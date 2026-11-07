import io, json, os, tempfile, unittest, zipfile
from pathlib import Path
from scripts import odpt_manual_fetch as fetch, odpt_source_contract as contract, odpt_source_store as store

def gtfs():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        for n in ('feed_info.txt','calendar.txt','calendar_dates.txt','stops.txt','routes.txt','trips.txt','stop_times.txt'):
            z.writestr(n,'feed_version,feed_start_date,feed_end_date\nfixture,20260101,20261231\n' if n=='feed_info.txt' else 'fixture\n')
    return b.getvalue()


def source_body(sid):
    """Synthetic scope-correct records; no saved ODPT input is used."""
    kind = {'railway':'Railway', 'station':'Station', 'train-timetable':'TrainTimetable',
            'station-timetable':'StationTimetable'}[sid.split('.')[1]]
    lines = [sid.split('.')[2].capitalize()] if len(sid.split('.')) == 3 else ['Yurakucho', 'Fukutoshin']
    rows = []
    for line in lines:
        railway = 'odpt.Railway:TokyoMetro.' + line
        station = 'odpt.Station:TokyoMetro.' + line + '.Fixture'
        row = {'@context':'http://vocab.odpt.org/context_odpt_' + kind + '.jsonld',
               '@type':'odpt:' + kind, '@id':'urn:test:' + kind + line,
               'owl:sameAs':railway if kind == 'Railway' else station if kind == 'Station' else 'urn:test:' + kind + line,
               'dc:date':'2026-10-08', 'odpt:operator':'odpt.Operator:TokyoMetro'}
        if kind != 'Railway': row['odpt:railway'] = railway
        if kind == 'TrainTimetable':
            from tests.test_odpt_train_semantic_diff import record
            row = record(line=line); row['odpt:operator'] = 'odpt.Operator:TokyoMetro'
        if kind == 'StationTimetable':
            row.update({'odpt:station':station, 'odpt:railDirection':'urn:direction:north',
                        'odpt:calendar':'urn:calendar:weekday', 'odpt:stationTimetableObject':[]})
        rows.append(row)
    return json.dumps(rows, separators=(',', ':')).encode()

class ManualFetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='/private/tmp'); self.root=Path(self.tmp.name); self.parent=self.root/'private';self.parent.mkdir(mode=0o700);os.chmod(self.parent,0o700)
        self.responses={s:(200,'application/json',source_body(s)) for s in contract.SOURCE_IDS if s != 'metro.gtfs'}
        self.responses['metro.gtfs']=(200,'application/zip',gtfs())
    def tearDown(self): self.tmp.cleanup()
    def test_seven_raw_sources_and_fetch_snapshot(self):
        out=fetch.capture_mock_batch(self.parent/'batch',self.responses);self.assertEqual(out['successCount'],7);self.assertTrue(out['snapshotCreated'])
        snap=json.loads((self.parent/'batch'/'snapshot.json').read_bytes());self.assertEqual(snap['mode'],'fetch');self.assertEqual(snap['acquisitionStatus'],'fetch-success')
        self.assertFalse(any('publicationApproved' in x for x in [snap]));self.assertEqual(snap['crossSourceConsistency'],'not-evaluated')
        for sid,name in contract.SOURCE_FILES.items(): self.assertEqual((self.parent/'batch'/'raw'/name).read_bytes(),self.responses[sid][2])
    def test_failed_source_does_not_create_snapshot_and_keeps_history(self):
        bad=dict(self.responses);bad.pop('metro.gtfs');out=fetch.capture_mock_batch(self.parent/'partial',bad)
        self.assertEqual(out['successCount'],6);self.assertFalse(out['snapshotCreated']);self.assertFalse((self.parent/'partial'/'snapshot.json').exists())
        self.assertEqual(len(fetch.history(self.parent/'partial')[1]),7)
    def test_existing_batch_and_symlink_refused(self):
        p=self.parent/'already';p.mkdir();
        with self.assertRaises(Exception): fetch.capture_mock_batch(p,self.responses)
        link=self.parent/'link';link.symlink_to(self.parent/'already',target_is_directory=True)
        with self.assertRaises(Exception): fetch.capture_mock_batch(link,self.responses)
    def test_invalid_payload_and_oversize_rejected(self):
        with self.assertRaises(Exception): fetch.make_fetch_record('metro.station', '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002','2026-01-01T00:00:00Z','2026-01-01T00:00:01Z',200,'application/json',b'{')
        with self.assertRaises(Exception): fetch.make_fetch_record('metro.station','00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002','2026-01-01T00:00:00Z','2026-01-01T00:00:01Z',200,'application/json',b'x'*(fetch.MAX_RESPONSE_BYTES+1))
    def test_live_transport_is_disabled(self): self.assertIsNone(fetch._LIVE_PLAN.get())


