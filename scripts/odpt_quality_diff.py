#!/usr/bin/env python3
"""Private basic/detailed itinerary quality comparison; sequential, memory only."""
from __future__ import annotations

import argparse
import collections
import copy
import itertools
import json
import resource
import sys
import time
from pathlib import Path

if __package__:
    from . import odpt_quality_metrics as collector
    from . import odpt_quality_detail_diff as detail_diff
else:
    import odpt_quality_metrics as collector
    import odpt_quality_detail_diff as detail_diff
quality = collector.quality

DIMENSIONS = ('serviceDate', 'stationId', 'routeId')
SIDES = ('baseline', 'candidate')
DEFAULT_DETAIL_LIMIT = 1000
MAX_DETAIL_LIMIT = 10000
NOT_EVALUATED = sorted((set(collector.NOT_EVALUATED) - {'quality-diff'}) | {
    'display-model-diff', 'quality-verdict',
    'cross-generation-trip-or-public-id-matching',
})


def _key(metric):
    return tuple(metric['dimensions'][k] for k in DIMENSIONS) + (metric['metricId'],)


def _compact(report):
    # Retain aggregates only; generator/DTO observations are released before the other side.
    return {k: copy.deepcopy(report.get(k)) for k in (
        'snapshotId', 'contentFingerprint', 'contextFingerprint', 'engineFingerprint',
        'collectionStatus', 'basicMetricsStatus', 'reasonCodes', 'failureCategory')} | {
        'metrics': sorted((copy.deepcopy(m) for m in report['metrics']
                           if m['metricId'] in collector.METRIC_UNITS), key=_key),
        'detailedMetrics': sorted((copy.deepcopy(m) for m in report['metrics']
                                  if m['metricId'] in collector.details.UNITS), key=_key),
        'detailedConsistency': copy.deepcopy(report['checks'].get('detailedConsistency', [])),
        'inputChecks': {k: copy.deepcopy(report['checks'][k]) for k in (
            'inputStart', 'inputEnd', 'inputImmutability') if k in report['checks']}}


def _index(metrics):
    index = collections.defaultdict(list)
    for metric in metrics:
        index[_key(metric)].append(metric)
    return index


def _valid(metric):
    if metric is None or metric.get('availability') != 'known':
        return False
    value = metric.get('value')
    if metric['metricId'] == 'exclusionReasonCounts':
        return (isinstance(value, dict) and set(value) == set(collector.v2.EXCLUSION_REASONS)
                and all(type(v) is int and v >= 0 for v in value.values()))
    return type(value) is int and value >= 0


def _one(index, cell, name):
    entries = index.get(cell + (name,), [])
    return entries[0] if len(entries) == 1 else None


def _side_checks(index, cell):
    # Reuse the collector's independent arithmetic checks, even when deltas are zero.
    metrics = [_one(index, cell, m) for m in sorted(collector.METRIC_UNITS)]
    safe = []
    for name, metric in zip(sorted(collector.METRIC_UNITS), metrics):
        if metric is None:
            metric = collector._metric(name, dict(zip(DIMENSIONS, cell)),
                                       availability='unavailable', reasons=['metric_missing_or_duplicate'])
        elif not _valid(metric):
            metric = {**metric, 'availability': 'unavailable', 'value': None}
        safe.append(metric)
    return collector._consistency(safe)


def _diff(baseline, candidate, dims, name, reason=None):
    reasons = set()
    values = []
    for side, metric in zip(SIDES, (baseline, candidate)):
        if metric is None:
            reasons.add(side + '_metric_missing_or_duplicate')
        elif not _valid(metric):
            reasons.add(side + '_metric_not_evaluable')
            reasons.update(metric.get('reasonCodes', []))
        values.append((metric['value'].get(reason) if reason else metric['value'])
                      if _valid(metric) else None)
    if baseline is not None and candidate is not None:
        # Counts use the same unit and definition under the frozen profile/engine.
        for field in ('unit', 'numerator', 'denominator'):
            if baseline.get(field) != candidate.get(field):
                reasons.add('metric_definition_mismatch')
        if baseline.get('unit') != collector.METRIC_UNITS[name]:
            reasons.add('metric_definition_mismatch')
    delta = None if reasons else values[1] - values[0]
    direction = ('not-evaluable' if delta is None else 'unchanged' if delta == 0
                 else 'candidate-increased' if delta > 0 else 'candidate-decreased')
    classifications = [direction]
    if delta is not None and delta != 0:
        if name == 'C' and values[0] > 0 and values[1] == 0:
            classifications.append('candidate-disappeared')
        if name == 'primaryDirectCount' and delta < 0:
            classifications.append('direct-decreased')
        if name == 'primaryTransferCount' and delta < 0:
            classifications.append('transfer-decreased')
        if name in {'E', 'exclusionReasonCounts'}:
            classifications.append('exclusion-increased' if delta > 0 else 'exclusion-decreased')
    return {'dimensions': dict(dims), 'metricId': name + ('.' + reason if reason else ''),
            'baselineValue': values[0], 'candidateValue': values[1], 'delta': delta,
            'deltaDirection': direction, 'comparisonAvailability': 'known' if delta is not None else 'not-evaluable',
            'reasonCodes': sorted(reasons), 'classifications': sorted(classifications)}


