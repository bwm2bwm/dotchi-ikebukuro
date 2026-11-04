"""Synthetic source fixtures and local Node only. Never reads saved real sources."""
import copy
from datetime import date
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

from scripts import odpt_display_metrics as metrics
from scripts import odpt_display_context as display
from scripts import odpt_quality_input as quality
from scripts import odpt_source_store as store
from tests.test_odpt_snapshot_qa import make_snapshot
from tests.test_odpt_public_v2 import FakeGenerator


class DisplayMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = quality.build_engine()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.source=make_snapshot(self.root/'source')
        self.store=self.root/'store';store.persist_snapshot(self.store,self.source)
        self.q=quality.initial_context(self.engine['engineFingerprint'])
        self.d=display.create_context(self.q,['2026-10-28T15:00:00Z'])  # Oct29 JST 00:00, previous day's 24:01.

    def collect(self,**kwargs):
        return metrics.collect_display_models(self.store,self.source,engine=kwargs.pop('engine',self.engine),
            quality_context=kwargs.pop('quality_context',self.q),display_context=kwargs.pop('display_context',self.d),**kwargs)

    def fake_collect(self,**kwargs):
        with patch.object(metrics,'ItineraryGenerator',FakeGenerator):return self.collect(**kwargs)

    def test_real_python_generator_node_integration_and_known_zero(self):
        r=self.collect()
        self.assertEqual(r['inputReadiness'],'ready')
        self.assertEqual(r['aggregateMetrics']['cellCount'],32)
        self.assertEqual(r['aggregateMetrics']['evaluatedCellCount'],32)
        self.assertEqual(r['checks']['inputImmutability']['status'],'PASS')
        self.assertEqual(r['collectionStatus'],'partial')
        self.assertEqual(metrics.exit_code(r),0)
        self.assertTrue(all(c['availability']=='known' for c in r['cells']))
        self.assertEqual(r['aggregateMetrics']['zeroCandidateCellCount'],32)
        self.assertEqual(len(r['checks']['generation']),24)

    def test_four_scenarios_day_envelope_and_no_writes_determinism(self):
        before=metrics.itinerary_metrics._inventory(self.store,self.source)
        tree=list(self.root.rglob('*'))
        a=self.fake_collect();b=self.fake_collect()
        self.assertEqual(a,b);self.assertEqual(a['collectionDigest'],b['collectionDigest'])
        self.assertEqual(a['aggregateMetrics']['itemsCount'],64)
        self.assertEqual(a['aggregateMetrics']['groupsCardCount'],64)
        self.assertEqual(a['aggregateMetrics']['bestInGroupsCount'],32)
        self.assertEqual(a['aggregateMetrics']['serviceDateCandidateCounts'],{'2026-10-28':64})
        self.assertEqual(a['aggregateMetrics']['validationErrorCounts'],{})
        self.assertEqual(a['aggregateMetrics']['availabilityCounts'],{'known':32})
        self.assertEqual(before,metrics.itinerary_metrics._inventory(self.store,self.source))
        self.assertEqual(tree,list(self.root.rglob('*')))
        self.assertNotIn('raw-secret-trip',json.dumps(a))
        self.assertTrue(all('2000-01-01T00:00:00Z' not in json.dumps(c) for c in a['cells']))

    def test_unknown_state_propagation_uses_existing_exclusion_rules(self):
        class UnknownGenerator(FakeGenerator):
            def generate(self,day):
                rows=super().generate(day)
                rows.append(NS(route_id='6',headsign='secret',departure_seconds=90000,
                    primary_itinerary=None,direct_alternative=None,best_transfer_alternative=None,
                    type_resolution=NS(label='不明'),odpt=NS(status='unique_match'),data_quality=[],
                    status='no_valid_arrival',transfer_wait_policy_excluded=False))
                self.last_destination_status['routes']['6']['originTripCount']+=1
                return rows
        with patch.object(metrics,'ItineraryGenerator',UnknownGenerator):r=self.collect()
        self.assertGreater(r['aggregateMetrics']['unknownSuppressedRouteCount'],0)
        for c in r['cells']:
            self.assertTrue(all(not v for v in c['metrics']['terminalKnown'].values()))
        self.assertTrue(all(e['reasonCounts']['no_valid_arrival']==1 for e in r['checks']['generation']))
        d=display.create_context(self.q,['2026-10-28T15:02:00Z'])
        with patch.object(metrics,'ItineraryGenerator',UnknownGenerator):late=self.collect(display_context=d)
        for c in late['cells']:
            self.assertEqual(c['metrics']['routeStates']['2026-10-28|6']['state'],'terminal_unconfirmed')
            self.assertEqual(c['metrics']['routeStates']['2026-10-29|6']['state'],'start_unconfirmed')

    def test_unavailable_and_out_of_range_are_not_empty_candidates(self):
        original=metrics.v2._build_station_payload
        def broken(g,s,days,t):
            if s=='Hikawadai' and days==['2026-10-28']:raise metrics.v2.V2Error('requested_service_date_outside_feed')
            return original(g,s,days,t)
        with patch.object(metrics.v2,'_build_station_payload',side_effect=broken):r=self.fake_collect()
        bad=[c for c in r['cells'] if c['dimensions']['stationId']=='Hikawadai']
        self.assertEqual(len(bad),4);self.assertTrue(all(c['availability']=='out-of-range' and c['metrics'] is None for c in bad))
        self.assertEqual(r['aggregateMetrics']['evaluatedCellCount'],28);self.assertEqual(metrics.exit_code(r),2)
        q=copy.deepcopy(self.q);q['serviceDates']=['2026-10-29'];q=quality.normalize_context(q,seal=True)
        with patch.object(metrics,'ItineraryGenerator',side_effect=AssertionError('must not generate')):
            r=self.collect(quality_context=q)
        self.assertEqual(r['collectionStatus'],'failed');self.assertFalse(r['cells'])

    def test_node_failures_timeout_bad_json_and_mutated_response(self):
        for code in ('node_timeout','node_subprocess_failed','node_response_json_invalid'):
            with self.subTest(code=code),patch.object(metrics,'_run_node',side_effect=metrics.DisplayCollectionError(code)):
                r=self.fake_collect()
                self.assertEqual(r['aggregateMetrics']['evaluatedCellCount'],0)
                self.assertTrue(all(c['metrics'] is None for c in r['cells']))
                self.assertEqual(metrics.exit_code(r),2)
        original=metrics._run_node
        def corrupt(*a,**kw):
            response,transport=original(*a,**kw);response['candidateCount']+=1;return response,transport
        with patch.object(metrics,'_run_node',side_effect=corrupt):r=self.fake_collect()
        self.assertIn('node_board_summary_inconsistent',r['aggregateMetrics']['validationErrorCounts'])

    def test_bounded_subprocess_transport(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'scripts').mkdir();p=root/'scripts/odpt_display_runner.mjs'
            for code,expected in [('setInterval(()=>{},1000);','node_timeout'),
                                  ('process.stdout.write("not-json");','node_response_json_invalid'),
                                  ('process.stderr.write("secret");process.stdout.write("{}");','node_unexpected_stderr'),
                                  ('process.exit(1);','node_response_json_invalid'),
                                  ('process.stdout.write("x".repeat(10000));','node_response_size_limit')]:
                p.write_text(code)
                with self.subTest(expected=expected),patch.object(metrics,'RESPONSE_LIMIT',1000),self.assertRaisesRegex(metrics.DisplayCollectionError,expected):
                    metrics._run_node({},root=root,timeout=.3)

    def test_payload_state_binding_strict_audit_and_public_gate_independence(self):
        def no_public(*a,**kw):raise AssertionError('public gate called')
        with patch.object(metrics.v2,'run_pipeline',no_public),patch('prepare_odpt_v2_qa.prepare',no_public),patch.object(metrics.v2,'validate_bundle',no_public):
            self.assertEqual(metrics.exit_code(self.fake_collect()),0)
        original=metrics._qa_state
        def wrong(*a,**kw):
            state=original(*a,**kw);del state['stations'][a[1][0]][a[2][0]]['otherUnknownCount'];return state
        with patch.object(metrics,'_qa_state',side_effect=wrong):r=self.fake_collect()
        self.assertEqual(r['aggregateMetrics']['availabilityCounts'],{'unavailable':32})
        self.assertIn('qa_exclusion_binding_inconsistent',r['aggregateMetrics']['validationErrorCounts'])
        with self.assertRaisesRegex(metrics.DisplayCollectionError,'qa_payload_integrity_mismatch'):
            metrics._verify_binding({'stationId':'Hikawadai'},{'candidateFiles':{'Hikawadai':{'bytes':1,'sha256':'0'*64}}})

    def test_detail_cap_preserves_totals_and_prioritizes_unavailable(self):
        original=metrics.v2._build_station_payload
        def broken(g,s,*a):
            if s=='Wakoshi':raise metrics.v2.V2Error('requested_service_date_outside_feed')
            return original(g,s,*a)
        with patch.object(metrics.v2,'_build_station_payload',side_effect=broken):r=self.fake_collect(detail_limit=2)
        self.assertEqual(r['aggregateMetrics']['cellCount'],32)
        self.assertEqual(r['aggregateMetrics']['evaluatedCellCount'],28)
        self.assertEqual(len(r['cells']),2)
        self.assertTrue(all(c['availability']=='out-of-range' for c in r['cells']))
        self.assertEqual(r['omittedDetails']['cells'],30)
        self.assertEqual(r['collectionStatus'],'partial');self.assertEqual(metrics.exit_code(r),2)

    def test_context_engine_input_binding_and_mid_collection_mutation(self):
        bad=copy.deepcopy(self.engine);bad['environment']['node']['versions']['icu']='other'
        bad['engineFingerprint']=quality.digest({k:v for k,v in bad.items() if k!='engineFingerprint'})
        r=self.collect(engine=bad)
        self.assertEqual(r['collectionStatus'],'failed');self.assertFalse(r['cells'])
        original=FakeGenerator.generate;changed=False
        def mutation(g,d):
            nonlocal changed
            if not changed:
                p=self.source/'Station_all.json';p.write_bytes(p.read_bytes()+b' ');changed=True
            return original(g,d)
        with patch.object(FakeGenerator,'generate',mutation):r=self.fake_collect()
        self.assertEqual(r['collectionStatus'],'failed');self.assertIsNone(r['aggregateMetrics']);self.assertFalse(r['cells'])
        self.assertEqual(r['checks']['inputImmutability']['status'],'FAIL')

    def test_cli_summary_codes_and_no_body(self):
        r=self.fake_collect()
        with patch.object(metrics,'collect_display_models',return_value=r),redirect_stdout(io.StringIO()) as out:
            code=metrics.main(['--store',str(self.store),'--source-dir',str(self.source)])
        self.assertEqual(code,0);self.assertIn('collection_status=partial',out.getvalue())
        self.assertNotIn('行先',out.getvalue());self.assertNotIn('p2-',out.getvalue())
        for readiness,expected in [('invalid',3),('unavailable',4),('incomparable',2)]:
            x=copy.deepcopy(r);x.update(inputReadiness=readiness,collectionStatus='failed');self.assertEqual(metrics.exit_code(x),expected)

    def test_direct_alternative_best_outside_groups_and_card_limit(self):
        class RichGenerator(FakeGenerator):
            def generate(self,day):
                rows=[];routes={}
                for route in ('6','9'):
                    for n in range(8):
                        dep=86460+n*60
                        direct=NS(kind='direct',departure_seconds=dep,arrival_seconds=dep+3000,second_leg=None,transfer_wait_seconds=None)
                        transfer=NS(kind='transfer',departure_seconds=dep,arrival_seconds=dep+(60 if n==7 else 2500),second_leg=NS(trip=NS(route_id='9' if route=='6' else '6')),transfer_wait_seconds=60)
                        rows.append(NS(route_id=route,headsign='synthetic',departure_seconds=dep,primary_itinerary=transfer,
                            direct_alternative=direct,best_transfer_alternative=transfer,type_resolution=NS(label='合成'),
                            odpt=NS(status='unique_match'),data_quality=[],origin_trip_id='never-expose'))
                    routes[route]={'scheduledTripCount':8,'originTripCount':8,'dataInsufficientCount':0,'transferDataInsufficientCount':0}
                self.last_destination_status={'routes':routes};return rows
        with patch.object(metrics,'ItineraryGenerator',RichGenerator):r=self.collect()
        for c in r['cells']:
            self.assertEqual(c['metrics']['itemsCount'],16)
            self.assertEqual(c['metrics']['groupsCardCount'],6)
            if c['dimensions']['scenarioId'].endswith('-all'):
                self.assertFalse(c['metrics']['bestInGroups']);self.assertEqual(c['metrics']['transferCount'],16)
            else:
                self.assertTrue(c['metrics']['bestInGroups']);self.assertEqual(c['metrics']['directCount'],16)

    def test_unknown_start_terminal_and_fixed_clock_boundaries(self):
        # Existing Node runner tests exercise every route state and second boundary;
        # collector must preserve them without resetting to the actual wall clock.
        for instant,state in [('2026-10-29T13:00:00Z','not_started'),('2026-10-29T14:01:00Z','running')]:
            d=display.create_context(self.q,[instant])
            r=self.fake_collect(display_context=d)
            for c in r['cells']:
                self.assertEqual(c['metrics']['routeStates']['2026-10-29|6']['state'],state)

    def test_engine_change_after_node_invalidates_all_collected_values(self):
        changed=False
        original_engine=quality.build_engine;original_node=metrics._run_node
        def engine_now(*a,**kw):
            e=original_engine(*a,**kw)
            if changed:
                e['files'][-1]['sha256']='1'*64
                e['engineFingerprint']=quality.digest({k:v for k,v in e.items() if k!='engineFingerprint'})
            return e
        def run(*a,**kw):
            nonlocal changed
            result=original_node(*a,**kw);changed=True;return result
        with patch.object(quality,'build_engine',side_effect=engine_now),patch.object(metrics,'_run_node',side_effect=run):
            r=self.fake_collect()
        self.assertEqual(r['collectionStatus'],'failed');self.assertEqual(r['inputReadiness'],'incomparable')
        self.assertFalse(r['cells']);self.assertIsNone(r['aggregateMetrics'])
        self.assertIn('engine_dependencies_mismatch',r['reasonCodes'])

    def test_structurally_invalid_payload_never_reaches_node(self):
        original=metrics.v2._build_station_payload
        def broken(*a,**kw):
            payload,measured=original(*a,**kw);payload['serviceDays'][0]['routeCoverage']['6']['dataState']='invented';return payload,measured
        with patch.object(metrics.v2,'_build_station_payload',side_effect=broken),patch.object(metrics,'_run_node',side_effect=AssertionError('invalid payload reached Node')):
            r=self.fake_collect()
        self.assertEqual(r['aggregateMetrics']['evaluatedCellCount'],0)
        self.assertEqual(r['collectionStatus'],'failed')
        self.assertTrue(all(c['availability']=='unavailable' and c['metrics'] is None for c in r['cells']))

    def test_malformed_engine_returns_failed_report(self):
        for engine in ('invalid',{'files':None}):
            with self.subTest(engine=engine):
                r=self.collect(engine=engine)
                self.assertEqual(r['collectionStatus'],'failed');self.assertEqual(metrics.exit_code(r),3)
                self.assertIsNone(r['aggregateMetrics']);self.assertFalse(r['cells'])

    def test_real_synthetic_feed_auxiliary_out_of_range(self):
        q=copy.deepcopy(self.q);q['auxiliaryServiceDates']=['2026-10-27'];q=quality.normalize_context(q,seal=True)
        d=display.create_context(q,['2026-10-28T03:00:00Z'])
        r=self.collect(quality_context=q,display_context=d)
        self.assertEqual(r['aggregateMetrics']['outOfRangeCellCount'],32)
        self.assertEqual(r['aggregateMetrics']['evaluatedCellCount'],0)
        self.assertIsNone(r['aggregateMetrics']['itemsCount'])
        self.assertEqual(r['checks']['generationSummary']['availabilityCounts'],{'known':16,'out-of-range':8})
        self.assertEqual(r['checks']['inputImmutability']['status'],'PASS')
