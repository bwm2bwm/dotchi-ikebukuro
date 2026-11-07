"""Private DOM collector tests use synthetic source/store fixtures only."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from scripts import odpt_dom_metrics as dom
from scripts import odpt_source_store as store
from tests.test_odpt_snapshot_qa import make_snapshot
from tests.test_odpt_public_v2 import FakeGenerator


class DomMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = dom.quality.build_engine()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = make_snapshot(self.root/'source')
        self.store = self.root/'store'; store.persist_snapshot(self.store,self.source)
        self.q = dom.quality.initial_context(self.engine['engineFingerprint'])
        self.d = dom.display.create_context(self.q,['2026-10-28T15:00:00Z'])

    def collect(self, fake=True, **kwargs):
        with patch.object(dom.model,'ItineraryGenerator',FakeGenerator if fake else dom.model.ItineraryGenerator):
            return dom.collect_dom_qa(self.store,self.source,quality_context=self.q,display_context=self.d,
                engine=kwargs.pop('engine',self.engine),**kwargs)

    def test_full_chain_all_station_audit_bytes_and_no_persistence_repeat_digest(self):
        before=dom.model.itinerary_metrics._inventory(self.store,self.source)
        tree=sorted(self.root.rglob('*'))
        a=self.collect(); b=self.collect()
        self.assertEqual(a['domQaStatus'],'complete'); self.assertEqual(dom.exit_code(a),0)
        self.assertEqual(a['resultDigest'],b['resultDigest'])
        self.assertEqual(a['checks']['generationCount'],24)
        self.assertEqual(a['checks']['allStationQaState']['stationCount'],8)
        self.assertEqual(a['checks']['nodeStarts'],8)
        self.assertEqual(a['summary']['domCardCount'],16)
        self.assertEqual(a['summary']['evaluatedCellCount'],8)
        self.assertTrue(all(c['availability']=='known' for c in a['cells']))
        self.assertNotIn('raw-secret-trip',json.dumps(a))
        self.assertEqual(before,dom.model.itinerary_metrics._inventory(self.store,self.source))
        self.assertEqual(tree,sorted(self.root.rglob('*')))
        totals=a['checks']['generationTotals']
        self.assertEqual(totals['generatedCount'],totals['candidateCount']+totals['excludedCount'])
        self.assertEqual(totals['candidateCount'],totals['primaryDirectCount']+totals['primaryTransferCount'])

    def test_explicit_all_station_scope_is_32_cells_and_keeps_one_24_day_generation_pass(self):
        r=self.collect(station_ids=list(dom.quality.STATIONS))
        self.assertEqual(r['domQaStatus'],'complete');self.assertEqual(dom.exit_code(r),0)
        self.assertEqual(r['evaluationScope']['stationIds'],list(dom.quality.STATIONS))
        self.assertEqual(r['evaluationScope']['scenarioIds'],['departure-all','departure-direct','line-all','line-direct'])
        self.assertEqual(r['checks']['generationCount'],24)
        self.assertEqual(r['checks']['nodeStarts'],32)
        self.assertEqual(r['summary']['evaluatedCellCount'],32)
        self.assertEqual(r['summary']['checkCounts'],{'PASS':352})
        self.assertNotIn('all-station-dom-evaluation',r['notEvaluated'])

    def test_station_selection_rejects_duplicates_unknown_empty_and_wrong_container(self):
        for value in ([],('Senkawa','Senkawa'),['NoSuchStation'],{'Senkawa'}):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'station_ids_invalid'):
                self.collect(station_ids=value)

    def test_actual_synthetic_generator_zero_is_known_not_unavailable(self):
        r=self.collect(fake=False)
        self.assertEqual(dom.exit_code(r),0)
        self.assertEqual(r['summary']['domCardCount'],0)
        self.assertTrue(all(c['availability']=='known' for c in r['cells']))

    def test_one_station_failure_prevents_all_normal_dom_evaluation(self):
        original=dom.model._generate_day
        def missing(g,s,d):
            if s=='Wakoshi': return dict(availability='unavailable',reasonCode='missing_station'),dict(stationId=s,serviceDate=d,availability='unavailable',reasonCode='missing_station')
            return original(g,s,d)
        with patch.object(dom.model,'_generate_day',side_effect=missing): r=self.collect()
        self.assertEqual(r['checks']['nodeStarts'],0)
        self.assertEqual(r['checks']['allStationQaState']['status'],'FAIL')
        self.assertEqual(r['summary']['evaluatedCellCount'],0)
        self.assertNotEqual(dom.exit_code(r),0)
        self.assertTrue(all(c['metrics'] is None for c in r['cells']))

    def test_missing_day_and_wrong_integrity_are_not_filled(self):
        with self.assertRaisesRegex(dom.model.DisplayCollectionError,'all_station_evidence_missing'):
            dom._all_station_inputs({},['2026-10-28'])
        original=dom.model._envelope
        def wrong(*args):
            p,s=original(*args);s['candidateFiles'][p['stationId']]['bytes']+=1;return p,s
        with patch.object(dom.model,'_envelope',side_effect=wrong):r=self.collect()
        self.assertEqual(r['checks']['nodeStarts'],0)
        self.assertNotEqual(dom.exit_code(r),0)

    def test_transport_failures_no_zero_substitution(self):
        for code in ('node_timeout','node_subprocess_failed','node_response_json_invalid'):
            with self.subTest(code=code),patch.object(dom.model,'_run_node',side_effect=dom.model.DisplayCollectionError(code)):
                r=self.collect()
                self.assertEqual(r['summary']['evaluatedCellCount'],0)
                self.assertNotEqual(dom.exit_code(r),0)
                self.assertTrue(all(c['metrics'] is None for c in r['cells']))

    def test_corrupt_dom_response_is_confirmed_inconsistency(self):
        original=dom.model._run_node
        def corrupt(*args,**kwargs):
            r,t=original(*args,**kwargs);r['observation']['groups']=[]
            r['observationDigest']=dom.quality.digest(r['observation']);return r,t
        with patch.object(dom.model,'_run_node',side_effect=corrupt):r=self.collect()
        self.assertEqual(dom.exit_code(r),3)
        self.assertEqual(r['domQaStatus'],'failed')
        self.assertTrue(any(f['code']=='dom_card_inconsistent' for f in r['findings']))

    def test_partial_cells_and_detail_cap_keep_full_totals(self):
        original=dom.model._run_node;calls=0
        def one_failure(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==1: raise dom.model.DisplayCollectionError('node_timeout')
            return original(*args,**kwargs)
        with patch.object(dom.model,'_run_node',side_effect=one_failure):r=self.collect(detail_limit=2)
        self.assertEqual(r['domQaStatus'],'partial');self.assertEqual(dom.exit_code(r),2)
        self.assertEqual(r['summary']['evaluatedCellCount'],7)
        self.assertEqual(r['omittedDetails']['cells'],6)
        self.assertEqual(r['cells'][0]['availability'],'unavailable')

    def test_input_or_engine_changed_invalidates_success(self):
        original=dom.model._run_node;changed=False
        def mutate(*args,**kwargs):
            nonlocal changed
            r=original(*args,**kwargs)
            if not changed:
                changed=True
                p=self.store/'snapshot.json';p.write_bytes(p.read_bytes()+b'\n')
            return r
        with patch.object(dom.model,'_run_node',side_effect=mutate):r=self.collect()
        self.assertEqual(dom.exit_code(r),3);self.assertIsNone(r['summary']);self.assertFalse(r['cells'])
        bad=copy.deepcopy(self.engine);bad['environment']['changed']=True
        bad['engineFingerprint']=dom.quality.digest({k:v for k,v in bad.items() if k!='engineFingerprint'})
        r=self.collect(engine=bad)
        self.assertEqual(r['domQaStatus'],'incomparable');self.assertEqual(dom.exit_code(r),2)

    def test_cli_summary_has_no_candidate_or_journey_body(self):
        r=self.collect()
        out=io.StringIO()
        with patch.object(dom,'collect_dom_qa',return_value=r),redirect_stdout(out):
            self.assertEqual(dom.main(['--store',str(self.store),'--source-dir',str(self.source)]),0)
        self.assertNotIn('p2-',out.getvalue());self.assertNotIn('departureServiceSeconds',out.getvalue())
        self.assertIn('domQaStatus="complete"',out.getvalue())

    def test_cli_all_stations_is_explicit_and_default_remains_smoke(self):
        r=self.collect()
        captured=[]
        def fake_collect(*args,**kwargs): captured.append((kwargs.get('station_ids'),kwargs.get('observation_instant')));return r
        out=io.StringIO()
        with patch.object(dom,'collect_dom_qa',side_effect=fake_collect),redirect_stdout(out):
            self.assertEqual(dom.main(['--store',str(self.store),'--source-dir',str(self.source),'--all-stations',
                '--observation-instant','2026-11-09T11:00:00Z']),0)
        self.assertEqual(captured,[(dom.quality.STATIONS,'2026-11-09T11:00:00Z')])
        captured.clear()
        with patch.object(dom,'collect_dom_qa',side_effect=fake_collect),redirect_stdout(io.StringIO()):
            self.assertEqual(dom.main(['--store',str(self.store),'--source-dir',str(self.source)]),0)
        self.assertEqual(captured,[(None,dom.INSTANT)])

    def test_explicit_observation_instant_seals_matching_default_quality_dates(self):
        instant='2026-11-09T11:00:00Z'
        with patch.object(dom.model,'ItineraryGenerator',FakeGenerator):
            r=dom.collect_dom_qa(self.store,self.source,engine=self.engine,
                station_ids=list(dom.quality.STATIONS),observation_instant=instant)
        self.assertEqual(r['domQaStatus'],'complete')
        self.assertEqual(r['evaluationScope']['requiredServiceDates'],['2026-11-08','2026-11-09','2026-11-10'])
        self.assertEqual(r['checks']['generationCount'],24)
        self.assertEqual(r['summary']['checkCounts'],{'PASS':352})

    def test_new_engine_closure_and_measurements_excluded_from_digest(self):
        paths={f['path'] for f in self.engine['files']}
        self.assertTrue({'scripts/odpt_dom_metrics.py','scripts/odpt_dom_runner.mjs','scripts/odpt_dom_harness.mjs'}<=paths)
        r=self.collect();v=copy.deepcopy(r);v['timings']={'any':7};v['resources']={'any':8}
        self.assertEqual(dom.result_digest(r),dom.result_digest(v))

    def test_runtime_mismatch_is_incomparable_not_dom_inconsistency(self):
        with patch.object(dom.model,'_run_node',side_effect=dom.model.DisplayCollectionError('node_runner_node_runtime_mismatch')):
            r=self.collect()
        self.assertEqual(r['domQaStatus'],'incomparable')
        self.assertEqual(dom.exit_code(r),2)
        self.assertIsNone(r['summary'])

    def test_failure_exit_code_survives_zero_detail_limit(self):
        with patch.object(dom.model,'_run_node',side_effect=dom.model.DisplayCollectionError('dom_card_inconsistent','invalid')):
            r=self.collect(detail_limit=0)
        self.assertEqual(r['domQaStatus'],'failed')
        self.assertEqual(dom.exit_code(r),3)
        self.assertFalse(r['cells'])

    def test_engine_change_after_node_invalidates_all_cells(self):
        original_build=dom.quality.build_engine;original_node=dom.model._run_node;changed=False
        def build(*args,**kwargs):
            engine=original_build(*args,**kwargs)
            if changed:
                engine['environment']['synthetic_change']=True
                engine['engineFingerprint']=dom.quality.digest({k:v for k,v in engine.items() if k!='engineFingerprint'})
            return engine
        def run(*args,**kwargs):
            nonlocal changed
            result=original_node(*args,**kwargs);changed=True;return result
        with patch.object(dom.model,'_run_node',side_effect=run),patch.object(dom.quality,'build_engine',side_effect=build):
            r=self.collect()
        self.assertEqual(dom.exit_code(r),2)
        self.assertEqual(r['domQaStatus'],'incomparable')
        self.assertFalse(r['cells'])
        self.assertIsNone(r['checks']['generationTotals'])

    def test_warning_audit_stays_warning_and_propagates_via_coverage(self):
        class WarningGenerator(FakeGenerator):
            def generate(self,day):
                rows=super().generate(day)
                bad=copy.deepcopy(rows[1]);bad.primary_itinerary=None;bad.direct_alternative=None
                bad.data_quality=['kotake_alighting_prohibited']
                rows.append(bad)
                self.last_destination_status['routes']['9']['originTripCount']+=1
                return rows
        with patch.object(dom.model,'ItineraryGenerator',WarningGenerator):
            r=dom.collect_dom_qa(self.store,self.source,quality_context=self.q,display_context=self.d,engine=self.engine)
        self.assertEqual(dom.exit_code(r),0)
        self.assertEqual(sum(g['classificationCounts']['WARNING'] for g in r['checks']['generation']),24)
        for cell in r['cells']:
            self.assertEqual(cell['metrics']['routeStates']['2026-10-28|9'],'data_insufficient')
            self.assertEqual(cell['observation']['statusState'],'warning')
            self.assertFalse(any('UNKNOWN' in c['text'] for c in cell['observation']['coverage']))

    def test_dom_transport_limits_bad_json_timeout_and_launch_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'scripts').mkdir();script=root/'scripts/odpt_dom_runner.mjs'
            for text,reason in [('setInterval(()=>{},1000)','node_timeout'),('process.stdout.write("oops")','node_response_json_invalid'),
                                ('process.stdout.write("x".repeat(10000))','node_response_size_limit')]:
                script.write_text(text)
                with patch.object(dom.model,'RESPONSE_LIMIT',1000),self.assertRaisesRegex(dom.model.DisplayCollectionError,reason):
                    dom.model._run_node({},root=root,runner='odpt_dom_runner.mjs',response_contract='odpt-dom-response',timeout=.3)
        with patch.object(dom.model.subprocess,'Popen',side_effect=OSError()),self.assertRaisesRegex(dom.model.DisplayCollectionError,'node_subprocess_failed'):
            dom.model._run_node({},runner='odpt_dom_runner.mjs',response_contract='odpt-dom-response')