from unittest.mock import patch
import contextlib, ssl, socket, hashlib

class Response:
    def __init__(self, status=200, body=b'[]', content_type='application/json', headers=None, failure=None):
        self.status=status; self.headers={'Content-Type':content_type, **(headers or {})}; self.stream=io.BytesIO(body);self.failure=failure;self.closed=False
    def getheader(self,key): return self.headers.get(key)
    def read(self,count):
        if self.failure: raise self.failure
        return self.stream.read(count)
    def close(self): self.closed=True

class TransportAndHistoryTests(unittest.TestCase):
    setUp = ManualFetchTests.setUp
    tearDown = ManualFetchTests.tearDown
    def make(self): return fetch.new_batch(self.parent/'batch')
    def attempt(self, root, response=None, sid='metro.station', exchange=None):
        return fetch.acquire(root,sid,lambda:'DUMMY-SECRET-123',exchange=exchange or (lambda url: response or Response(body=source_body(sid))))
    def test_http_errors_timeout_tls_are_safe_failed_records(self):
        cases=[(lambda url:Response(404),'http_status_failed'),(lambda url:Response(500),'http_status_failed')]
        for exc,code in [(TimeoutError('DUMMY-SECRET-123'),'timeout'),(ssl.SSLCertVerificationError('DUMMY-SECRET-123'),'tls_failed')]:
            def fail(url,exc=exc): raise exc
            cases.append((fail,code))
        for index,(exchange,code) in enumerate(cases):
            root=fetch.new_batch(self.parent/str(index)); rec=self.attempt(root,exchange=exchange)
            self.assertEqual(rec['outcome'],'failed');self.assertEqual(rec['errorCode'],code)
            self.assertEqual(fetch.history(root)[1][0]['outcome'],'failed')
            with self.assertRaises(Exception):fetch.finalize(root)
            self.assertFalse((root/'snapshot.json').exists())
    def test_interrupt_retry_preserves_parent_and_success(self):
        root=self.make()
        def stop(url): raise KeyboardInterrupt()
        first=self.attempt(root,exchange=stop);second=self.attempt(root)
        self.assertEqual(first['outcome'],'interrupted');self.assertIsNone(first['finishedAt'])
        self.assertEqual(second['retryOfAttemptId'],first['attemptId']); self.assertNotEqual(first['attemptId'],second['attemptId'])
        self.assertEqual(len(fetch.history(root)[1]),2)
        with self.assertRaises(fetch.FetchError): self.attempt(root)
    def test_failed_manual_retry_completes_snapshot_with_full_retry_chain(self):
        bad=dict(self.responses); bad.pop('metro.gtfs');root=self.parent/'batch';fetch.capture_mock_batch(root,bad)
        old=fetch.history(root)[1]; parent=next(r for r in old if r['sourceId']=='metro.gtfs')
        rec=self.attempt(root,Response(body=gtfs(),content_type='application/zip'),sid='metro.gtfs')
        self.assertEqual(rec['retryOfAttemptId'],parent['attemptId']);snap=fetch.finalize(root)
        self.assertEqual(len(fetch.history(root)[1]),8);contract.validate_snapshot(snap,fetch.history(root)[1])
        self.assertFalse(fetch._read_json(root/'batch.json')['publicationApproved'])
        self.assertIsNone(fetch._read_json(root/'batch.json')['applicationPeriod'])
    def test_invalid_json_zip_and_content_type(self):
        for index,(sid,response) in enumerate([('metro.station',Response(body=b'{')),('metro.gtfs',Response(body=b'no zip',content_type='application/zip')),('metro.station',Response(content_type='text/html; DUMMY-SECRET-123'))]):
            root=fetch.new_batch(self.parent/str(index));rec=self.attempt(root,response,sid)
            self.assertEqual(rec['outcome'],'failed');self.assertFalse((root/'raw'/contract.SOURCE_FILES[sid]).exists())
            if index<2:self.assertEqual(rec['http']['responses'][-1]['status'],200)
    def test_size_length_encoding_and_truncation(self):
        for response in [Response(body=b'[]'*100),Response(headers={'Content-Length':'999'}),Response(headers={'Content-Length':'10'}),Response(headers={'Content-Encoding':'gzip'})]:
            with patch.object(fetch,'MAX_RESPONSE_BYTES',16):
                with self.assertRaises(fetch.FetchError):fetch.transport('metro.station',lambda:'DUMMY-SECRET-123',lambda url:response)
            self.assertTrue(response.closed)
    def test_bad_redirects_and_json_redirect_never_follow(self):
        locations=['http://dataodpt.blob.core.windows.net/x','https://evil.example/x','https://user@dataodpt.blob.core.windows.net/x','https://dataodpt.blob.core.windows.net:444/x','https://dataodpt.blob.core.windows.net/x?acl:consumerKey=anything','https://dataodpt.blob.core.windows.net/x?sig=DUMMY-SECRET-123','https://dataodpt.blob.core.windows.net/x#fragment']
        for location in locations:
            calls=[]
            def exchange(url):calls.append(url);return Response(302,headers={'Location':location})
            with self.assertRaises(fetch.FetchError):fetch.transport('metro.gtfs',lambda:'DUMMY-SECRET-123',exchange)
            self.assertEqual(len(calls),1)
        with self.assertRaises(fetch.FetchError):fetch.transport('metro.station',lambda:'DUMMY-SECRET-123',lambda url:Response(302))
    def test_allowed_redirect_records_identifiers_only(self):
        calls=[]
        def exchange(url):
            calls.append(url)
            return Response(302,headers={'Location':'https://dataodpt.blob.core.windows.net/feed.zip?sig=SIGNED'}) if len(calls)==1 else Response(body=gtfs(),content_type='application/octet-stream')
        root=self.make(); rec=self.attempt(root,sid='metro.gtfs',exchange=exchange)
        self.assertEqual(rec['outcome'],'succeeded');self.assertNotIn('consumerKey',calls[1]); self.assertEqual(len(rec['http']['responses']),2)
        for path in root.rglob('*.json'):
            content=path.read_bytes(); self.assertNotIn(b'SIGNED',content);self.assertNotIn(b'DUMMY-SECRET-123',content)
    def test_history_persistence_failure_cannot_succeed_or_finalize(self):
        root=self.make(); original=fetch._save
        def fail(directory,name,value):
            if name=='result.json':raise fetch.FetchError('persistence_failed')
            return original(directory,name,value)
        with patch.object(fetch,'_save',side_effect=fail):
            with self.assertRaises(fetch.FetchError):self.attempt(root)
        self.assertEqual(fetch.history(root)[1][0]['outcome'],'interrupted')
        with self.assertRaises(Exception):fetch.finalize(root)
        # Orphan raw is never silently overwritten on retry.
        with self.assertRaises(Exception):self.attempt(root)
    def test_hash_bytes_missing_source_batch_and_symlink_refuse_finalization(self):
        for index,mode in enumerate(['hash','bytes','missing','symlink','batch','source']):
            root=self.parent/str(index);bad=dict(self.responses);bad.pop('metro.gtfs');fetch.capture_mock_batch(root,bad)
            self.attempt(root,Response(body=gtfs(),content_type='application/zip'),sid='metro.gtfs')
            target=root/'raw'/contract.SOURCE_FILES['metro.station']
            if mode=='hash':target.write_bytes(target.read_bytes().replace(b'urn:test',b'urn:best'))
            elif mode=='bytes':target.write_bytes(target.read_bytes()+b' ')
            elif mode=='missing':target.unlink()
            elif mode=='symlink':target.unlink();target.symlink_to(root/'raw'/contract.SOURCE_FILES['metro.railway'])
            else:
                record=next(p for p in (root/'attempts').glob('*/result.json') if json.loads(p.read_bytes())['sourceId']=='metro.station')
                obj=json.loads(record.read_bytes());obj['batchId' if mode=='batch' else 'sourceId']='00000000-0000-0000-0000-000000000001' if mode=='batch' else 'metro.railway';record.write_text(json.dumps(obj))
            with self.assertRaises(Exception):fetch.finalize(root)
            self.assertFalse((root/'snapshot.json').exists())
    def test_secret_exception_header_echo_and_cli_never_leak(self):
        root=self.make(); output=io.StringIO()
        def explode(url):raise RuntimeError(url+' Authorization: DUMMY-SECRET-123')
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):rec=self.attempt(root,exchange=explode)
        self.assertEqual(rec['errorCode'],'transport_failed');self.assertEqual(output.getvalue(),'')
        echo=self.attempt(root,Response(body=b'DUMMY-SECRET-123'))
        self.assertEqual(echo['errorCode'],'credential_echo_rejected')
        for path in root.rglob('*'):
            if path.is_file():self.assertNotIn(b'DUMMY-SECRET-123',path.read_bytes())
        with patch.object(fetch,'env_credential',side_effect=AssertionError('must not read')),patch.object(socket,'create_connection',side_effect=AssertionError('network forbidden')):
            with contextlib.redirect_stderr(output):self.assertEqual(fetch.main(['fetch','--batch',str(self.parent/'unused'),'--enable-live-transport']),2)
            with self.assertRaises(fetch.FetchError):fetch.transport('metro.station',fetch.env_credential)
            self.assertFalse((self.parent/'unused').exists())
    def test_path_traversal_repository_and_raw_symlink(self):
        for p in [Path('relative'),self.parent/'..'/'escape',store.PROJECT_ROOT/'forbidden']:
            with self.assertRaises(Exception):fetch.new_batch(p)
        root=self.make();outside=self.parent/'outside';outside.mkdir(mode=0o700);(root/'raw').rmdir();(root/'raw').symlink_to(outside)
        with self.assertRaises(Exception):self.attempt(root)
        self.assertEqual(list(outside.iterdir()),[])
    def test_transport_tls_verification_and_two_timeouts(self):
        # No real socket: the HTTPSConnection adapter is replaced in its entirety.
        with patch.object(fetch,'_require_live_policy'),patch.object(fetch.http.client,'HTTPSConnection') as conn:
            conn.return_value.getresponse.return_value=Response()
            response=fetch._https_exchange('https://api.odpt.org/api/v4/odpt:Station')
            kwargs=conn.call_args.kwargs
            self.assertEqual(kwargs['context'].verify_mode,ssl.CERT_REQUIRED);self.assertTrue(kwargs['context'].check_hostname)
            self.assertEqual(kwargs['timeout'],fetch.CONNECT_TIMEOUT);conn.return_value.sock.settimeout.assert_called_with(fetch.READ_TIMEOUT)
            response.close();conn.return_value.close.assert_called()
    def test_invalid_cli_arguments_do_not_echo_secret_values(self):
        output=io.StringIO()
        with contextlib.redirect_stderr(output):
            with self.assertRaises(SystemExit):fetch.main(['fetch','--batch','/private/tmp/unused','--key','DUMMY-SECRET-123'])
        self.assertEqual(output.getvalue(),'cli_arguments_invalid\n')

    def test_every_history_write_failure_is_fail_closed(self):
        for index, filename in enumerate(['started.json', 'evidence.json', 'Station_all.json', 'result.json']):
            root=fetch.new_batch(self.parent/str(index)); original=fetch._save
            def failing(directory,name,value):
                if name==filename: raise fetch.FetchError('persistence_failed')
                return original(directory,name,value)
            with patch.object(fetch,'_save',side_effect=failing):
                with self.assertRaises(fetch.FetchError):self.attempt(root)
            with self.assertRaises(Exception):fetch.finalize(root)
            self.assertFalse((root/'snapshot.json').exists())
    def test_read_failure_and_second_pass_mutation(self):
        root=self.make(); rec=self.attempt(root,Response(failure=OSError('DUMMY-SECRET-123')))
        self.assertEqual(rec['outcome'],'failed');self.assertIsNone(rec['artifact'])
        self.assertFalse((root/'raw'/'Station_all.json').exists())
        good=self.parent/'good';fetch.capture_mock_batch(good,self.responses)
        (good/'snapshot.json').unlink()  # Synthetic test only: reopen finalization fixture.
        original=fetch._stable_read;calls=[]
        def mutate(path,sid):
            result=original(path,sid);calls.append(path)
            if len(calls)==7:calls[0].write_bytes(calls[0].read_bytes()+b' ')
            return result
        with patch.object(fetch,'_stable_read',side_effect=mutate):
            with self.assertRaises(Exception):fetch.finalize(good)
        self.assertFalse((good/'snapshot.json').exists())




