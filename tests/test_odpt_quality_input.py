import copy
import io
import json
import os
import tempfile
import unittest
import hashlib
import uuid
from scripts import odpt_source_store as source_store
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import odpt_quality_input as quality
from tests import test_odpt_gtfs_semantic_diff as fixtures


class QualityInputTests(unittest.TestCase):
    def setUp(self):
        self.helper=fixtures.GTFSSemanticTests();self.helper.setUp()
        self.env={'python':{'version':'synthetic'},'node':{'versions':{'icu':'synthetic'}},'timezoneData':[{'name':'Asia/Tokyo','sha256':'1'*64}]}
        self.root=self.helper.root/'engine';self.root.mkdir()
        # Synthetic engine code only; no real source data is copied.
        for name in quality.SEEDS:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# synthetic\n' if p.suffix=='.py' else '// synthetic\n')
        actual=quality.build_engine(environment=self.env)['stationMapping']
        source='\n'.join(f'{name} = {value!r}' for name,value in actual.items() if name!='ORIGIN_ROUTE_STOP_IDS')
        source+='\nROUTE_STOP_IDS = '+repr({r:{'ikebukuro':v} for r,v in actual['ORIGIN_ROUTE_STOP_IDS'].items()})+'\n'
        (self.root/'scripts/odpt_itinerary.py').write_text(source)
        self.engine=quality.build_engine(self.root,environment=self.env)
        self.context=quality.initial_context(self.engine['engineFingerprint'])
        self.a=self.helper.make_store();self.b=self.helper.make_store()
    def tearDown(self):self.helper.tearDown()
    def run_validation(self,ca=None,cb=None,ea=None,eb=None):
        with patch.object(quality,'collect_environment',return_value=copy.deepcopy(self.env)):
            return quality.validate_inputs(self.a[0],self.b[0],self.a[1],self.b[1],ca if ca is not None else self.context,cb if cb is not None else self.context,ea if ea is not None else self.engine,eb if eb is not None else self.engine,root=self.root)
    def seal(self,c):return quality.normalize_context(c,seal=True)
    def reseal_engine(self,e):
        e['engineFingerprint']=quality.digest({k:v for k,v in e.items() if k!='engineFingerprint'});return e

    def test_ready_and_no_metrics(self):
        r=self.run_validation();self.assertEqual(r['comparisonReadiness'],'ready');self.assertFalse(r['reasonCodes'])
        self.assertEqual(r['inputChecks']['baseline']['sourceCount'],7)
        self.assertEqual(r['inputChecks']['candidate']['contentFingerprint'],'PASS')
        self.assertNotIn('metrics',r);self.assertIn('quality-metrics',r['notEvaluated'])

    def test_distinct_valid_snapshot_contents_remain_ready(self):
        raw=b'[ ]';(self.b[1]/'Station_all.json').write_bytes(raw)
        path=self.b[0]/'sources/metro.station.json';record=json.loads(path.read_text())
        record['recordId']=str(uuid.uuid4());record['artifact']['sha256']=hashlib.sha256(raw).hexdigest();record['artifact']['sizeBytes']=len(raw)
        path.write_text(json.dumps(record))
        records=[json.loads(p.read_text()) for p in sorted((self.b[0]/'sources').iterdir())]
        (self.b[0]/'snapshot.json').write_text(json.dumps(source_store.create_snapshot(records,'2026-11-04T00:00:00Z')))
        r=self.run_validation();self.assertEqual(r['comparisonReadiness'],'ready')
        self.assertNotEqual(r['baselineContentFingerprint'],r['candidateContentFingerprint'])

    def test_canonical_order_and_no_run_metadata(self):
        c=copy.deepcopy(self.context)
        for field in ('serviceDates','stationIds','routeIds'):c[field].reverse()
        c['direction']['originStopIdsByRoute']['6'].reverse()
        self.assertEqual(quality.normalize_context(c),self.context)
        self.assertEqual(self.engine,quality.build_engine(self.root,environment=self.env))
        c['generatedAt']='2026-11-04T00:00:00Z'
        self.assertEqual(quality.compare_contexts(c,self.context)['status'],'invalid')

    def test_missing_vs_invalid_vs_different(self):
        c=copy.deepcopy(self.context);del c['auxiliaryServiceDates']
        self.assertEqual(quality.compare_contexts(c,self.context)['status'],'insufficient')
        self.assertEqual(self.run_validation(cb=c)['comparisonReadiness'],'incomparable')
        c=copy.deepcopy(self.context);c['maximumWaitSeconds']=600;c=self.seal(c)
        self.assertEqual(quality.compare_contexts(c,self.context)['status'],'different')
        self.assertEqual(self.run_validation(cb=c)['comparisonReadiness'],'incomparable')
        c['contextFingerprint']='0'*64
        self.assertEqual(self.run_validation(cb=c)['comparisonReadiness'],'invalid')

    def test_dates_stations_routes_wait_types(self):
        for field,value in [('serviceDates',['2026-02-30']),('serviceDates',['2026-1-01']),('stationIds',['Hikawadai']),('routeIds',[6,9]),('routeIds',['6']),('minimumWaitSeconds',False),('minimumWaitSeconds',-1),('maximumWaitSeconds',59),('maximumWaitSeconds',3601),('crossServiceDateSearch',True)]:
            c=copy.deepcopy(self.context);c[field]=value
            with self.subTest(field=field,value=value),self.assertRaises(quality.QualityInputError):self.seal(c)
        c=copy.deepcopy(self.context);c['auxiliaryServiceDates']=[c['serviceDates'][0]]
        with self.assertRaises(quality.QualityInputError):self.seal(c)

    def test_future_display_is_explicitly_not_evaluated(self):
        c=copy.deepcopy(self.context);c['observationInstants']=['2026-10-29T00:00:00Z']
        c['displayScenarios']=[{'id':'line-all','mode':'line','directOnly':False,'horizonSeconds':86400,'lineLimit':3,'departureLimit':6}]
        c=self.seal(c);r=self.run_validation(c,c)
        self.assertEqual(r['comparisonReadiness'],'ready');self.assertIn('display-model',r['notEvaluated'])
        bad=copy.deepcopy(c);bad['displayScenarios'][0]['mode']=[]
        with self.assertRaises(quality.QualityInputError):self.seal(bad)
        c['observationInstants']=['2026-10-29T09:00:00+09:00']
        with self.assertRaises(quality.QualityInputError):self.seal(c)

    def test_engine_hash_tamper_and_mismatch(self):
        e=copy.deepcopy(self.engine);e['engineFingerprint']='0'*64
        self.assertEqual(self.run_validation(eb=e)['comparisonReadiness'],'invalid')
        e=copy.deepcopy(self.engine);e['files'][0]['sha256']='0'*64;self.reseal_engine(e)
        r=self.run_validation(eb=e);self.assertEqual(r['comparisonReadiness'],'incomparable')
        self.assertIn('engine_dependencies_mismatch',r['reasonCodes'])
        c=copy.deepcopy(self.context);c['engineFingerprint']='0'*64;c=self.seal(c)
        self.assertIn('context_engine_reference_mismatch',self.run_validation(cb=c)['reasonCodes'])

    def test_runtime_environment_mismatch(self):
        e=copy.deepcopy(self.engine);e['environment']['node']['versions']['icu']='other';self.reseal_engine(e)
        r=self.run_validation(eb=e);self.assertIn('engine_environment_mismatch',r['reasonCodes'])
        self.assertEqual(r['comparisonReadiness'],'incomparable')

    def test_dependency_missing_changed_and_local_import_closure(self):
        p=self.root/'scripts/odpt_train_matcher.py';p.write_text('# changed fixture\n')
        self.assertEqual(self.run_validation()['comparisonReadiness'],'incomparable')
        p.unlink();self.assertEqual(self.run_validation()['comparisonReadiness'],'unavailable')
        p.write_text('import odpt_fixture_dependency\n')
        with self.assertRaises(quality.QualityInputError):quality.build_engine(self.root,environment=self.env)
        d=self.root/'scripts/odpt_fixture_dependency.py';d.write_text('# fixture dependency\n')
        names={f['path'] for f in quality.build_engine(self.root,environment=self.env)['files']}
        self.assertIn('scripts/odpt_fixture_dependency.py',names)

    def test_mapping_conditions_must_match_actual_code(self):
        p=self.root/'scripts/odpt_itinerary.py';p.write_text(p.read_text().replace("'228', '609'","'228', '777'"))
        e=quality.build_engine(self.root,environment=self.env);c=quality.initial_context(e['engineFingerprint'])
        self.assertIn('context_station_mapping_mismatch',self.run_validation(c,c,e,e)['reasonCodes'])

    def test_store_contract_and_source_binding(self):
        p=self.b[0]/'snapshot.json';p.write_text('{}')
        self.assertEqual(self.run_validation()['comparisonReadiness'],'invalid')
        self.b=self.helper.make_store();path=self.b[1]/'Station_all.json';path.write_bytes(b'changed')
        self.assertIn('source_bytes_mismatch',self.run_validation()['reasonCodes'])
        path.unlink();self.assertEqual(self.run_validation()['comparisonReadiness'],'unavailable')

    def test_source_change_during_validation(self):
        original=quality._read;calls={}
        def changed(path):
            raw,identity=original(path)
            if path==self.b[1]/'Station_all.json':
                calls[path]=calls.get(path,0)+1
                if calls[path]>1:identity=(*identity[:-1],identity[-1]+1)
            return raw,identity
        with patch.object(quality,'_read',side_effect=changed):
            r=self.run_validation();self.assertIn('source_changed_during_validation',r['reasonCodes'])
            self.assertNotEqual(r['comparisonReadiness'],'ready')

    def test_mutation_while_reading_is_rejected(self):
        p=self.b[1]/'Station_all.json';target=p.stat().st_ino;original=os.fstat
        def changed(fd):
            value=original(fd)
            if value.st_ino==target:
                p.write_bytes(p.read_bytes()+b' ')
                value=original(fd)
            return value
        with patch.object(os,'fstat',side_effect=changed):
            r=self.run_validation();self.assertIn('source_changed_while_reading',r['reasonCodes'])
            self.assertEqual(r['comparisonReadiness'],'invalid')

    def test_engine_change_during_validation(self):
        original=quality.build_engine;calls=0
        def changed(*args,**kwargs):
            nonlocal calls
            calls+=1;engine=original(*args,**kwargs)
            if calls==1:(self.root/'scripts/odpt_train_matcher.py').write_text('# mutated\n')
            return engine
        with patch.object(quality,'build_engine',side_effect=changed):
            r=self.run_validation();self.assertIn('engine_changed_during_validation',r['reasonCodes'])

    def test_strict_json_and_cli_readonly(self):
        with self.assertRaises(quality.QualityInputError):quality.loads('{"x":1,"x":2}')
        with self.assertRaises(quality.QualityInputError):quality.loads('{"x":NaN}')
        # CLI uses the same verification but an in-memory synthetic frozen engine.
        out=io.StringIO();original=quality.build_engine
        with patch.object(quality,'build_engine',side_effect=lambda *a,**kw:original(self.root,environment=self.env)),patch.object(quality,'collect_environment',return_value=self.env),redirect_stdout(out):
            code=quality.main(['--baseline-store',str(self.a[0]),'--candidate-store',str(self.b[0]),'--baseline-source-dir',str(self.a[1]),'--candidate-source-dir',str(self.b[1])])
        self.assertEqual(code,0);self.assertIn('metrics=not-evaluated',out.getvalue());self.assertNotIn('Synthetic',out.getvalue())