def compare_basic(baseline, candidate, context, *, detail_limit=DEFAULT_DETAIL_LIMIT):
    """Compare only basic aggregates, with bounded evidence and unbounded counts.

    This internal stage requires the caller's completed input/engine binding. No
    identifier in a journey is joined across generations. Missing cells stay missing.
    """
    if type(detail_limit) is not int or not 0 <= detail_limit <= MAX_DETAIL_LIMIT:
        quality.fail('detail_limit_invalid')
    indexes = [_index(side['metrics']) for side in (baseline, candidate)]
    expected = set(itertools.product(*(context[k] for k in ('serviceDates', 'stationIds', 'routeIds'))))
    cells = sorted(expected | {key[:3] for index in indexes for key in index})
    diffs, findings, checks = [], [], []
    counts = collections.Counter()
    check_counts = {side: collections.Counter() for side in SIDES}
    totals = {}
    omitted = collections.Counter()

    def retain(name, target, item):
        if len(target) < detail_limit:
            target.append(item)
        else:
            omitted[name] += 1

    for cell in cells:
        dims = dict(zip(DIMENSIONS, cell))
        consistent = True
        for side, index in zip(SIDES, indexes):
            for check in _side_checks(index, cell):
                check = {**check, 'side': side}
                check_counts[side][check['status']] += 1
                retain('consistencyChecks', checks, check)
                if check['status'] != 'PASS':
                    consistent = False
                if check['status'] == 'FAIL':
                    retain('findings', findings, {'code': 'side_consistency_failed', **check})
        changed, full = False, consistent
        for name in sorted(collector.METRIC_UNITS):
            a, b = [_one(index, cell, name) for index in indexes]
            reasons = sorted(collector.v2.EXCLUSION_REASONS) if name == 'exclusionReasonCounts' else [None]
            for reason in reasons:
                diff = _diff(a, b, dims, name, reason)
                if cell not in expected:
                    diff.update(delta=None, deltaDirection='not-evaluable', comparisonAvailability='not-evaluable',
                                reasonCodes=sorted(set(diff['reasonCodes']) | {'cell_outside_context'}),
                                classifications=['not-evaluable'])
                known = diff['comparisonAvailability'] == 'known'
                is_changed = known and diff['delta'] != 0
                changed |= is_changed
                full &= known
                counts['comparedMetricCount' if known else 'notEvaluableMetricCount'] += 1
                counts['changedMetricCount'] += is_changed
                total = totals.setdefault(diff['metricId'], {'baselineValue': None, 'candidateValue': None,
                    'delta': None, 'comparedCellCount': 0, 'notEvaluableCellCount': 0})
                if known:
                    total['comparedCellCount'] += 1
                    for field in ('baselineValue', 'candidateValue', 'delta'):
                        total[field] = (total[field] or 0) + diff[field]
                else:
                    total['notEvaluableCellCount'] += 1
                retain('metricDiffs', diffs, diff)
                # At most one finding per metric/reason/cell, with multiple tags.
                if is_changed or not known:
                    retain('findings', findings, {'code': 'basic_metric_changed' if is_changed else 'not-evaluable', **diff})
        counts['changedCellCount' if changed else 'unchangedCellCount' if full else 'indeterminateCellCount'] += 1
        counts['partialCellCount'] += not full
    summary = {name: counts[name] for name in ('changedCellCount', 'unchangedCellCount', 'indeterminateCellCount',
        'partialCellCount', 'comparedMetricCount', 'notEvaluableMetricCount', 'changedMetricCount')}
    summary.update(cellCount=len(cells), targetCellCount=len(expected), metricDiffTotals=dict(sorted(totals.items())),
                   consistency={side: dict(sorted(check_counts[side].items())) for side in SIDES})
    return {'metricDiffs': diffs, 'findings': findings, 'consistency': checks,
            'summary': summary, 'omittedDetails': dict(sorted(omitted.items()))}


