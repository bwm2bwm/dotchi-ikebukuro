"""Only generated fixtures and injected communication; no private saved inputs."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from scripts import odpt_manual_fetch as fetch
from scripts import odpt_evaluation_input as adapter
from scripts import odpt_fetch_evaluate as entry
from scripts import odpt_source_store as store
from scripts import odpt_source_contract as contract
from tests.test_odpt_manual_fetch import Response, source_body
from tests.test_odpt_gtfs_loader import fixture, archive
from tests.test_odpt_snapshot_qa import make_snapshot


class FetchEvaluationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir='/private/tmp'); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.raw = self.root/'legacy-raw'; self.raw.mkdir()
        tables = fixture()
        tables['feed_info'][0].update(feed_version='fixture', feed_start_date='20260101', feed_end_date='20261231')
        self.responses = {sid: (200, 'application/json', source_body(sid)) for sid in contract.SOURCE_IDS if sid != 'metro.gtfs'}
        self.responses['metro.gtfs'] = (200, 'application/zip', archive(tables))
        for sid, name in contract.SOURCE_FILES.items(): (self.raw/name).write_bytes(self.responses[sid][2])
        self.legacy = self.root/'legacy'; store.persist_snapshot(self.legacy, self.raw)
        self.batch = self.root/'candidate'

    def batch_create(self, retry=False):
        responses = dict(self.responses)
        if retry: responses.pop('metro.gtfs')
        fetch.capture_mock_batch(self.batch, responses)
        if retry:
            rec = fetch.acquire(self.batch, 'metro.gtfs', lambda: 'mock-key', exchange=lambda url: Response(body=self.responses['metro.gtfs'][2], content_type='application/zip'))
            self.assertEqual(rec['outcome'], 'succeeded')
            fetch.finalize(self.batch)
        return self.batch

    def digest_tree(self):
        return {str(p.relative_to(self.root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_ino, p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def run_stage(self, stage, **kwargs):
        return entry.evaluate(self.legacy, self.raw, self.batch, stage=stage, **kwargs)

    def test_normal_retry_selects_seven_without_erasing_history_or_copying(self):
        self.batch_create(retry=True); before = self.digest_tree()
        loaded = adapter.load_fetch_batch(self.batch)
        self.assertEqual(len(loaded['records']), 7); self.assertEqual(len(loaded['attemptRecords']), 8)
        contract.validate_snapshot(loaded['snapshot'], loaded['attemptRecords'])
        self.assertTrue(all(r['outcome']=='succeeded' for r in loaded['records']))
        # Existing strict reader remains strict (no schema/layout relaxation).
        with self.assertRaises(store.StoreError): store.load_store_contract(self.batch)
        report = self.run_stage('2a')
        self.assertEqual(report['reports']['basic']['overallBasicStatus'], 'identical')
        self.assertEqual(before, self.digest_tree())
        batch = fetch._read_json(self.batch/'batch.json')
        self.assertIs(batch['publicationApproved'], False); self.assertIsNone(batch['applicationPeriod'])
        self.assertEqual(loaded['snapshot']['crossSourceConsistency'], 'not-evaluated')

    def test_phase2a_changed_and_phase2b_known_equivalent_and_changed(self):
        # Only synthetic fixture changes are made before capture.
        self.batch_create()
        unchanged = self.run_stage('2b')['reports']['semantic']
        self.assertEqual(unchanged['comparisonStatus'], 'complete')
        self.assertEqual(unchanged['semanticStatus'], 'equivalent')
        self.assertEqual(len(unchanged['sourceResults']), 7)
        tables = fixture(); tables['feed_info'][0].update(feed_version='fixture', feed_start_date='20260101', feed_end_date='20261231')
        tables['routes'][0]['route_short_name'] = 'New'
        changed = self.root/'changed'; values = dict(self.responses); values['metro.gtfs']=(200,'application/zip',archive(tables))
        fetch.capture_mock_batch(changed, values)
        a = entry.evaluate(self.legacy,self.raw,changed,stage='2a')
        b = entry.evaluate(self.legacy,self.raw,changed,stage='2b')
        self.assertEqual(a['reports']['basic']['overallBasicStatus'],'changed')
        self.assertEqual(b['reports']['semantic']['semanticStatus'],'changed')

    def test_bad_batch_inputs_stop_before_engines(self):
        cases = ['batch','duplicate','parent','selected-failure','raw','bytes','fingerprint','reference','branch','approval']
        for index, case in enumerate(cases):
            with self.subTest(case=case):
                self.batch=self.root/('bad-'+str(index));self.batch_create(retry=True)
                snap_path=self.batch/'snapshot.json'; snap=fetch._read_json(snap_path)
                files=list((self.batch/'attempts').glob('*/result.json'))
                successes=[p for p in files if fetch._read_json(p)['outcome']=='succeeded']
                failures=[p for p in files if fetch._read_json(p)['outcome']=='failed']
                p=successes[0]; rec=fetch._read_json(p)
                if case=='batch': rec['batchId']='00000000-0000-0000-0000-000000000001'
                elif case=='duplicate': rec['recordId']=fetch._read_json(successes[1])['recordId']
                elif case=='parent': rec['retryOfAttemptId']='00000000-0000-0000-0000-000000000001'
                elif case=='bytes': rec['artifact']['sizeBytes']+=1
                elif case=='branch':
                    # Incomplete unexpected attempt is refused, never ignored.
                    (self.batch/'attempts'/'orphan').mkdir(mode=0o700)
                elif case=='selected-failure':
                    fail=fetch._read_json(failures[0]);snap['selectedRecords'][fail['sourceId']]=fail['recordId']
                elif case=='raw':
                    raw=self.batch/'raw'/contract.SOURCE_FILES[rec['sourceId']];raw.write_bytes(raw.read_bytes()+b' ')
                elif case=='fingerprint':snap['contentFingerprint']='0'*64
                elif case=='reference':snap['selectedRecords'][rec['sourceId']]='00000000-0000-0000-0000-000000000001'
                elif case=='approval':
                    path=self.batch/'batch.json';value=fetch._read_json(path);value['publicationApproved']=True;path.write_text(json.dumps(value))
                if case in ('batch','duplicate','parent','bytes'):p.write_text(json.dumps(rec))
                snap_path.write_text(json.dumps(snap))
                with patch.object(entry.basic,'compare_stores',side_effect=AssertionError('engine must not run')) as engine:
                    with self.assertRaises(Exception):self.run_stage('2a')
                    engine.assert_not_called()

    def test_incomplete_and_wrong_baseline_raw_fail_closed(self):
        responses=dict(self.responses);responses.pop('metro.gtfs');fetch.capture_mock_batch(self.batch,responses)
        with self.assertRaises(store.StoreError):self.run_stage('2a')

        self.batch=self.root/'complete';self.batch_create()
        (self.raw/'Station_all.json').write_bytes(b'[{}]')
        with self.assertRaises(store.StoreError):self.run_stage('2a')

    def test_opaque_gtfs_partial_is_preserved(self):
        tables=fixture()
        tables['feed_info'][0].update(feed_version='fixture',feed_start_date='20260101',feed_end_date='20261231')
        tables['trips'][0]['block_id']='opaque-block'
        self.responses['metro.gtfs']=(200,'application/zip',archive(tables))
        self.batch_create()
        report=self.run_stage('2b')['reports']['semantic']
        self.assertEqual(report['comparisonStatus'],'partial')
        self.assertEqual(report['semanticStatus'],'indeterminate')

    def test_post_evaluation_metadata_mutation_is_rejected(self):
        self.batch_create();original=entry.basic.compare_stores
        def mutate(*args):
            result=original(*args)
            path=self.batch/'snapshot.json';path.write_bytes(path.read_bytes()+b' ')
            return result
        with patch.object(entry.basic,'compare_stores',side_effect=mutate):
            with self.assertRaises(store.StoreError):self.run_stage('2a')

    def test_candidate_replaced_before_binding_is_rejected(self):
        self.batch_create();original=entry._bind;calls=[]
        def mutate(*args):
            calls.append(args)
            if len(calls)==1:
                path=self.batch/'snapshot.json';snap=fetch._read_json(path)
                snap['snapshotId']='00000000-0000-0000-0000-000000000001';path.write_text(json.dumps(snap))
            return original(*args)
        with patch.object(entry,'_bind',side_effect=mutate),patch.object(entry.basic,'compare_stores') as engine:
            with self.assertRaises(store.StoreError):self.run_stage('2a')
            engine.assert_not_called()

    def test_cli_summary_no_source_body_or_paths(self):
        self.batch_create();out=io.StringIO()
        args=['--baseline-store',str(self.legacy),'--baseline-raw',str(self.raw),'--candidate-batch',str(self.batch),'--stage','2a']
        with redirect_stdout(out):self.assertEqual(entry.main(args),0)
        self.assertNotIn(str(self.root),out.getvalue());self.assertIn('"publicationApproved": false',out.getvalue())

    def test_bad_explicit_scope_stops_before_quality_collection(self):
        self.batch_create()
        with patch.object(entry.quality_diff, 'compare_quality') as collect:
            with self.assertRaises(ValueError):
                self.run_stage('2c',service_dates=['2026-10-28'],observation_instant='2026-10-29T03:00:00Z',dom_station_ids=['Invalid'])
            collect.assert_not_called()

    def test_basic_unavailable_is_not_cli_success(self):
        self.batch_create()
        path=self.legacy/'sources'/'metro.station.json';rec=fetch._read_json(path)
        rec['metadata']={'status':'unavailable','odpt':None,'gtfs':None};path.write_text(json.dumps(rec))
        out=io.StringIO()
        with redirect_stdout(out):
            code=entry.main(['--baseline-store',str(self.legacy),'--baseline-raw',str(self.raw),'--candidate-batch',str(self.batch),'--stage','2a'])
        self.assertEqual(code,2);self.assertIn('unavailable',out.getvalue())

    def test_phase2c_real_synthetic_generator_v2_board_and_dom(self):
        raw=make_snapshot(self.root/'quality-raw')
        for sid, name in contract.SOURCE_FILES.items():
            if sid != 'metro.gtfs': (raw/name).write_bytes(source_body(sid))
        legacy=self.root/'quality-store';store.persist_snapshot(legacy,raw)
        responses={sid:(200,'application/zip' if sid=='metro.gtfs' else 'application/json',(raw/name).read_bytes()) for sid,name in contract.SOURCE_FILES.items()}
        batch=self.root/'quality-fetch';fetch.capture_mock_batch(batch,responses)
        before=self.digest_tree()
        result=entry.evaluate(legacy,raw,batch,stage='2c',service_dates=['2026-10-28','2026-10-29','2026-10-30'],observation_instant='2026-10-29T03:00:00Z',dom_station_ids=['Senkawa','Hikawadai'])
        self.assertEqual(result['reports']['quality']['inputReadiness'],'ready')
        self.assertEqual(result['reports']['display']['inputReadiness'],'ready')
        for role in ('baselineDom','candidateDom'):self.assertEqual(result['reports'][role]['domQaStatus'],'complete')
        self.assertFalse(result['publicationApproved']);self.assertIsNone(result['applicationPeriod'])
        self.assertEqual(result['crossSourceConsistency'],'not-evaluated')
        self.assertEqual(before,self.digest_tree())
        self.assertGreater(result['reports']['candidateDom']['checks']['inputImmutability']['storeFileCount'],8)


if __name__=='__main__': unittest.main()
