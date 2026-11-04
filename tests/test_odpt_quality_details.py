"""Synthetic-only detailed quality observations; no private timetable artifacts."""
import copy
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from scripts import odpt_quality_details as details
from scripts import odpt_quality_metrics as metrics
from tests import test_odpt_quality_metrics as fixtures
from tests.test_odpt_train_matcher import sample_trip, sample_record
from odpt_train_matcher import MatchResult, OdptTrainMatcher
from odpt_itinerary import to_dict


DIMS = {'snapshotId': 'fixture', 'serviceDate': '2026-10-28', 'stationId': 'Hikawadai', 'routeId': '6'}


def trip(identity, route='6', status='unique_match'):
    return NS(service_date='2026-10-28', route_id=route, trip_id=identity,
              odpt=NS(status=status, destination=('FixtureDestination',)))


def row(identity='a', second=None, primary=True):
    first = trip(identity)
    itinerary = NS(kind='transfer' if second else 'direct', departure_seconds=60 + ord(identity[0]),
                   arrival_seconds=600, first_leg=NS(trip=first), second_leg=NS(trip=second) if second else None,
                   transfer_wait_seconds=60 if second else None)
    return NS(origin_trip_id=identity, route_id='6', odpt=first.odpt, data_quality=[],
              primary_itinerary=itinerary if primary else None,
              direct_alternative=itinerary if not second and primary else None,
              best_transfer_alternative=itinerary if second else None,
              status='ok' if primary else 'no_valid_arrival', headsign='fixture-head',
              departure_seconds=itinerary.departure_seconds,
              type_resolution=NS(train_type='Local', source='odpt_confirmed', label='各駅停車', service_brand=None))


def generator(rows, raw=None, **route_overrides):
    evidence = {'scheduledTripCount': 10, 'originTripCount': len(rows),
                'dataInsufficientCount': 0, 'transferDataInsufficientCount': 0, **route_overrides}
    return NS(quality_raw_matches=raw or {}, last_destination_status={'routes': {
        '6': evidence, '9': {**evidence, 'originTripCount': 0}}}, active_service_ids=lambda _: {'0'})


def observed(*trips):
    return {(t.service_date, t.route_id, t.trip_id): 'confirmed' for t in trips}


def values(rows, g=None):
    g = g or generator(rows)
    return {m['metricId']: m for m in details.measure_cell(rows, rows, DIMS, g, date(2026,10,28))}


