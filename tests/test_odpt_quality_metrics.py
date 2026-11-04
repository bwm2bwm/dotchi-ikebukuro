"""Synthetic fixtures only; no saved local timetable inputs."""
import copy
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scripts import odpt_quality_metrics as metrics
from scripts import odpt_quality_input as quality
from scripts import odpt_source_store as store
from tests import test_odpt_quality_input as input_fixture
from tests.test_odpt_snapshot_qa import make_snapshot


def journey(kind='direct', arrival=600):
    return NS(kind=kind, departure_seconds=60, arrival_seconds=arrival,
              second_leg=NS(trip=NS(route_id='9')) if kind == 'transfer' else None,
              transfer_wait_seconds=60 if kind == 'transfer' else None)


def row(primary=None, direct=None, transfer=None, pairs=0, codes=(), status='no_valid_arrival', wait=False):
    return NS(primary_itinerary=primary, direct_alternative=direct, best_transfer_alternative=transfer,
              transfer_candidates_count=pairs, route_id='6', departure_seconds=60, headsign='synthetic-secret',
              type_resolution=NS(label='synthetic-type'), data_quality=list(codes), status=status,
              transfer_wait_policy_excluded=wait)


class QualityMetricsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = input_fixture.QualityInputTests(); self.fixture.setUp()
        self.root = self.fixture.root
        self.source = make_snapshot(self.fixture.helper.root / 'metric-input')
        self.store = self.fixture.helper.root / 'metric-store'
        store.persist_snapshot(self.store, self.source)
        self.engine = self.fixture.engine
        self.context = self.fixture.context
        self.dims = {'snapshotId': 'synthetic', 'serviceDate': '2026-10-28', 'stationId': 'Hikawadai', 'routeId': '6'}

    def tearDown(self): self.fixture.tearDown()

    def collect(self, **kwargs):
        with patch.object(quality, 'collect_environment', return_value=self.fixture.env):
            return metrics.collect_metrics(self.store, self.source, engine=kwargs.pop('engine', self.engine),
                                           context=kwargs.pop('context', self.context), root=self.root, **kwargs)

    @staticmethod
    def values(cell): return {m['metricId']: m['value'] for m in cell}

    def test_generation_projection_exclusions_alternatives_and_pairs(self):
        direct, transfer = journey(), journey('transfer', 700)
        faster = journey('transfer', 500)
        rows = [row(direct, direct, transfer, 3), row(faster, direct, faster, 2)]
        rows += [row(codes=['destination_explicit_pass']), row(wait=True), row(),
                 row(journey(arrival=None)), row(codes=['independent_warning']), row(status='other')]
        cell = metrics.measure_cell(rows, self.dims); values = self.values(cell)
        self.assertEqual([values[k] for k in ('G', 'C', 'E')], [8, 2, 6])
        self.assertEqual([values[k] for k in ('primaryDirectCount', 'primaryTransferCount')], [1, 1])
        self.assertEqual(values['exclusionReasonCounts'], {k: 1 for k in metrics.v2.EXCLUSION_REASONS})
        # Both retained rows have a direct alternative; only one has direct primary.
        self.assertEqual(values['alternativeDirectRowCount'], 2)
        self.assertEqual(values['bestTransferRowCount'], 2)
        self.assertEqual(values['validTransferPairCount'], 5)
        self.assertTrue(all(c['status'] == 'PASS' for c in metrics._consistency(cell)))

    def test_zero_vs_unavailable_without_inference(self):
        cell = metrics.measure_cell([], self.dims)
        self.assertTrue(all(m['availability'] == 'known' for m in cell))
        self.assertEqual(self.values(cell)['validTransferPairCount'], 0)
        r = row(); del r.transfer_candidates_count; del r.direct_alternative
        values = {m['metricId']: m for m in metrics.measure_cell([r], self.dims)}
        for name in ('validTransferPairCount', 'alternativeDirectRowCount'):
            self.assertEqual(values[name]['availability'], 'unavailable')
            self.assertIsNone(values[name]['value']); self.assertTrue(values[name]['reasonCodes'])
        self.assertEqual(values['C']['value'], 0)
        r.transfer_candidates_count = False
        values = {m['metricId']: m for m in metrics.measure_cell([r], self.dims)}
        self.assertEqual(values['validTransferPairCount']['availability'], 'unavailable')

    def test_duplicate_projection_fails_without_erasing_generated_count(self):
        direct = journey()
        cell = {m['metricId']: m for m in metrics.measure_cell(
            [row(direct, direct), row(direct, direct)], self.dims)}
        self.assertEqual(cell['G']['value'], 2)
        self.assertEqual(cell['C']['availability'], 'failed')
        self.assertIsNone(cell['E']['value'])
        self.assertEqual(cell['C']['reasonCodes'], ['duplicate_public_journey'])

    def test_no_active_service_is_known_zero_in_all_48_cells(self):
        make_snapshot(self.source, active=False)
        self.store = self.fixture.helper.root / 'inactive-store'
        store.persist_snapshot(self.store, self.source)
        report = self.collect(); summary = metrics.summarize(report)
        self.assertEqual(summary['cellCount'], 48)
        self.assertEqual(summary['unevaluableCellCount'], 0)
        self.assertEqual(summary['rowInstanceTotals']['G'], 0)
        self.assertEqual(summary['rowInstanceTotals']['C'], 0)
        self.assertEqual(report['basicMetricsStatus'], 'collected')

    def test_consistency_findings_do_not_repair_measurements(self):
        cell = metrics.measure_cell([], self.dims)
        next(m for m in cell if m['metricId'] == 'G')['value'] = 2
        next(m for m in cell if m['metricId'] == 'primaryDirectCount')['value'] = 1
        checks = metrics._consistency(cell)
        self.assertEqual([c['status'] for c in checks], ['FAIL', 'FAIL', 'PASS'])
        self.assertEqual(self.values(cell)['G'], 2)
        with patch.object(metrics, 'measure_cell', return_value=cell):
            report = self.collect()
        self.assertTrue(report['findings']); self.assertEqual(report['basicMetricsStatus'], 'partial')

    def test_48_cells_contract_order_determinism_and_no_persistence(self):
        before = metrics._inventory(self.store, self.source)
        tree = sorted(p.relative_to(self.fixture.helper.root).as_posix() for p in self.fixture.helper.root.rglob('*'))
        a = self.collect(); b = self.collect()
        self.assertEqual(a, b)
        self.assertEqual(a['collectionStatus'], 'partial'); self.assertEqual(a['basicMetricsStatus'], 'collected')
        summary = metrics.summarize(a)
        self.assertEqual(summary['cellCount'], 48); self.assertEqual(summary['unevaluableCellCount'], 0)
        self.assertEqual(summary['consistency'], {'PASS': 144})
        keys = [tuple(m['dimensions'][k] for k in ('serviceDate', 'stationId', 'routeId')) + (m['metricId'],) for m in a['metrics']]
        self.assertEqual(keys, sorted(keys)); self.assertEqual(len(set(keys)), 48 * (9 + len(metrics.details.UNITS)))
        self.assertTrue(all(set(m) == {'metricId','dimensions','availability','value','unit','reasonCodes','evidenceRefs','numerator','denominator'} for m in a['metrics']))
        self.assertEqual(before, metrics._inventory(self.store, self.source))
        self.assertEqual(tree, sorted(p.relative_to(self.fixture.helper.root).as_posix() for p in self.fixture.helper.root.rglob('*')))
        self.assertNotIn('trip-6-', json.dumps(a))

    def test_exact_existing_v2_projection_equivalence(self):
        generator = metrics.ItineraryGenerator(self.source / 'TokyoMetro-Train-GTFS.zip', self.source,
            min_transfer_seconds=self.context['minimumWaitSeconds'],
            max_transfer_seconds=self.context['maximumWaitSeconds'])
        payload, existing = metrics.v2._build_station_payload(generator, 'Hikawadai', self.context['serviceDates'], '2026-10-29T00:00:00Z')
        report = self.collect()
        selected = [m for m in report['metrics'] if m['dimensions']['stationId'] == 'Hikawadai']
        values = metrics.summarize({**report, 'metrics': selected})['rowInstanceTotals']
        self.assertEqual(values['G'], existing['itineraryResultCount'])
        self.assertEqual(values['C'], sum(len(d['departures']) for d in payload['serviceDays']))
        audit = metrics.v2._build_exclusion_audit(existing['exclusionAudit'])
        self.assertEqual(values['E'], audit['excludedCount'])
        self.assertEqual(values['exclusionReasonCounts'], audit['reasonCounts'])

    def test_local_date_failure_preserves_other_cells(self):
        original = metrics.ItineraryGenerator.generate
        def generate(g, day):
            if day == date(2026,10,29) and g.destination_station_id == 'Hikawadai': raise metrics.FeedDateError()
            return original(g, day)
        with patch.object(metrics.ItineraryGenerator, 'generate', generate): report = self.collect()
        summary = metrics.summarize(report)
        self.assertEqual(summary['unevaluableCellCount'], 2)
        self.assertEqual(summary['knownCellCounts']['G'], 46)
        unknown = [m for m in report['metrics'] if m['availability'] == 'out-of-range']
        self.assertEqual(len(unknown), 2 * (9 + len(metrics.details.UNITS))); self.assertTrue(all(m['value'] is None for m in unknown))
        self.assertEqual(report['collectionStatus'], 'partial')

    def test_generator_and_projection_failure_keep_confirmed_metrics(self):
        original = metrics.ItineraryGenerator
        def factory(**kw):
            if kw['destination_station_id'] == 'Senkawa': raise ValueError('secret')
            return original(**kw)
        with patch.object(metrics, 'ItineraryGenerator', side_effect=factory): report = self.collect()
        self.assertEqual(metrics.summarize(report)['unevaluableCellCount'], 6)
        with patch.object(metrics.v2, '_public_departure', side_effect=ValueError('secret')):
            report = self.collect()
        self.assertEqual(metrics.summarize(report)['knownCellCounts']['G'], 48)
        self.assertIsNone(metrics.summarize(report)['rowInstanceTotals']['C'])
        self.assertNotIn('secret', json.dumps(report))

    def test_invalid_input_and_engine_mismatch_prevent_generation(self):
        malformed = metrics.collect_metrics(self.store, self.source, engine={}, root=self.root)
        self.assertEqual(malformed['collectionStatus'], 'failed')
        self.assertEqual(malformed['reasonCodes'], ['engine_contract_invalid'])
        for kind in ('source', 'context', 'engine'):
            with self.subTest(kind=kind):
                c, e = copy.deepcopy(self.context), copy.deepcopy(self.engine)
                path = self.source / 'Station_all.json'; raw = path.read_bytes()
                if kind == 'source': path.write_bytes(b'changed')
                if kind == 'context': c['contextFingerprint'] = '0' * 64
                if kind == 'engine':
                    e['files'][0]['sha256'] = '0' * 64
                    e['engineFingerprint'] = quality.digest({k:v for k,v in e.items() if k != 'engineFingerprint'})
                with patch.object(metrics, 'ItineraryGenerator') as generator:
                    report = self.collect(context=c, engine=e)
                    generator.assert_not_called()
                self.assertEqual(report['collectionStatus'], 'failed'); self.assertFalse(report['metrics'])
                path.write_bytes(raw)

    def test_original_store_and_engine_changes_during_collection(self):
        original = metrics.ItineraryGenerator.generate
        for kind in ('source', 'store', 'engine'):
            with self.subTest(kind=kind):
                path = {'source': self.source / 'Station_all.json', 'store': self.store / 'snapshot.json',
                        'engine': self.root / 'scripts/odpt_train_matcher.py'}[kind]
                raw = path.read_bytes(); changed = False
                def mutate(g, day):
                    nonlocal changed
                    result = original(g, day)
                    if not changed:
                        # Store JSON remains semantically identical: physical bytes must still be checked.
                        path.write_bytes(raw + b' '); changed = True
                    return result
                with patch.object(metrics.ItineraryGenerator, 'generate', mutate): report = self.collect()
                self.assertEqual(report['collectionStatus'], 'failed')
                self.assertTrue(all(m['value'] is None and m['availability'] == 'failed' for m in report['metrics']))
                self.assertTrue(report['reasonCodes']); path.write_bytes(raw)

    def test_input_read_mutation_and_invalid_store(self):
        original = quality._read; calls = 0
        def changed(path):
            nonlocal calls
            raw, identity = original(path)
            if path == self.source / 'Station_all.json':
                calls += 1
                if calls > 1: identity = (*identity[:-1], identity[-1] + calls)
            return raw, identity
        with patch.object(quality, '_read', side_effect=changed): report = self.collect()
        self.assertEqual(report['collectionStatus'], 'failed')
        (self.store / 'snapshot.json').write_text('{}')
        self.assertEqual(self.collect()['collectionStatus'], 'failed')

    def test_cli_summary_exit_codes_and_gate_independence(self):
        report = self.collect(); out = io.StringIO()
        with patch.object(metrics, 'collect_metrics', return_value=report), redirect_stdout(out):
            code = metrics.main(['--store', str(self.store), '--source-dir', str(self.source)])
        self.assertEqual(code, 0); self.assertIn('collection_status=partial', out.getvalue())
        for text in ('trip-', 'synthetic-secret', 'primary_itinerary'): self.assertNotIn(text, out.getvalue())
        for status, readiness, expected in [('partial', 'ready', 2), ('failed', 'invalid', 3), ('failed', 'incomparable', 2), ('failed', 'unavailable', 4)]:
            altered = copy.deepcopy(report); altered['collectionStatus'] = status; altered['basicMetricsStatus'] = 'partial'
            altered['checks']['inputEnd']['comparisonReadiness'] = readiness
            with patch.object(metrics, 'collect_metrics', return_value=altered), redirect_stdout(io.StringIO()):
                self.assertEqual(metrics.main(['--store', str(self.store), '--source-dir', str(self.source)]), expected)
        # The collector can diagnose unresolved coverage without calling the public bundle gate.
        with patch.object(metrics.v2, '_route_state', wraps=metrics.v2._route_state) as coverage, \
             patch.object(metrics.v2, 'validate_bundle', side_effect=AssertionError('public gate called')):
            self.assertEqual(self.collect()['basicMetricsStatus'], 'collected')
            self.assertTrue(coverage.called)

    def test_cli_actual_current_engine_with_synthetic_sources(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = metrics.main(['--store', str(self.store), '--source-dir', str(self.source)])
        self.assertEqual(code, 0)
        self.assertIn('"cellCount": 48', out.getvalue())
        self.assertIn('input_immutability=PASS', out.getvalue())
        self.assertNotIn('trip-6-', out.getvalue())


if __name__ == '__main__': unittest.main()
