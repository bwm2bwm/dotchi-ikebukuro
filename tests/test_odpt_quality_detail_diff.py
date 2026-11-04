"""Synthetic collected metrics only; no saved private sources or network."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import odpt_quality_diff as diff
from scripts import odpt_quality_detail_diff as dd
from tests import test_odpt_quality_details as fx
from tests import test_odpt_quality_diff as basic

CTX = basic.CONTEXT
PREFIX = 'matcher.primary.secondLeg.references.'


def report(rows=None, generator=None):
    rows = rows if rows is not None else [fx.row()]
    if generator is None:
        trips = [r.primary_itinerary.first_leg.trip for r in rows if r.primary_itinerary]
        generator = fx.generator(rows, fx.observed(*trips))
    ms = list(fx.values(rows,generator).values())
    bs = diff.collector.measure_cell(rows,fx.DIMS)
    return {'detailedMetrics':ms, 'detailedConsistency':fx.details.checks(bs+ms)}


def get(r, name): return next(m for m in r['detailedMetrics'] if m['metricId']==name)
def change(r, name, value): get(r,name)['value']=value
def metric(r,name): return next(m for m in r['detailedMetricDiffs'] if m['metricId']==name)
def component(record,field): return next(c for c in record['componentDiffs'] if c['field']==field)


class DetailedDiffTests(unittest.TestCase):
    def compare(self,a,b,**kw): return dd.compare_details(a,b,CTX,**kw)

    def test_all_98_metrics_self_comparison_and_zero_rates(self):
        a=report();r=self.compare(a,copy.deepcopy(a))
        self.assertEqual(len(fx.details.UNITS),98)
        self.assertEqual(r['summary']['metricCount'],98)
        self.assertEqual(r['summary']['changedMetricCount'],0)
        self.assertFalse(r['findings'])
        self.assertEqual(r['summary']['unchangedCellCount'],1)
        self.assertFalse(r['detailedMetricDiffs'])
        self.assertEqual(r['summary']['not-applicableMetricCount'],12)
        self.assertGreater(r['unchangedDetailsAggregatedCount'],0)
        self.assertIn('time-inconsistency-count',r['notEvaluated'])
        self.assertIn('transfer-wait-inspected-targets',r['notEvaluated'])

    def test_all_raw_states_native_mapping_and_aggregate_independence(self):
        for state in ('confirmed','ambiguous','unmatched','unavailable','candidate_unconfirmed'):
            a=report();row=fx.row();row.odpt.status='unmatched' if state=='candidate_unconfirmed' else ('unique_match' if state=='confirmed' else state)
            b=report([row],fx.generator([row],{('2026-10-28','6','a'):state}))
            r=self.compare(a,b)
            name='matcher.generated.firstLeg.references.'
            raw=next((m for m in r['detailedMetricDiffs'] if m['metricId']==name+'rawStatusCounts'),None)
            canonical='unique_match' if state=='confirmed' else state
            if raw:self.assertEqual(raw['candidateValue'][canonical],1)
            native=next((m for m in r['detailedMetricDiffs'] if m['metricId']==name+'nativeRawStatusCounts'),None)
            if native:self.assertEqual(native['candidateValue'][state],1)
            if state=='candidate_unconfirmed':
                aggregate=metric(r,name+'aggregatedStatusCounts')
                self.assertEqual(aggregate['candidateValue']['unmatched'],1)
                self.assertNotIn('candidate_unconfirmed',aggregate['candidateValue'])
            if state=='confirmed':self.assertFalse(r['detailedMetricDiffs'])
            if state in ('ambiguous','unmatched'):
                self.assertIn(state+'-increased',raw['classifications'])
            if state=='confirmed':self.assertEqual(r['summary']['changedMetricCount'],0)

    def test_rate_decrease_denominator_change_and_distinct_count_finding(self):
        a=report();rows=[fx.row('a'),fx.row('b')]
        rows[1].odpt.status='ambiguous'
        b=report(rows,fx.generator(rows,{('2026-10-28','6','a'):'confirmed',('2026-10-28','6','b'):'ambiguous'}))
        r=self.compare(a,b)
        p='matcher.generated.firstLeg.references.'
        m=metric(r,p+'rawMatchRate')
        self.assertEqual(m['delta'],-.5)
        self.assertEqual(m['numerator'],{'baseline':1,'candidate':1})
        self.assertEqual(m['denominator'],{'baseline':1,'candidate':2})
        self.assertIn('match-rate-decreased',m['classifications'])
        self.assertIn('denominator-count-changed',m['classifications'])
        self.assertTrue(any(f['metricId']==p+'targetCount' for f in r['findings']))
        self.assertTrue(any(f['metricId']==p+'rawMatchRate' for f in r['findings']))
        summary=r['summary']['metricSummaries'][p+'rawMatchRate']
        self.assertEqual(summary['denominatorChangedCellCount'],1)
        self.assertEqual(summary['rateDelta'],-.5)

    def test_fraction_definition_change_invalid_fraction_and_zero_to_nonzero(self):
        name='matcher.generated.firstLeg.references.rawMatchRate'
        for kind in ('definition','unit','fraction','one-zero','unavailable'):
            a=report();b=copy.deepcopy(a);m=get(b,name)
            if kind=='definition':m['denominatorDefinition']='another-population'
            if kind=='unit':m['unit']='other'
            if kind=='fraction':m['numerator']=99
            if kind=='one-zero':m.update(value=None,numerator=0,denominator=0)
            if kind=='unavailable':m.update(availability='unavailable',value=None,numerator=None)
            r=self.compare(a,b);m=metric(r,name)
            with self.subTest(kind=kind):
                self.assertEqual(m['comparisonAvailability'],'not-evaluable')
                self.assertIsNone(m['delta'])
                self.assertIsNone(r['summary']['metricSummaries'][name]['rateDelta'])

    def test_raw_changes_do_not_change_aggregate_and_rates_are_weighted(self):
        a=report();b=copy.deepcopy(a)
        name='matcher.generated.firstLeg.references.'
        get(b,name+'rawStatusCounts')['value'].update(unique_match=0,candidate_unconfirmed=1)
        get(b,name+'rawMatchRate').update(value=0,numerator=0)
        r=self.compare(a,b)
        self.assertEqual(metric(r,name+'rawMatchRate')['delta'],-1)
        self.assertFalse(any(m['metricId']==name+'aggregatedMatchRate' for m in r['detailedMetricDiffs']))
        # Aggregate rates use paired numerators/denominators, not a mean of cell rates.
        ctx={**CTX,'routeIds':['6','9']}
        for side in (a,b):
            extra=copy.deepcopy(side['detailedMetrics'])
            for m in extra:
                m['dimensions']['routeId']='9'
                if m['metricId']==name+'rawMatchRate':m.update(value=1,numerator=9,denominator=9)
            side['detailedMetrics'].extend(extra)
        r=dd.compare_details(a,b,ctx)
        s=r['summary']['metricSummaries'][name+'rawMatchRate']
        self.assertEqual(s['candidateRate'],.9)
        self.assertAlmostEqual(s['rateDelta'],-.1)

    def test_observed_partial_counts_and_v2_state_survive_missing_canonical_evidence(self):
        a=report();b=copy.deepcopy(a)
        p='matcher.generated.firstLeg.references.'
        for side in (a,b):get(side,p+'rawStatusCounts').update(availability='unavailable',value=None)
        get(b,p+'observedRawStatusCounts')['value'].update(unique_match=0,ambiguous=1)
        get(b,'routeCoverage').update(availability='unavailable',value=None)
        change(b,'routeCoverage.v2DataState','unknown')
        r=self.compare(a,b)
        self.assertTrue(any(f.get('metricId')==p+'observedRawStatusCounts' and f['changed'] for f in r['findings']))
        self.assertTrue(any(f.get('metricId')=='routeCoverage.v2DataState' and 'coverage-regressed' in f['classifications'] for f in r['findings']))

    def test_second_leg_primary_alternative_reference_unique_axes(self):
        second=fx.trip('second','9');rows=[fx.row('a',second),fx.row('b',second)]
        trips=[r.primary_itinerary.first_leg.trip for r in rows]+[second]
        a=report(rows,fx.generator(rows,fx.observed(*trips)))
        raw=fx.observed(*trips);raw[('2026-10-28','9','second')]='unmatched';second.odpt.status='unmatched'
        b=report(rows,fx.generator(rows,raw));r=self.compare(a,b)
        for pop in ('primary','bestTransferAlternative'):
            for counting,n in (('references',2),('unique',1)):
                p=f'matcher.{pop}.secondLeg.{counting}.'
                self.assertEqual(metric(r,p+'rawMatchRate')['delta'],-1)
                self.assertEqual(metric(r,p+'rawMatchRate')['denominator']['baseline'],n)
                self.assertEqual(metric(r,p+'rawStatusCounts')['delta']['unmatched'],n)
                self.assertFalse(any(m['metricId']==f'matcher.{pop}.firstLeg.{counting}.rawMatchRate' for m in r['detailedMetricDiffs']))

    def test_unknown_warning_diagnostics_and_validator_are_separate(self):
        a=report();b=copy.deepcopy(a)
        names=('diagnostics.itinerary.WARNING','diagnostics.v2Exclusions.UNKNOWN',
               'diagnostics.v2Exclusions.WARNING','diagnostics.v2ValidatorRows','diagnostics.v2ValidatorCell')
        for name in names:change(b,name,fx.details._summary([(0,'fixture_error'),(0,'fixture_error')],fx.DIMS,name!='diagnostics.v2ValidatorCell'))
        r=self.compare(a,b)
        for name in names:
            m=metric(r,name)
            self.assertEqual(m['delta']['codeOccurrences'],2)
            self.assertEqual(m['delta']['affectedRowCount'],1)
            self.assertEqual(m['delta']['codes/fixture_error/occurrences'],2)
        self.assertIn('unknown-increased',metric(r,names[1])['classifications'])
        self.assertIn('warning-increased',metric(r,names[0])['classifications'])
        cell=metric(r,'diagnostics.v2ValidatorCell')
        self.assertIsNone(cell['delta']['affectedGeneratedRowCount'])
        self.assertEqual(cell['comparisonAvailability'],'partial')
        self.assertEqual(r['summary']['metricSummaries'][names[0]]['componentTotals']['codeOccurrences']['delta'],2)
        self.assertNotIn('diagnosticGrandTotal',r['summary'])

    def test_histogram_code_absence_is_zero_only_for_known_complete_metric(self):
        a=report();b=copy.deepcopy(a)
        change(a,'diagnostics.itinerary.WARNING',fx.details._summary([(0,'old')],fx.DIMS))
        change(b,'diagnostics.itinerary.WARNING',fx.details._summary([(0,'new')],fx.DIMS))
        r=self.compare(a,b);m=metric(r,'diagnostics.itinerary.WARNING')
        self.assertEqual(m['delta']['codes/old/occurrences'],-1)
        self.assertEqual(m['delta']['codes/new/occurrences'],1)
        get(b,'diagnostics.itinerary.WARNING').update(availability='unavailable',value=None)
        m=metric(self.compare(a,b),'diagnostics.itinerary.WARNING')
        self.assertTrue(all(c['delta'] is None for c in m['componentDiffs']))
        self.assertEqual(m['comparisonAvailability'],'not-evaluable')

    def test_coverage_transitions_evidence_scheduled_and_out_of_range(self):
        for state in ('insufficient','unknown'):
            a=report();b=copy.deepcopy(a)
            v=get(b,'routeCoverage')['value'];v['dataState']=state;v['coverageClassification']='data-insufficient'
            v['scheduledTripCount']=20;v['originEvidence']['dataInsufficientCount']=2
            change(b,'routeCoverage.v2DataState',state)
            r=self.compare(a,b);m=metric(r,'routeCoverage')
            self.assertIn('coverage-regressed',m['classifications'])
            self.assertEqual(m['delta']['scheduledTripCount'],10)
            self.assertEqual(m['delta']['originEvidence/dataInsufficientCount'],2)
            self.assertEqual(r['summary']['metricSummaries']['routeCoverage']['stateTransitions']['dataState'],{'complete -> '+state:1})
            self.assertEqual(r['summary']['metricSummaries']['routeCoverage']['stateCellCounts']['dataState'],{'baseline':{'complete':1},'candidate':{state:1}})
            # Correlated v2 state remains evidence, not a duplicate finding.
            self.assertEqual(sum(f.get('metricId')=='routeCoverage.v2DataState' for f in r['findings']),0)
        get(b,'routeCoverage').update(availability='out-of-range',value=None)
        r=self.compare(a,b)
        self.assertEqual(r['summary']['metricSummaries']['routeCoverage']['availabilityTransitions'],{'known -> out-of-range':1})
        self.assertIsNone(metric(r,'routeCoverage')['candidateValue'].get('scheduledTripCount'))

    def test_train_type_destination_and_brand_are_independent(self):
        a=report();b=copy.deepcopy(a)
        for name in ('trainTypeUnknownCount','destinationMissingCount','serviceBrandOnlyCount'):change(b,name,1)
        r=self.compare(a,b)
        self.assertIn('train-type-unresolved-increased',metric(r,'trainTypeUnknownCount')['classifications'])
        self.assertIn('destination-missing-increased',metric(r,'destinationMissingCount')['classifications'])
        self.assertEqual(metric(r,'serviceBrandOnlyCount')['delta'],1)
        self.assertFalse(any(m['metricId']=='destinationUnknownCount' for m in r['detailedMetricDiffs']))

    def test_missing_duplicate_unavailable_never_zero_and_changes_survive(self):
        a=report();b=copy.deepcopy(a)
        b['detailedMetrics']=[m for m in b['detailedMetrics'] if m['metricId']!='trainTypeUnknownCount']
        get(b,'destinationMissingCount').update(availability='unavailable',value=None)
        change(b,'serviceBrandOnlyCount',2)
        b['detailedMetrics'].append(copy.deepcopy(get(b,'destinationUnknownCount')))
        r=self.compare(a,b)
        for name in ('trainTypeUnknownCount','destinationMissingCount','destinationUnknownCount'):
            self.assertIsNone(metric(r,name)['delta'])
            self.assertEqual(metric(r,name)['comparisonAvailability'],'not-evaluable')
        self.assertEqual(metric(r,'serviceBrandOnlyCount')['delta'],2)
        self.assertEqual(r['summary']['changedCellCount'],1)
        self.assertGreater(r['summary']['confirmedFindingCount'],0)

    def test_limits_omit_evidence_but_preserve_counts_and_determinism(self):
        a=report();b=copy.deepcopy(a);change(b,'serviceBrandOnlyCount',2)
        full=self.compare(a,b)
        for limit in (0,1,3):
            limited=self.compare(a,b,detail_limit=limit)
            self.assertEqual(limited['summary'],full['summary'])
            self.assertLessEqual(len(limited['detailedMetricDiffs']),limit)
            self.assertLessEqual(len(limited['findings']),limit)
            self.assertGreater(limited['summary']['unchangedMetricCount'],0)
            self.assertEqual(limited['summary']['aggregatedUnchangedMetricCount'],
                             limited['summary']['unchangedMetricCount'])
        a['detailedMetrics'].reverse();b['detailedMetrics'].reverse()
        self.assertEqual(full,self.compare(a,b))
        self.assertEqual(diff.comparison_digest(full),diff.comparison_digest(self.compare(a,b)))
        keys=[diff._key(m) for m in full['detailedMetricDiffs']]
        self.assertEqual(keys,sorted(keys))

    def test_changed_and_unevaluable_details_get_priority_over_unchanged(self):
        a=report();b=copy.deepcopy(a);dates=[f'2026-10-{i:02d}' for i in range(1,13)]
        stations=[f'station-{i:02d}' for i in range(1,17)]
        a['detailedConsistency']=b['detailedConsistency']=[]
        for day in dates:
            for station in stations:
                for route in ('6','9'):
                    dims={'snapshotId':'fixture','serviceDate':day,'stationId':station,'routeId':route}
                    for side in (a,b):
                        for m in side['detailedMetrics'][:len(fx.details.UNITS)]:
                            clone=copy.deepcopy(m);clone['dimensions']=dims
                            if side is b and clone['metricId']!='serviceBrandOnlyCount':
                                clone.update(availability='unavailable',value=None,numerator=None,denominator=None,
                                             reasonCodes=['synthetic_unavailable'])
                            elif side is b and clone['metricId']=='serviceBrandOnlyCount':clone['value']=1
                            side['detailedMetrics'].append(clone)
        # Keep only the cloned context; the template metrics belong to no requested cell.
        a['detailedMetrics']=a['detailedMetrics'][len(fx.details.UNITS):]
        b['detailedMetrics']=b['detailedMetrics'][len(fx.details.UNITS):]
        ctx={'serviceDates':dates,'stationIds':stations,'routeIds':['6','9']}
        full=dd.compare_details(a,b,ctx,detail_limit=10000)
        capped=dd.compare_details(a,b,ctx,detail_limit=1000)
        self.assertEqual(capped['summary'],full['summary'])
        self.assertEqual(len(capped['detailedMetricDiffs']),1000)
        self.assertEqual(len(capped['findings']),1000)
        self.assertGreater(capped['omittedDetails']['detailedMetricDiffs'],0)
        self.assertGreater(capped['omittedDetails']['detailedFindings'],0)
        self.assertTrue(all(m['changed'] for m in capped['detailedMetricDiffs'][:100]))
        self.assertTrue(any(m['comparisonAvailability']=='not-evaluable' for m in capped['detailedMetricDiffs']))
        self.assertTrue(all(f.get('changed') for f in capped['findings'][:100]))


class DetailedIntegrationTests(unittest.TestCase):
    def setUp(self): self.helper=basic.QualityDiffTests();self.helper.setUp()
    def tearDown(self):self.helper.tearDown()

    def test_additive_contract_basic_fields_unchanged_and_details_aggregated(self):
        r=self.helper.compare()
        self.assertEqual(len(r['metricDiffs']),672)
        self.assertEqual(r['summary']['comparedMetricCount'],672)
        self.assertEqual(r['detailedSummary']['metricCount'],4704)
        self.assertEqual(r['confirmedFindingCount'],0)
        self.assertEqual(r['detailedSummary']['changedMetricCount'],0)
        self.assertEqual(r['comparisonStatus'],'partial')
        self.assertEqual(r['qualityDiffStatus'],'indeterminate')
        self.assertFalse(r['detailedMetricDiffs'])
        self.assertFalse(r['omittedDetails'])
        self.assertEqual(r['unchangedDetailsAggregatedCount'],r['detailedSummary']['unchangedMetricCount'])
        self.assertGreater(r['unchangedDetailsAggregatedCount'],0)
        self.assertEqual(diff.exit_code(r),0)
        self.assertIn('time-consistency-inspected-targets',r['notEvaluated'])
        self.assertNotIn('detailed-metrics-diff',r['notEvaluated'])
        self.assertEqual(r,self.helper.compare())

    def test_known_detail_change_retained_with_missing_other_metric_and_limits(self):
        original=diff.collector.collect_metrics;calls=0
        def collect(*a,**kw):
            nonlocal calls
            r=original(*a,**kw);calls+=1
            if calls==2:
                for m in r['metrics']:
                    if m['metricId']=='trainTypeUnknownCount':m['value']+=1
                    if m['metricId'].endswith('rawMatchRate'):m.update(value=None,availability='unavailable',numerator=None)
            return r
        with patch.object(diff.collector,'collect_metrics',side_effect=collect):r=self.helper.compare(detail_limit=1)
        self.assertEqual(r['qualityDiffStatus'],'changed')
        self.assertEqual(r['basicQualityDiffStatus'],'unchanged')
        self.assertEqual(r['detailedQualityDiffStatus'],'changed')
        self.assertEqual(r['summary']['changedMetricCount'],0)
        self.assertEqual(r['detailedSummary']['changedMetricCount'],48)
        self.assertGreater(r['confirmedFindingCount'],0)
        self.assertLessEqual(len(r['findings']),1)

    def test_cli_codes_no_gate_and_legacy_arguments(self):
        with patch.object(diff.collector.v2,'validate_bundle',side_effect=AssertionError('gate invoked')):
            r=self.helper.compare(detail_limit=10000)
        self.assertEqual(diff.exit_code(r),0)
        args=['--baseline-store',str(self.helper.store),'--candidate-store',str(self.helper.store),
              '--baseline-source-dir',str(self.helper.source),'--candidate-source-dir',str(self.helper.source)]
        r['qualityDiffStatus']='changed'
        for readiness,code in (('ready',0),('incomparable',2),('invalid',3),('unavailable',4)):
            r['inputReadiness']=readiness;out=io.StringIO()
            with patch.object(diff,'compare_quality',return_value=r),redirect_stdout(out):
                self.assertEqual(diff.main(args),code)
            self.assertIn('detailed_summary=',out.getvalue())
            self.assertIn('confirmed_finding_count=0',out.getvalue())
            for text in ('trip-6-','fixture-head','primary_itinerary'):self.assertNotIn(text,out.getvalue())


if __name__=='__main__':unittest.main()