def _category(exc):
    return getattr(exc, 'category', 'unavailable' if exc.code == 'store_not_found' else 'invalid')


def comparison_digest(result):
    """Only deterministic comparison evidence; run measurements are CLI-only."""
    return quality.digest({k: v for k, v in result.items() if k not in {
        'comparisonDigest', 'elapsedSeconds', 'peakRssBytes', 'timings', 'generatedAt'}})


def compare_quality(baseline_store, candidate_store, baseline_source_dir, candidate_source_dir, *,
                    context=None, engine=None, baseline_context=None, candidate_context=None,
                    baseline_engine=None, candidate_engine=None, root=quality.ROOT,
                    detail_limit=DEFAULT_DETAIL_LIMIT):
    result = {'contract': 'dotchi.odpt.itinerary-quality-diff', 'schemaVersion': 1,
        'qualityProfile': dict(quality.PROFILE), 'baselineSnapshotId': None, 'candidateSnapshotId': None,
        'baselineContentFingerprint': None, 'candidateContentFingerprint': None,
        'evaluationContext': None, 'contextFingerprint': None, 'engineFingerprints': None,
        'baselineMetrics': [], 'candidateMetrics': [], 'metricDiffs': [], 'findings': [], 'checks': {},
        'notEvaluated': list(NOT_EVALUATED), 'comparisonStatus': 'failed', 'qualityDiffStatus': 'indeterminate',
        'basicQualityDiffStatus': 'indeterminate', 'inputReadiness': 'ready', 'reasonCodes': [],
        'summary': None, 'omittedDetails': {}, 'detailLimit': detail_limit}
    result.update(baselineDetailedMetrics=[], candidateDetailedMetrics=[], detailedMetricDiffs=[],
                  detailedSummary=None, detailedQualityDiffStatus='indeterminate', confirmedFindingCount=0)
    problems = []
    compact = []
    compared = None
    detailed = None
    before = {}
    paths = [(Path(baseline_store), Path(baseline_source_dir)), (Path(candidate_store), Path(candidate_source_dir))]
    try:
        if type(detail_limit) is not int or not 0 <= detail_limit <= MAX_DETAIL_LIMIT:
            quality.fail('detail_limit_invalid')
        engine = copy.deepcopy(engine) if engine is not None else quality.build_engine(root)
        quality._validate_engine(engine)
        context = copy.deepcopy(context) if context is not None else quality.initial_context(engine['engineFingerprint'])
        contexts = [copy.deepcopy(c if c is not None else context) for c in (baseline_context, candidate_context)]
        engines = [copy.deepcopy(e if e is not None else engine) for e in (baseline_engine, candidate_engine)]
        result['engineFingerprints'] = {side: e.get('engineFingerprint') if isinstance(e, dict) else None
                                        for side, e in zip(SIDES, engines)}
        # Freeze both sides before either evaluation (including store serialization/identity).
        for side, (store, source) in zip(SIDES, paths):
            before[side] = collector._inventory(store, source)

        def validate():
            return quality.validate_inputs(*[p[0] for p in paths], *[p[1] for p in paths],
                                           *contexts, *engines, root=root)

        start = validate()
        result['checks']['inputStart'] = start
        for key in ('baselineSnapshotId', 'candidateSnapshotId', 'baselineContentFingerprint', 'candidateContentFingerprint'):
            result[key] = start[key]
        result['evaluationContext'] = start['evaluationContext']
        result['contextFingerprint'] = start['contextFingerprint']
        if start['comparisonReadiness'] != 'ready':
            problems.append((start['comparisonReadiness'], start['reasonCodes']))
        else:
            for side, (store, source), c, e in zip(SIDES, paths, contexts, engines):
                # Baseline always completes and releases generator/detail observations first.
                report = _compact(collector.collect_metrics(store, source, context=c, engine=e, root=root))
                compact.append(report)
                for check in report['inputChecks'].values():
                    if check.get('comparisonReadiness', 'ready') != 'ready':
                        problems.append((check['comparisonReadiness'], check['reasonCodes']))
                if report['collectionStatus'] == 'failed':
                    statuses = [check.get('comparisonReadiness') for check in report['inputChecks'].values()]
                    category = report['failureCategory'] or next((s for s in ('invalid', 'unavailable', 'incomparable')
                                                                  if s in statuses), 'invalid')
                    problems.append((category, report['reasonCodes'] or ['collection_failed']))
                if (report['snapshotId'] != result[side + 'SnapshotId'] or
                    report['contentFingerprint'] != result[side + 'ContentFingerprint']):
                    problems.append(('invalid', ['collection_snapshot_binding_mismatch']))
                if (report['contextFingerprint'] != contexts[0]['contextFingerprint'] or
                    report['engineFingerprint'] != engines[0]['engineFingerprint']):
                    problems.append(('incomparable', ['collection_conditions_mismatch']))
            if not problems:
                compared = compare_basic(*compact, contexts[0], detail_limit=detail_limit)
                detailed = detail_diff.compare_details(*compact, contexts[0], detail_limit=detail_limit)
            # End checks cover the arithmetic comparison as well as both collectors.
            end = validate()
            result['checks']['inputEnd'] = end
            if end['comparisonReadiness'] != 'ready':
                problems.append((end['comparisonReadiness'], end['reasonCodes']))
    except (quality.QualityInputError, quality.StoreError) as exc:
        problems.append((_category(exc), [exc.code]))
    finally:
        for side, (store, source) in zip(SIDES, paths):
            if side not in before:
                continue
            try:
                same = before[side] == collector._inventory(store, source)
                result['checks'][side + 'InputImmutability'] = {
                    'status': 'PASS' if same else 'FAIL', 'sourceFileCount': 7, 'storeFileCount': 8}
                if not same:
                    problems.append(('invalid', [side + '_inputs_changed_during_comparison']))
            except (quality.QualityInputError, quality.StoreError) as exc:
                result['checks'][side + 'InputImmutability'] = {'status': 'not-confirmed'}
                problems.append((_category(exc), [exc.code]))

    for side, report in zip(SIDES, compact):
        result[side + 'Metrics'] = report['metrics'][:detail_limit]
        omitted = len(report['metrics']) - len(result[side + 'Metrics'])
        if omitted:
            result['omittedDetails'][side + 'Metrics'] = omitted
        actionable = set(detailed['actionableMetricKeys']) if detailed else set()
        candidates = [m for m in report['detailedMetrics']
                      if (tuple(m['dimensions'][k] for k in detail_diff.DIMS),m['metricId']) in actionable]
        result[side+'DetailedMetrics'] = candidates[:detail_limit]
        omitted = len(candidates)-len(result[side+'DetailedMetrics'])
        if omitted: result['omittedDetails'][side+'DetailedMetrics'] = omitted
    if problems:
        result['inputReadiness'] = next(c for c in ('invalid', 'unavailable', 'incomparable') if any(p[0] == c for p in problems))
        result['comparisonStatus'] = 'incomparable' if result['inputReadiness'] == 'incomparable' else 'failed'
        result['reasonCodes'] = sorted({code for _, codes in problems for code in codes})
        findings = [{'code': 'context-mismatch' if code.startswith('context_') else 'not-evaluable',
                     'reasonCodes': [code]} for code in result['reasonCodes']]
        limit = detail_limit if type(detail_limit) is int and 0 <= detail_limit <= MAX_DETAIL_LIMIT else 0
        result['findings'] = findings[:limit]
        if len(findings) > limit:
            result['omittedDetails']['findings'] = len(findings) - limit
        result['notEvaluated'] = sorted(set(result['notEvaluated']) | {'basic-metrics-diff'})
        result['notEvaluated'] = sorted(set(result['notEvaluated']) | {'detailed-metrics-diff'} | set(detail_diff.TIME_NOT_EVALUATED))
    else:
        result.update(metricDiffs=compared['metricDiffs'], findings=compared['findings'], summary=compared['summary'])
        result['checks']['consistency'] = compared['consistency']
        result['omittedDetails'].update(compared['omittedDetails'])
        # Side summaries are independently measured; delta totals cover only paired known cells.
        result['summary']['baseline'] = collector.summarize({'metrics': compact[0]['metrics'], 'checks': {'consistency': []}})
        result['summary']['candidate'] = collector.summarize({'metrics': compact[1]['metrics'], 'checks': {'consistency': []}})
        for side in SIDES:
            result['summary'][side]['consistency'] = result['summary']['consistency'][side]
        summary = result['summary']
        result['comparisonStatus'] = 'partial' if summary['comparedMetricCount'] else 'failed'
        if summary['changedMetricCount']:
            result['qualityDiffStatus'] = result['basicQualityDiffStatus'] = 'changed'
        elif not summary['partialCellCount']:
            result['basicQualityDiffStatus'] = 'unchanged'
        if summary['partialCellCount']:
            result['notEvaluated'] = sorted(set(result['notEvaluated']) | {'basic-metrics-or-consistency-incomplete'})
        result['detailedMetricDiffs'] = detailed['detailedMetricDiffs']
        result['detailedSummary'] = detailed['summary']
        result['unchangedDetailsAggregatedCount'] = detailed['unchangedDetailsAggregatedCount']
        result['checks']['detailedConsistency'] = detailed['checks']
        result['notEvaluated'] = sorted(set(result['notEvaluated']) | set(detailed['notEvaluated']))
        result['omittedDetails'].update(detailed['omittedDetails'])
        combined = result['findings'] + detailed['findings']
        if len(combined) > detail_limit:
            result['omittedDetails']['combinedFindings'] = len(combined)-detail_limit
        result['findings'] = combined[:detail_limit]
        result['confirmedFindingCount'] = summary['changedMetricCount'] + detailed['summary']['confirmedFindingCount']
        if detailed['summary']['changedMetricCount']:
            result['qualityDiffStatus'] = result['detailedQualityDiffStatus'] = 'changed'
        elif not detailed['summary']['partialCellCount']:
            result['detailedQualityDiffStatus'] = 'unchanged'
        if detailed['summary']['knownMetricCount'] and result['comparisonStatus'] == 'failed':
            result['comparisonStatus'] = 'partial'
    if result['omittedDetails']:
        result['reasonCodes'] = sorted(set(result['reasonCodes']) | {'detail_limit_reached'})
        result['notEvaluated'] = sorted(set(result['notEvaluated']) | {'omitted-comparison-details'})
    result['comparisonDigest'] = comparison_digest(result)
    return result


