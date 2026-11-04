"""Synthetic fixtures only. No network, private saved sources or report artifacts."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import odpt_quality_diff as diff
from tests import test_odpt_quality_metrics as fixture

collector, quality = diff.collector, diff.quality


def cell(g=5, c=4, direct=3, alt=4, best=2, pairs=6, reason='no_valid_arrival'):
    dims = {'snapshotId': 'synthetic', 'serviceDate': '2026-10-28', 'stationId': 'Hikawadai', 'routeId': '6'}
    values = {'G': g, 'C': c, 'E': g-c, 'primaryDirectCount': direct, 'primaryTransferCount': c-direct,
              'alternativeDirectRowCount': alt, 'bestTransferRowCount': best, 'validTransferPairCount': pairs,
              'exclusionReasonCounts': {r: g-c if r == reason else 0 for r in collector.v2.EXCLUSION_REASONS}}
    return {'metrics': [collector._metric(name, dims, values[name]) for name in sorted(values)]}


CONTEXT = {'serviceDates': ['2026-10-28'], 'stationIds': ['Hikawadai'], 'routeIds': ['6']}


class BasicDiffTests(unittest.TestCase):
    def compare(self, a=None, b=None, **kwargs):
        return diff.compare_basic(a or cell(), b or cell(), CONTEXT, **kwargs)

    def test_same_counts_are_known_zero_and_no_findings(self):
        r = self.compare()
        self.assertEqual(len(r['metricDiffs']), 14)
        self.assertTrue(all(m['delta'] == 0 and m['comparisonAvailability'] == 'known' for m in r['metricDiffs']))
        self.assertEqual(r['summary']['unchangedCellCount'], 1)
        self.assertEqual(r['summary']['consistency'], {'baseline': {'PASS': 3}, 'candidate': {'PASS': 3}})
        self.assertFalse(r['findings'])

    def test_gce_primary_alternative_pairs_and_exclusion_changes(self):
        for candidate, changes in (
            (cell(g=8, c=5, direct=2, alt=2, best=3, pairs=10),
             {'G': 3, 'C': 1, 'E': 2, 'primaryDirectCount': -1, 'primaryTransferCount': 2,
              'alternativeDirectRowCount': -2, 'bestTransferRowCount': 1, 'validTransferPairCount': 4,
              'exclusionReasonCounts.no_valid_arrival': 2}),
            (cell(g=2, c=2, direct=2), {'G': -3, 'C': -2, 'E': -1, 'primaryTransferCount': -1,
                                     'exclusionReasonCounts.no_valid_arrival': -1}),
        ):
            with self.subTest(changes=changes):
                r = self.compare(b=candidate)
                by_id = {m['metricId']: m for m in r['metricDiffs']}
                for name, delta in changes.items(): self.assertEqual(by_id[name]['delta'], delta)
                self.assertEqual(r['summary']['changedCellCount'], 1)
                self.assertEqual(len(r['findings']), r['summary']['changedMetricCount'])
                self.assertIn('direct-decreased', by_id['primaryDirectCount']['classifications'])
                self.assertIn('exclusion-increased' if changes['E'] > 0 else 'exclusion-decreased', by_id['E']['classifications'])
                if changes['primaryTransferCount'] < 0:
                    self.assertIn('transfer-decreased', by_id['primaryTransferCount']['classifications'])

    def test_disappearance_requires_paired_positive_C_to_known_zero(self):
        r = self.compare(b=cell(g=0, c=0, direct=0, alt=0, best=0, pairs=0))
        c = next(m for m in r['metricDiffs'] if m['metricId'] == 'C')
        self.assertIn('candidate-disappeared', c['classifications'])
        for a, b in ((cell(g=0,c=0,direct=0),cell(g=0,c=0,direct=0)), (cell(), {'metrics': []})):
            r = self.compare(a,b)
            self.assertFalse(any('candidate-disappeared' in m['classifications'] for m in r['metricDiffs']))

    def test_missing_cells_are_not_imputed_in_either_direction(self):
        for a,b in ((cell(), {'metrics': []}), ({'metrics': []},cell())):
            r = self.compare(a,b)
            self.assertEqual(r['summary']['comparedMetricCount'], 0)
            self.assertEqual(r['summary']['indeterminateCellCount'], 1)
            self.assertTrue(all(m['delta'] is None for m in r['metricDiffs']))
            self.assertIsNone(r['summary']['metricDiffTotals']['C']['delta'])
            self.assertTrue(all('missing_or_duplicate' in ' '.join(m['reasonCodes']) for m in r['metricDiffs']))

    def test_unavailable_is_not_zero_other_confirmed_changes_survive(self):
        b = cell(g=7)
        m = next(m for m in b['metrics'] if m['metricId'] == 'validTransferPairCount')
        m.update(availability='unavailable', value=None, reasonCodes=['field_missing'])
        r = self.compare(b=b)
        by_id = {m['metricId']: m for m in r['metricDiffs']}
        self.assertEqual(by_id['G']['delta'], 2)
        self.assertIsNone(by_id['validTransferPairCount']['candidateValue'])
        self.assertIsNone(by_id['validTransferPairCount']['delta'])
        self.assertEqual(by_id['exclusionReasonCounts.unknown']['delta'], 0)
        self.assertEqual(r['summary']['partialCellCount'], 1)

    def test_unit_denominator_duplicate_and_reason_set_mismatch(self):
        for kind in ('unit', 'denominator', 'numerator', 'duplicate', 'reason-key'):
            b = cell()
            name = 'exclusionReasonCounts' if kind == 'reason-key' else 'C'
            m = next(m for m in b['metrics'] if m['metricId'] == name)
            if kind == 'duplicate': b['metrics'].append(copy.deepcopy(m))
            elif kind == 'reason-key': del m['value']['unknown']
            else: m[kind] = 'different' if kind == 'unit' else 99
            with self.subTest(kind=kind):
                r = self.compare(b=b)
                self.assertTrue(all(m['delta'] is None for m in r['metricDiffs'] if m['metricId'].startswith(name)))
                self.assertGreater(r['summary']['notEvaluableMetricCount'], 0)

    def test_both_side_consistency_failures_remain_when_deltas_zero(self):
        a = cell()
        next(m for m in a['metrics'] if m['metricId'] == 'G')['value'] = 99
        next(m for m in a['metrics'] if m['metricId'] == 'primaryDirectCount')['value'] = 99
        r = self.compare(a,copy.deepcopy(a))
        self.assertTrue(all(m['delta'] == 0 for m in r['metricDiffs']))
        failures = [f for f in r['findings'] if f['code'] == 'side_consistency_failed']
        self.assertEqual(len(failures), 4)
        self.assertEqual({f['side'] for f in failures}, {'baseline','candidate'})
        self.assertEqual(r['summary']['partialCellCount'], 1)
        self.assertEqual(a['metrics'][next(i for i,m in enumerate(a['metrics']) if m['metricId'] == 'G')]['value'], 99)

    def test_limits_preserve_all_counts_and_deterministic_sort(self):
        a, b = cell(), cell(g=8,c=5,direct=2)
        full = self.compare(a,b)
        for limit in (0,1,3):
            r = self.compare(a,b,detail_limit=limit)
            self.assertEqual(r['summary'], full['summary'])
            for field in ('metricDiffs','findings','consistency'): self.assertLessEqual(len(r[field]),limit)
            self.assertTrue(r['omittedDetails'])
        a['metrics'].reverse(); b['metrics'].reverse()
        self.assertEqual(full, self.compare(a,b))
        keys = [diff._key(m) for m in full['metricDiffs']]
        self.assertEqual(keys, sorted(keys))
        for limit in (-1,10001,False):
            with self.assertRaises(quality.QualityInputError): self.compare(detail_limit=limit)


class QualityDiffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.QualityMetricsTests(); self.fixture.setUp()
        self.engine, self.context = self.fixture.engine, self.fixture.context
        self.store, self.source = self.fixture.store, self.fixture.source

    def tearDown(self): self.fixture.tearDown()

    def compare(self, **kwargs):
        with patch.object(quality, 'collect_environment', return_value=self.fixture.fixture.env):
            return diff.compare_quality(self.store,self.store,self.source,self.source,
                engine=self.engine,context=self.context,root=self.fixture.root, **kwargs)

    def test_self_comparison_contract_order_binding_and_no_writes(self):
        before = collector._inventory(self.store,self.source)
        tree = sorted(self.fixture.fixture.helper.root.rglob('*'))
        r = self.compare()
        self.assertEqual(r['contract'],'dotchi.odpt.itinerary-quality-diff')
        self.assertEqual(r['qualityProfile'],quality.PROFILE)
        self.assertEqual(r['summary']['cellCount'],48)
        self.assertEqual(r['summary']['unchangedCellCount'],48)
        self.assertEqual(r['summary']['changedMetricCount'],0)
        self.assertEqual(r['summary']['comparedMetricCount'],672)
        self.assertEqual(r['comparisonStatus'],'partial')
        self.assertEqual(r['qualityDiffStatus'],'indeterminate')
        self.assertEqual(r['basicQualityDiffStatus'],'unchanged')
        self.assertEqual(diff.exit_code(r),0)
        self.assertEqual(len(r['baselineMetrics']),432)
        self.assertEqual(len(r['candidateMetrics']),432)
        self.assertFalse(r['omittedDetails'])
        self.assertNotIn('detailed-metrics-diff',r['notEvaluated'])
        self.assertFalse(r['findings'])
        self.assertEqual(before,collector._inventory(self.store,self.source))
        self.assertEqual(tree,sorted(self.fixture.fixture.helper.root.rglob('*')))
        self.assertNotIn('trip-6-',json.dumps(r))
        self.assertEqual(r,self.compare())

    def test_sequential_collector_calls_same_context_engine_no_public_gate(self):
        original = collector.collect_metrics
        calls = []
        running = False
        def collect(*args,**kw):
            nonlocal running
            self.assertFalse(running);running=True
            calls.append((args,copy.deepcopy(kw)))
            r = original(*args,**kw)
            running=False
            return r
        with patch.object(collector,'collect_metrics',side_effect=collect), \
             patch.object(collector.v2,'validate_bundle',side_effect=AssertionError('gate called')):
            r = self.compare()
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0],calls[1])
        self.assertEqual(diff.exit_code(r),0)

    def test_context_engine_runtime_mismatch_prevents_collection(self):
        c = copy.deepcopy(self.context);c['maximumWaitSeconds']=600;c=quality.normalize_context(c,seal=True)
        engine = copy.deepcopy(self.engine);engine['files'][0]['sha256']='0'*64
        runtime = copy.deepcopy(self.engine);runtime['environment']['python']['version']='other'
        for e in (engine,runtime):
            e['engineFingerprint']=quality.digest({k:v for k,v in e.items() if k!='engineFingerprint'})
        for kwargs, reason in (({'candidate_context':c},'context_conditions_mismatch'),
            ({'candidate_engine':engine},'engine_fingerprints_differ'),
            ({'candidate_engine':runtime},'engine_environment_mismatch')):
            with self.subTest(reason=reason),patch.object(collector,'collect_metrics') as collect:
                r = self.compare(**kwargs);collect.assert_not_called()
                self.assertEqual(r['comparisonStatus'],'incomparable')
                self.assertEqual(r['inputReadiness'],'incomparable')
                self.assertEqual(diff.exit_code(r),2)
                self.assertIn(reason,r['reasonCodes']);self.assertFalse(r['metricDiffs'])
        self.assertTrue(any(f['code']=='context-mismatch' for f in self.compare(candidate_context=c)['findings']))

    def test_invalid_unavailable_source_store_contract_and_fingerprint(self):
        for target, value, expected in (
            (self.source/'Station_all.json',b'changed',3),
            (self.store/'snapshot.json',b'{}',3),
            (self.store/'snapshot.json',None,3),
        ):
            raw=target.read_bytes()
            try:
                if value is None: target.unlink()
                else: target.write_bytes(value)
                with patch.object(collector,'collect_metrics') as collect:
                    r=self.compare();collect.assert_not_called()
                self.assertEqual(diff.exit_code(r),expected)
                self.assertEqual(r['comparisonStatus'],'failed');self.assertFalse(r['metricDiffs'])
            finally:
                target.write_bytes(raw)
                if target.parent == self.store: target.chmod(0o600)
        with patch.object(quality,'collect_environment',return_value=self.fixture.fixture.env):
            r=diff.compare_quality(self.store,self.store/'absent',self.source,self.source,
                                   engine=self.engine,context=self.context,root=self.fixture.root)
        self.assertEqual(r['inputReadiness'],'unavailable')
        self.assertEqual(diff.exit_code(r),4)

    def test_distinct_synthetic_snapshots_detect_loss_without_id_matching(self):
        source=fixture.make_snapshot(self.fixture.fixture.helper.root/'inactive-input',active=False)
        target=self.fixture.fixture.helper.root/'inactive-store'
        fixture.store.persist_snapshot(target,source)
        with patch.object(quality,'collect_environment',return_value=self.fixture.fixture.env):
            r=diff.compare_quality(self.store,target,self.source,source,
                                   engine=self.engine,context=self.context,root=self.fixture.root)
        self.assertNotEqual(r['baselineContentFingerprint'],r['candidateContentFingerprint'])
        self.assertEqual(r['qualityDiffStatus'],'changed')
        self.assertEqual(r['summary']['metricDiffTotals']['C']['delta'],-18)
        self.assertEqual(r['summary']['metricDiffTotals']['G']['delta'],-156)
        self.assertTrue(any('candidate-disappeared' in f.get('classifications',[]) for f in r['findings']))
        self.assertEqual(diff.exit_code(r),2)

    def test_input_mutation_during_first_collector_call(self):
        original=collector.ItineraryGenerator.generate;changed=False
        target=self.source/'Station_all.json';raw=target.read_bytes()
        def generate(g,day):
            nonlocal changed
            rows=original(g,day)
            if not changed:target.write_bytes(raw+b' ');changed=True
            return rows
        try:
            with patch.object(collector.ItineraryGenerator,'generate',generate):r=self.compare()
            self.assertEqual(r['inputReadiness'],'invalid')
            self.assertFalse(r['metricDiffs'])
            self.assertEqual(diff.exit_code(r),3)
        finally:target.write_bytes(raw)

    def test_change_between_sides_and_during_collection_or_validation(self):
        for kind in ('source','store','engine'):
            target={'source':self.source/'Station_all.json','store':self.store/'snapshot.json',
                    'engine':self.fixture.root/'scripts/odpt_itinerary.py'}[kind]
            raw=target.read_bytes();calls=0;original=collector.collect_metrics
            def collect(*args,**kwargs):
                nonlocal calls
                r=original(*args,**kwargs);calls+=1
                if calls==1: target.write_bytes(raw+b' ')
                return r
            try:
                with self.subTest(kind=kind),patch.object(collector,'collect_metrics',side_effect=collect):
                    r=self.compare()
                    self.assertIn(r['comparisonStatus'],('failed','incomparable'))
                    self.assertFalse(r['metricDiffs']);self.assertEqual(r['qualityDiffStatus'],'indeterminate')
                    self.assertTrue(r['reasonCodes'])
            finally: target.write_bytes(raw)

    def test_changed_and_partial_metric_results_survive_and_limit_status(self):
        original=collector.collect_metrics;calls=0
        def collect(*args,**kw):
            nonlocal calls
            r=original(*args,**kw);calls+=1
            if calls%2==0:
                # A confirmed measured change plus a separate unavailable metric.
                for m in r['metrics']:
                    if m['metricId']=='G':m['value']+=1
                    if m['metricId']=='validTransferPairCount':m.update(availability='unavailable',value=None)
            return r
        with patch.object(collector,'collect_metrics',side_effect=collect):
            r=self.compare()
            limited=self.compare(detail_limit=1)
        self.assertEqual(r['qualityDiffStatus'],'changed')
        self.assertEqual(r['summary']['changedCellCount'],48)
        self.assertEqual(r['summary']['partialCellCount'],48)
        self.assertEqual(diff.exit_code(r),2)
        self.assertEqual(r['summary'],limited['summary'])
        self.assertEqual(limited['qualityDiffStatus'],'changed')
        self.assertEqual(limited['comparisonStatus'],'partial')
        self.assertIn('detail_limit_reached',limited['reasonCodes'])
        self.assertLessEqual(len(limited['baselineMetrics']),1)

    def test_end_checks_cover_arithmetic_comparison_too(self):
        target=self.store/'snapshot.json';raw=target.read_bytes()
        original=diff.compare_basic
        def compare(*args,**kwargs):
            result=original(*args,**kwargs)
            target.write_bytes(raw+b' ')
            return result
        try:
            with patch.object(diff,'compare_basic',side_effect=compare):r=self.compare()
            self.assertEqual(r['inputReadiness'],'invalid')
            self.assertEqual(r['comparisonStatus'],'failed')
            self.assertFalse(r['metricDiffs'])
            self.assertIn('baseline_inputs_changed_during_comparison',r['reasonCodes'])
        finally:target.write_bytes(raw)

    def test_digest_excludes_run_measurements_and_preserves_order(self):
        r=self.compare()
        changed=copy.deepcopy(r);changed.update(elapsedSeconds=3,peakRssBytes=999,generatedAt='later',timings={'all':1})
        self.assertEqual(r['comparisonDigest'],diff.comparison_digest(changed))
        changed['metricDiffs'][0]['delta']=1
        self.assertNotEqual(r['comparisonDigest'],diff.comparison_digest(changed))
        keys=[diff._key(m) for m in r['metricDiffs']]
        self.assertEqual(keys,sorted(keys))
        self.assertTrue(all(m['reasonCodes']==sorted(m['reasonCodes']) for m in r['metricDiffs']))

    def test_cli_fixed_codes_and_difference_is_not_error(self):
        r=self.compare(detail_limit=10000);args=['--baseline-store',str(self.store),'--candidate-store',str(self.store),
                              '--baseline-source-dir',str(self.source),'--candidate-source-dir',str(self.source)]
        for readiness,code in (('ready',0),('incomparable',2),('invalid',3),('unavailable',4)):
            report=copy.deepcopy(r);report['inputReadiness']=readiness
            # Confirmed change alone must succeed.
            report['qualityDiffStatus']='changed'
            out=io.StringIO()
            with patch.object(diff,'compare_quality',return_value=report),redirect_stdout(out):
                self.assertEqual(diff.main(args),code)
            for text in ('trip-6-','synthetic-secret','primary_itinerary','raw-sources'):self.assertNotIn(text,out.getvalue())
            self.assertIn('comparison_status=partial',out.getvalue())
        with redirect_stdout(io.StringIO()),patch('sys.stderr',new=io.StringIO()),self.assertRaises(SystemExit) as exit:
            diff.main([])
        self.assertEqual(exit.exception.code,2)

    def test_actual_comparison_cli_current_engine(self):
        out=io.StringIO()
        with redirect_stdout(out):
            code=diff.main(['--baseline-store',str(self.store),'--candidate-store',str(self.store),
                           '--baseline-source-dir',str(self.source),'--candidate-source-dir',str(self.source)])
        self.assertEqual(code,0)
        self.assertNotIn('detail_limit_reached',out.getvalue())
        self.assertIn('"unchangedCellCount": 48',out.getvalue())
        self.assertIn('quality_diff_status=indeterminate',out.getvalue())
        self.assertNotIn('trip-6-',out.getvalue())


if __name__=='__main__': unittest.main()