class DriverAndProvenanceTests(unittest.TestCase):
    setUp = ManualFetchTests.setUp
    tearDown = ManualFetchTests.tearDown

    def exchange(self, calls, fail_sid=None, failure=None):
        from urllib.parse import urlsplit, parse_qs
        def send(url):
            parsed=urlsplit(url); params=parse_qs(parsed.query)
            self.assertEqual(params.pop('acl:consumerKey'), ['DUMMY-DRIVER-KEY'])
            found=[]
            for sid in contract.SOURCE_FILES:
                base, filters=fetch.endpoint(sid)
                if parsed.path==urlsplit(base).path and params=={k:[v] for k,v in filters.items()}:found.append(sid)
            self.assertEqual(len(found),1);sid=found[0];calls.append(sid)
            self.assertNotIn('date',params)
            if sid==fail_sid:
                if isinstance(failure, BaseException):raise failure
                return Response(status=failure or 500)
            status,ctype,body=self.responses[sid]
            return Response(status,body,ctype)
        return send

    def run_cli(self, path, calls, *, command='fetch', source=None, fail_sid=None, failure=None):
        args=[command,'--batch',str(path)]
        if source:args+=['--source',source]
        stdout=io.StringIO();stderr=io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            code=fetch.main(args,exchange=self.exchange(calls,fail_sid,failure),credential_provider=lambda:'DUMMY-DRIVER-KEY')
        for value in (stdout.getvalue(),stderr.getvalue()):
            self.assertNotIn('DUMMY-DRIVER-KEY',value);self.assertNotIn(str(self.parent),value)
        return code,stdout.getvalue(),stderr.getvalue()

    def tree(self, root):
        return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}

    def test_cli_calls_fixed_seven_driver_and_finalizes_without_reformatting(self):
        from scripts import odpt_evaluation_input as adapter
        root=self.parent/'batch';calls=[]
        code,out,err=self.run_cli(root,calls)
        self.assertEqual(code,0);self.assertFalse(err);self.assertEqual(calls,list(contract.SOURCE_FILES))
        self.assertEqual(json.loads(out)['driverStatus'],'complete')
        loaded=adapter.load_fetch_batch(root);self.assertEqual(len(loaded['records']),7)
        batch=fetch._read_json(root/'batch.json');self.assertEqual(batch['schemaVersion'],2)
        self.assertEqual(batch['provenance']['transport'],'offline-injected')
        self.assertIs(batch['publicationApproved'],False);self.assertIsNone(batch['applicationPeriod'])
        self.assertEqual(loaded['snapshot']['crossSourceConsistency'],'not-evaluated')
        for sid,name in contract.SOURCE_FILES.items():self.assertEqual((root/'raw'/name).read_bytes(),self.responses[sid][2])
        before=self.tree(root);calls=[];code,_,_=self.run_cli(root,calls)
        self.assertEqual(code,2);self.assertFalse(calls);self.assertEqual(before,self.tree(root))

    def test_first_http_timeout_and_interrupt_stop_without_snapshot(self):
        sid=list(contract.SOURCE_FILES)[2]
        for index,failure in enumerate([403,500,TimeoutError('DUMMY-DRIVER-KEY'),KeyboardInterrupt()]):
            root=self.parent/str(index);calls=[];code,_,_=self.run_cli(root,calls,fail_sid=sid,failure=failure)
            self.assertEqual(code,2);self.assertEqual(calls,list(contract.SOURCE_FILES)[:3])
            self.assertFalse((root/'snapshot.json').exists());batch,records=fetch.history(root)
            self.assertEqual(len(records),3)
            failed=next(r for r in records if r['sourceId']==sid)
            self.assertEqual(failed['outcome'],'interrupted' if isinstance(failure,KeyboardInterrupt) else 'failed')
            with self.assertRaises(Exception):fetch.finalize(root)

    def test_manual_retry_preserves_all_old_records_and_only_fetches_missing(self):
        for index,failure in enumerate([500,KeyboardInterrupt()]):
            root=self.parent/str(index);failed=list(contract.SOURCE_FILES)[2];calls=[]
            self.run_cli(root,calls,fail_sid=failed,failure=failure)
            before=self.tree(root);old=next(r for r in fetch.history(root)[1] if r['sourceId']==failed)
            calls=[];code,_,_=self.run_cli(root,calls,command='retry',source=failed)
            self.assertEqual(code,0);self.assertEqual(calls,list(contract.SOURCE_FILES)[2:])
            after=self.tree(root);self.assertTrue(all(after[k]==v for k,v in before.items()))
            records=fetch.history(root)[1];self.assertEqual(len(records),8)
            retry=next(r for r in records if r['sourceId']==failed and r['outcome']=='succeeded')
            self.assertEqual(retry['retryOfAttemptId'],old['attemptId'])
            contract.validate_snapshot(fetch._read_json(root/'snapshot.json'),records)

    def test_retry_of_success_and_raw_corruption_stop_before_transport(self):
        root=self.parent/'batch';first,failed=list(contract.SOURCE_FILES)[:2];calls=[]
        self.run_cli(root,calls,fail_sid=failed)
        before=self.tree(root);calls=[];code,_,_=self.run_cli(root,calls,command='retry',source=first)
        self.assertEqual(code,2);self.assertFalse(calls);self.assertEqual(before,self.tree(root))
        path=root/'raw'/contract.SOURCE_FILES[first];path.write_bytes(path.read_bytes()+b' ')
        calls=[];code,_,_=self.run_cli(root,calls,command='retry',source=failed)
        self.assertEqual(code,2);self.assertFalse(calls);self.assertFalse((root/'snapshot.json').exists())

    def test_process_stop_between_attempts_can_continue_without_invented_parent(self):
        root=self.parent/'between';calls=[];original=fetch.acquire
        def stop_after_success(*args,**kwargs):
            original(*args,**kwargs)
            raise KeyboardInterrupt()
        with patch.object(fetch,'acquire',side_effect=stop_after_success):
            code,_,_=self.run_cli(root,calls)
        self.assertEqual(code,2);self.assertEqual(len(fetch.history(root)[1]),1)
        self.assertFalse((root/'snapshot.json').exists());before=self.tree(root)
        calls=[];code,_,_=self.run_cli(root,calls,command='retry',source=list(contract.SOURCE_FILES)[1])
        self.assertEqual(code,0);self.assertEqual(calls,list(contract.SOURCE_FILES)[1:])
        after=self.tree(root);self.assertTrue(all(after[k]==v for k,v in before.items()))
        self.assertTrue(all(r['retryOfAttemptId'] is None for r in fetch.history(root)[1]))

    def test_incomplete_or_changed_body_cannot_be_finalized_by_driver(self):
        root=self.parent/'batch';calls=[];exchange=self.exchange(calls)
        def mutate(url):
            response=exchange(url)
            if calls[-1]=='metro.gtfs':
                path=root/'raw'/'Station_all.json';path.write_bytes(path.read_bytes()+b' ')
            return response
        with self.assertRaises(fetch.FetchError):fetch.run_fetch(root,lambda:'DUMMY-DRIVER-KEY',exchange=mutate)
        self.assertFalse((root/'snapshot.json').exists())

    def test_constant_option_and_environment_cannot_enable_network(self):
        root=self.parent/'blocked'
        with patch.object(fetch,'env_credential',side_effect=AssertionError('secret read')) as key,patch.object(fetch.http.client,'HTTPSConnection',side_effect=AssertionError('network')) as network:
            for extra in ([],['--enable-live-transport']):
                output=io.StringIO()
                with contextlib.redirect_stderr(output):self.assertEqual(fetch.main(['fetch','--batch',str(root)]+extra),2)
            with self.assertRaises(fetch.FetchError):fetch.transport('metro.station',fetch.env_credential)
            with self.assertRaises(fetch.FetchError):fetch._https_exchange('https://api.odpt.org/api/v4/odpt:Station')
            with self.assertRaises(fetch.FetchError):fetch.run_fetch(root,fetch.env_credential)
            key.assert_not_called();network.assert_not_called();self.assertFalse(root.exists())

    @staticmethod
    def format_fixture(root, *, version=2, mode='live-https'):
        # Synthetic future-live FORMAT only, never presented as an actual live fetch.
        p=root/'batch.json';batch=fetch._read_json(p);batch['schemaVersion']=version
        batch['provenance']['transport']=mode;p.write_text(json.dumps(batch))
        for p in (root/'attempts').glob('*/evidence.json'):
            evidence=fetch._read_json(p);evidence['schemaVersion']=version;evidence['transport']=mode;p.write_text(json.dumps(evidence))

    def test_future_live_format_with_retry_passes_existing_2a_2b(self):
        from tests.test_odpt_fetch_evaluate import FetchEvaluationTests, entry
        helper=FetchEvaluationTests();helper.setUp();self.addCleanup(helper.doCleanups)
        helper.batch_create(retry=True);self.format_fixture(helper.batch)
        before=helper.digest_tree()
        for stage in ('2a','2b'):
            result=helper.run_stage(stage);self.assertFalse(result['publicationApproved']);self.assertIsNone(result['applicationPeriod'])
        from scripts import odpt_evaluation_input as adapter
        self.assertEqual(len(adapter.load_fetch_batch(helper.batch)['attemptRecords']),8)
        self.assertEqual(before,helper.digest_tree())

    def test_synthetic_future_live_format_runs_existing_phase2c_without_weakening_validation(self):
        from tests.test_odpt_fetch_evaluate import FetchEvaluationTests
        helper=FetchEvaluationTests();helper.setUp();self.addCleanup(helper.doCleanups)
        original=fetch.capture_mock_batch
        def fixture(path,responses):
            result=original(path,responses)
            self.format_fixture(path)
            return result
        # Only the generated fixture format is converted. The adapter/engines are real.
        with patch.object(fetch,'capture_mock_batch',side_effect=fixture):
            helper.test_phase2c_real_synthetic_generator_v2_board_and_dom()

    def test_old_v1_offline_remains_readable_but_v1_live_is_rejected(self):
        from scripts import odpt_evaluation_input as adapter
        root=self.parent/'old';calls=[];self.run_cli(root,calls)
        self.format_fixture(root,version=1,mode='offline-injected');adapter.load_fetch_batch(root)
        self.format_fixture(root,version=1,mode='live-https')
        with self.assertRaises(store.StoreError):adapter.load_fetch_batch(root)

    def test_bad_or_mixed_provenance_is_fail_closed(self):
        from scripts import odpt_evaluation_input as adapter
        for index,case in enumerate(['unknown','mixed','time','extra','version']):
            root=self.parent/str(index);self.run_cli(root,[])
            p=root/'batch.json';batch=fetch._read_json(p)
            if case=='unknown':batch['provenance']['transport']='unverified'
            elif case=='mixed':
                evidence_path=next((root/'attempts').glob('*/evidence.json'));evidence=fetch._read_json(evidence_path)
                evidence['transport']='live-https';evidence_path.write_text(json.dumps(evidence))
            elif case=='time':batch['provenance']['retrievedAt']='2026-01-01T00:00:00Z'
            elif case=='extra':batch['provenance']['secret']='DUMMY-DRIVER-KEY'
            else:batch['schemaVersion']=True
            p.write_text(json.dumps(batch))
            with self.assertRaises(store.StoreError):adapter.load_fetch_batch(root)

    def test_mock_cannot_append_to_live_labeled_batch(self):
        root=fetch.new_batch(self.parent/'future',transport_mode='live-https');before=self.tree(root)
        exchange=self.exchange([])
        with self.assertRaises(fetch.FetchError):fetch.acquire(root,'metro.station',lambda:'DUMMY-DRIVER-KEY',exchange=exchange)
        self.assertEqual(before,self.tree(root))

    def test_cli_protects_secrets_in_failure_and_argument_errors(self):
        root=self.parent/'bad';calls=[]
        code,out,err=self.run_cli(root,calls,fail_sid=list(contract.SOURCE_FILES)[0],failure=RuntimeError('DUMMY-DRIVER-KEY url headers'))
        self.assertEqual(code,2)
        for p in root.rglob('*'):
            if p.is_file():self.assertNotIn(b'DUMMY-DRIVER-KEY',p.read_bytes())
        self.assertNotIn('url headers',out+err)