def exit_code(result):
    if result['inputReadiness'] == 'invalid': return 3
    if result['inputReadiness'] == 'unavailable': return 4
    if (result['inputReadiness'] != 'ready' or result['summary'] is None or
        result['summary']['partialCellCount'] or result['omittedDetails']): return 2
    if (result.get('detailedSummary') or {}).get('partialCellCount'): return 2
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('baseline-store', 'candidate-store', 'baseline-source-dir', 'candidate-source-dir'):
        parser.add_argument('--' + flag, type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    result = compare_quality(args.baseline_store, args.candidate_store, args.baseline_source_dir, args.candidate_source_dir)
    print('profile=' + quality.PROFILE['id'] + ' version=' + quality.PROFILE['version'])
    print('summary=' + json.dumps(result['summary'], sort_keys=True))
    print('detailed_summary=' + json.dumps(result['detailedSummary'], sort_keys=True))
    print('confirmed_finding_count=' + str(result['confirmedFindingCount']))
    print('comparison_status=' + result['comparisonStatus'] + ' quality_diff_status=' + result['qualityDiffStatus']
          + ' basic_quality_diff_status=' + result['basicQualityDiffStatus'] + ' input_readiness=' + result['inputReadiness'])
    print('not_evaluated=' + ','.join(result['notEvaluated']))
    print('reasons=' + (','.join(result['reasonCodes']) or 'none'))
    print('input_immutability=' + json.dumps({side: result['checks'].get(side + 'InputImmutability', {}).get('status', 'not-confirmed')
                                            for side in SIDES}, sort_keys=True))
    print('comparison_digest=' + result['comparisonDigest'])
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f'elapsed_seconds={time.perf_counter() - started:.3f} peak_rss_bytes={rss if sys.platform == "darwin" else rss * 1024}')
    return exit_code(result)


if __name__ == '__main__':
    raise SystemExit(main())