class DetailMetricsTests(unittest.TestCase):
    def test_native_match_status_observed_once_without_changing_aggregation(self):
        target = sample_trip()
        for native in ('confirmed', 'ambiguous', 'unmatched', 'unavailable', 'candidate_unconfirmed'):
            with self.subTest(native=native):
                match = MatchResult(native, 'fixture', odpt_record=sample_record() if native == 'confirmed' else None)
                calls = []
                matcher = NS(match=lambda *a: (calls.append(a), match)[1])
                base = object.__new__(details.BaseGenerator)
                observer = object.__new__(details.ObservingGenerator); observer.quality_raw_matches = {}
                expected = base._enrich(target, 'Weekday', matcher, ('same-object',))
                calls.clear()
                actual = observer._enrich(target, 'Weekday', matcher, ('same-object',))
                self.assertEqual(actual, expected); self.assertEqual(len(calls), 1)
                self.assertIs(calls[0][0], target)
                self.assertEqual(observer.quality_raw_matches[(target.service_date, target.route_id, target.trip_id)], native)
                if native == 'candidate_unconfirmed': self.assertEqual(actual.status, 'unmatched')
                population = [((target.service_date,target.route_id,target.trip_id), actual.status)]
                ms = {m['metricId']:m for m in details._match_metrics('generated.firstLeg', population, DIMS, observer.quality_raw_matches)}
                canonical = 'unique_match' if native == 'confirmed' else native
                self.assertEqual(ms['matcher.generated.firstLeg.references.rawStatusCounts']['value'][canonical], 1)
                self.assertEqual(ms['matcher.generated.firstLeg.references.nativeRawStatusCounts']['value'], {native: 1})

    def test_unobserved_raw_is_not_inferred_from_generator_status(self):
        r = row(); ms = values([r])
        raw = ms['matcher.generated.firstLeg.references.rawStatusCounts']
        self.assertEqual(raw['availability'], 'unavailable'); self.assertIsNone(raw['value'])
        self.assertEqual(ms['matcher.generated.firstLeg.references.rawObservedTargetCount']['value'], 0)
        self.assertEqual(ms['matcher.generated.firstLeg.references.aggregatedMatchRate']['value'], 1)
        self.assertIsNone(ms['matcher.generated.firstLeg.references.rawMatchRate']['numerator'])

    def test_raw_candidate_and_aggregate_unmatched_remain_separate(self):
        r = row(); r.odpt.status = 'unmatched'
        ms = values([r], generator([r], {('2026-10-28','6','a'): 'candidate_unconfirmed'}))
        prefix = 'matcher.generated.firstLeg.references.'
        self.assertEqual(ms[prefix+'rawStatusCounts']['value']['candidate_unconfirmed'], 1)
        self.assertEqual(ms[prefix+'aggregatedStatusCounts']['value']['unmatched'], 1)
        self.assertEqual(ms[prefix+'rawMatchRate']['value'], 0)

    def test_second_leg_references_unique_denominators_and_alternatives(self):
        second = trip('second', '9'); a, b = row('a', second), row('b', second)
        raw = observed(a.primary_itinerary.first_leg.trip, b.primary_itinerary.first_leg.trip, second)
        ms = values([a,b], generator([a,b], raw))
        for population in ('primary.secondLeg', 'bestTransferAlternative.secondLeg'):
            self.assertEqual(ms[f'matcher.{population}.references.targetCount']['value'], 2)
            self.assertEqual(ms[f'matcher.{population}.unique.targetCount']['value'], 1)
            for counting, n in [('references',2),('unique',1)]:
                rate = ms[f'matcher.{population}.{counting}.rawMatchRate']
                self.assertEqual((rate['numerator'],rate['denominator'],rate['value']), (n,n,1))
        self.assertEqual(ms['matcher.generated.firstLeg.unique.targetCount']['value'], 2)
        # Removing primary does not remove an alternative's leg references.
        a.primary_itinerary = None
        ms = values([a,b], generator([a,b], raw))
        self.assertEqual(ms['matcher.primary.secondLeg.references.targetCount']['value'], 1)
        self.assertEqual(ms['matcher.bestTransferAlternative.secondLeg.references.targetCount']['value'], 2)

    def test_zero_denominator_is_null_and_zero_counts_are_known(self):
        ms = values([])
        self.assertEqual(ms['diagnostics.v2ValidatorCell']['value']['affectedGeneratedRowCount'], 0)
        for name,m in ms.items():
            if name.endswith('Rate'):
                self.assertEqual(m['availability'], 'known'); self.assertIsNone(m['value'])
                self.assertEqual((m['numerator'],m['denominator']), (0,0))
        self.assertEqual(ms['matcher.primary.secondLeg.unique.targetCount']['value'], 0)

    def test_warning_occurrences_rows_and_unknown_exclusions_are_independent(self):
        a, b = row('a', primary=False), row('b', primary=False)
        a.data_quality = ['fixture_warning','fixture_warning','destination_explicit_pass']
        ms = values([a,b])
        warning = ms['diagnostics.itinerary.WARNING']['value']
        self.assertEqual((warning['codeOccurrences'],warning['affectedGeneratedRowCount']), (2,1))
        self.assertEqual(warning['codes']['fixture_warning']['affectedCells'], [DIMS])
        self.assertEqual(ms['diagnostics.itinerary.INFO']['value']['codeOccurrences'], 1)
        self.assertEqual(ms['diagnostics.v2Exclusions.WARNING']['value']['codeOccurrences'], 1)
        unknown = ms['diagnostics.v2Exclusions.UNKNOWN']['value']
        self.assertEqual(unknown['codes']['no_valid_arrival']['occurrences'], 1)
        self.assertEqual(ms['diagnostics.v2ValidatorRows']['value']['codeOccurrences'], 0)

    def test_validator_errors_are_separate_from_exclusion_unknown(self):
        r = row(); r.headsign = None
        ms = values([r])
        self.assertEqual(ms['diagnostics.v2Exclusions.UNKNOWN']['value']['codeOccurrences'], 0)
        errors = ms['diagnostics.v2ValidatorRows']['value']
        self.assertEqual(errors['codeOccurrences'], 1)
        self.assertIn('destination_invalid', errors['codes'])
        self.assertIsNone(ms['diagnostics.v2ValidatorCell']['value']['affectedGeneratedRowCount'])
        self.assertEqual(ms['destinationMissingCount']['value'], 1)

    def test_route_coverage_reuses_states_and_distinguishes_calendar_evidence(self):
        r = row()
        self.assertEqual(values([r])['routeCoverage']['value']['dataState'], 'complete')
        ms = values([r], generator([r], dataInsufficientCount=2))
        self.assertEqual(ms['routeCoverage']['value']['dataState'], 'insufficient')
        self.assertEqual(ms['routeCoverage']['value']['originEvidence']['dataInsufficientCount'], 2)
        g = generator([]); g.last_destination_status = {'routes': {}}
        ms = values([], g)
        self.assertEqual(ms['routeCoverage.v2DataState']['value'], 'unknown')
        self.assertEqual(ms['routeCoverage']['availability'], 'unavailable')
        g = generator([], scheduledTripCount=0); g.active_service_ids = lambda _: set()
        ms = values([], g)
        self.assertEqual(ms['routeCoverage']['value']['coverageClassification'], 'no-active-service')
        self.assertEqual(ms['routeCoverage']['value']['dataState'], 'unknown')
        g.active_service_ids = lambda _: {'0'}
        self.assertEqual(values([], g)['routeCoverage']['value']['coverageClassification'], 'no-scheduled-route-service')
        self.assertEqual(values([])['routeCoverage']['value']['coverageClassification'], 'no-origin-direction-candidates')
        outside = {m['metricId']:m for m in details.empty_cell(DIMS,'out-of-range','service_date_outside_feed')}
        self.assertEqual(outside['routeCoverage']['availability'], 'out-of-range')
        self.assertIsNone(outside['routeCoverage']['value'])

    def test_type_destination_provenance_and_brand_without_metro_type(self):
        rows = [row(chr(97+i)) for i in range(4)]
        rows[1].type_resolution.source = 'gtfs_stop_pattern'; rows[1].odpt.status = 'unmatched'
        rows[2].type_resolution = NS(source='unknown',label='種別不明',train_type=None,service_brand=None)
        rows[2].headsign = None
        rows[3].type_resolution = NS(source='odpt_confirmed',label='Fライナー',train_type=None,service_brand='F-Liner')
        ms = {m['metricId']:m for m in details.display_quality(rows,DIMS)}
        self.assertEqual([ms[n]['value'] for n in ('trainTypeConfirmedCount','trainTypeAuxiliaryCount','trainTypeUnknownCount')], [1,1,2])
        self.assertEqual(ms['serviceBrandOnlyCount']['value'], 1)
        self.assertEqual([ms[n]['value'] for n in ('destinationConfirmedCount','destinationMissingCount','destinationUnknownCount')], [2,1,1])
        rows[0].type_resolution = NS(label='種別不明')
        ms = {m['metricId']:m for m in details.display_quality(rows,DIMS)}
        self.assertEqual(ms['trainTypeConfirmedCount']['availability'], 'unavailable')
        self.assertIsNone(ms['trainTypeConfirmedCount']['value'])

    def test_missing_leg_evidence_is_unavailable_while_other_metrics_survive(self):
        r = row(); del r.primary_itinerary.first_leg
        ms = values([r])
        self.assertEqual(ms['matcher.primary.firstLeg.references.targetCount']['availability'], 'unavailable')
        self.assertEqual(ms['matcher.generated.firstLeg.references.targetCount']['value'], 1)
        self.assertEqual(ms['trainTypeConfirmedCount']['value'], 1)

    def test_opt_in_observer_preserves_full_generator_dto_and_call_count(self):
        helper = fixtures.QualityMetricsTests(); helper.setUp()
        try:
            kwargs = {'gtfs_zip':helper.source/'TokyoMetro-Train-GTFS.zip', 'odpt_dir':helper.source,
                      'destination_station_id':'Hikawadai','max_transfer_seconds':3600}
            base = details.BaseGenerator(**kwargs); observer = details.ObservingGenerator(**kwargs)
            original = OdptTrainMatcher.match
            with patch.object(OdptTrainMatcher,'match',autospec=True,side_effect=original) as spy:
                expected = base.generate(date(2026,10,28)); count = spy.call_count; spy.reset_mock()
                actual = observer.generate(date(2026,10,28))
                self.assertEqual(spy.call_count,count)
            self.assertEqual([to_dict(r) for r in actual], [to_dict(r) for r in expected])
            self.assertFalse(hasattr(base,'quality_raw_matches'))
            self.assertTrue(observer.quality_raw_matches)
            with patch.object(metrics.v2,'validate_bundle',side_effect=AssertionError('gate called')):
                report = helper.collect()
            self.assertEqual(report['detailedMetricsStatus'],'collected')
            self.assertEqual(report['collectionStatus'],'partial')
            self.assertEqual(report, helper.collect())
            with patch.object(metrics, 'ItineraryGenerator', details.BaseGenerator):
                unobserved = helper.collect()
            self.assertEqual(unobserved['basicMetricsStatus'], 'collected')
            self.assertEqual(unobserved['detailedMetricsStatus'], 'partial')
            raw = [m for m in unobserved['metrics'] if m['metricId']=='matcher.generated.firstLeg.references.rawStatusCounts']
            self.assertTrue(all(m['availability']=='unavailable' and m['value'] is None for m in raw))
        finally: helper.tearDown()

    def test_summary_weighted_rate_and_no_global_unique_claim(self):
        second = trip('second','9'); rows = [row('a',second),row('b',second)]
        ms = list(values(rows, generator(rows, observed(second))).values())
        summary = metrics.summarize_details({'metrics':ms})
        rate = summary['matcher.primary.secondLeg.references.rawMatchRate']['value']
        self.assertEqual(rate, {'numerator':2,'denominator':2,'rate':1})
        self.assertEqual(summary['matcher.primary.secondLeg.unique.targetCount']['value'], 1)


if __name__ == '__main__': unittest.main()