class LivePreparationTests(ManualFetchTests):
    def test_plan_and_confirmation_are_read_only_and_bound_to_destination(self):
        path = self.parent/'planned'
        with patch.object(fetch, 'env_credential', side_effect=AssertionError('secret')), patch.object(fetch.http.client, 'HTTPSConnection', side_effect=AssertionError('network')):
            plan = fetch.acquisition_plan(path)
            self.assertFalse(path.exists())
            self.assertEqual([r['sourceId'] for r in plan['sources']], list(contract.SOURCE_FILES))
            self.assertNotIn('consumerKey', json.dumps(plan))
            fetch.validate_live_confirmation(plan, True, plan['confirmation'])
            self.assertIsNone(fetch._LIVE_PLAN.get())  # Pure validation never enables live use.
            for enabled, value in [(False, plan['confirmation']), (True, None), (True, 'wrong')]:
                with self.assertRaises(fetch.FetchError): fetch.validate_live_confirmation(plan, enabled, value)
            other = fetch.acquisition_plan(self.parent/'other')
            self.assertNotEqual(plan['confirmation'], other['confirmation'])
            with self.assertRaises(fetch.FetchError): fetch.validate_live_confirmation(other, True, plan['confirmation'])

    def test_cli_authorized_dispatch_is_stubbed_before_any_live_session(self):
        path = self.parent/'planned'; plan = fetch.acquisition_plan(path)
        complete = {'driverStatus':'complete'}
        with patch.object(fetch, '_live_session', return_value=contextlib.nullcontext()) as session, patch.object(fetch, 'env_credential', return_value='DUMMY-ONLY') as provider, patch.object(fetch, 'run_fetch', return_value=complete) as driver, patch.object(fetch.http.client, 'HTTPSConnection', side_effect=AssertionError('network')):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(fetch.main(['fetch','--batch',str(path),'--enable-live-transport','--confirm-plan',plan['confirmation']]), 0)
            self.assertEqual(driver.call_args.args[1](), 'DUMMY-ONLY')
            provider.assert_called_once(); session.assert_called_once_with(plan)
            self.assertIsNone(fetch._LIVE_PLAN.get()); self.assertFalse(path.exists())

    def test_invalid_credentials_never_reach_exchange_or_create_live_batch(self):
        path = self.parent/'planned'; plan = fetch.acquisition_plan(path)
        for secret in (None, '', 'white space', 'line\n', '日本語', 123):
            with patch.object(fetch, '_live_session', side_effect=AssertionError('live session')) as session, patch.object(fetch.http.client, 'HTTPSConnection', side_effect=AssertionError('network')), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(fetch.main(['fetch','--batch',str(path),'--enable-live-transport','--confirm-plan',plan['confirmation']], credential_provider=lambda: secret), 2)
                session.assert_not_called(); self.assertFalse(path.exists())
            calls = []
            with self.assertRaises(fetch.FetchError):
                fetch.transport('metro.station', lambda: secret, lambda url: calls.append(url))
            self.assertFalse(calls)

    def test_scope_failures_stop_driver_and_keep_failed_history(self):
        sid = 'metro.railway'; rows = json.loads(source_body(sid))
        cases = [b'', b'[]', b'{}', b'[null]']
        for field, value in [('@type','odpt:Station'), ('@type',[]), ('odpt:operator','odpt.Operator:Other'), ('@id',None)]:
            wrong = [dict(rows[0], **{field:value})]; cases.append(json.dumps(wrong).encode())
        for index, body in enumerate(cases):
            calls = []
            root = self.parent/('bad'+str(index))
            def send(url): calls.append(url); return Response(body=body)
            result = fetch.run_fetch(root, lambda:'DUMMY-SCOPE', exchange=send)
            self.assertEqual(result['driverStatus'], 'stopped'); self.assertEqual(len(calls), 1)
            self.assertFalse((root/'snapshot.json').exists()); self.assertFalse((root/'raw'/contract.SOURCE_FILES[sid]).exists())
            self.assertEqual(fetch.history(root)[1][0]['outcome'], 'failed')
        sid = 'metro.train-timetable.yurakucho'; wrong = json.loads(source_body(sid))
        wrong[0]['odpt:railway'] = 'odpt.Railway:TokyoMetro.Fukutoshin'
        root = fetch.new_batch(self.parent/'wrong-line')
        rec = fetch.acquire(root, sid, lambda:'DUMMY-SCOPE', exchange=lambda url:Response(body=json.dumps(wrong).encode()))
        self.assertEqual(rec['errorCode'], 'response_filter_mismatch')

    def test_retry_plan_binds_history_and_rejects_offline_or_sealed_batches(self):
        root = fetch.new_batch(self.parent/'offline')
        with self.assertRaises(fetch.FetchError): fetch.acquisition_plan(root, 'metro.station')
        # Format-only fixture. No live session is entered.
        root = fetch.new_batch(self.parent/'live-format', transport_mode='live-https')
        first = fetch.acquisition_plan(root, 'metro.railway')
        self.assertNotEqual(first['confirmation'], fetch.acquisition_plan(root, 'metro.station')['confirmation'])
        self.assertIsNone(fetch._LIVE_PLAN.get())

    def test_live_flags_cannot_be_combined_with_mock_exchange(self):
        with patch.object(fetch.http.client,'HTTPSConnection',side_effect=AssertionError('network')), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fetch.main(['fetch','--batch',str(self.parent/'never'),'--enable-live-transport','--confirm-plan','wrong'], exchange=lambda url:Response(), credential_provider=lambda:'DUMMY'), 2)
        self.assertFalse((self.parent/'never').exists())


if __name__ == '__main__': unittest.main()
