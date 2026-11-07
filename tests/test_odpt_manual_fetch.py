import io, json, os, tempfile, unittest, zipfile
from pathlib import Path
from scripts import odpt_manual_fetch as fetch, odpt_source_contract as contract, odpt_source_store as store

def gtfs():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        for n in ('feed_info.txt','calendar.txt','calendar_dates.txt','stops.txt','routes.txt','trips.txt','stop_times.txt'):
            z.writestr(n,'feed_version,feed_start_date,feed_end_date\nfixture,20260101,20261231\n' if n=='feed_info.txt' else 'fixture\n')
    return b.getvalue()

class ManualFetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='/private/tmp'); self.root=Path(self.tmp.name); self.parent=self.root/'private';self.parent.mkdir(mode=0o700);os.chmod(self.parent,0o700)
        self.responses={s:(200,'application/json',json.dumps([{'@id':'urn:test','dc:date':'2026-10-08'}],separators=(',',':')).encode()) for s in contract.SOURCE_IDS}
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
    def test_live_transport_is_disabled(self): self.assertFalse(fetch.LIVE_TRANSPORT_ENABLED)


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
        return fetch.acquire(root,sid,lambda:'DUMMY-SECRET-123',exchange=exchange or (lambda url: response or Response()))
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
        with patch.object(fetch,'LIVE_TRANSPORT_ENABLED',True),patch.object(fetch.http.client,'HTTPSConnection') as conn:
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

if __name__ == '__main__': unittest.main()
