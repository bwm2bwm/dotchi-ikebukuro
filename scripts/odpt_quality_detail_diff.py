"""Typed comparisons of the existing 98 collected metrics; no journey inspection."""
from collections import Counter, defaultdict
import copy
import itertools
import math

if __package__:
    from . import odpt_quality_details as details
else:
    import odpt_quality_details as details

DIMS = ('serviceDate', 'stationId', 'routeId')
SIDES = ('baseline', 'candidate')
TIME_NOT_EVALUATED = ['time-consistency-inspected-targets', 'time-inconsistency-count',
                      'transfer-wait-inspected-targets', 'transfer-wait-violation-count']


def _count(v): return type(v) is int and v >= 0
def _path(s): return str(s).replace('~', '~0').replace('/', '~1')


def _fields(name, metric, other):
    """Return measured typed fields. Absence inside a complete histogram means 0;
    absence of a metric, a required field, or an unavailable measurement never does.
    No affectedCells/identifiers or source contents enter the comparison.
    """
    if metric is None or metric.get('availability') != 'known': return {}
    v = metric.get('value')
    if name.endswith('Rate'):
        n, d = metric.get('numerator'), metric.get('denominator')
        if not _count(n) or not _count(d) or n > d: return {}
        if d == 0:
            return {'': (None, 'zero-denominator')} if v is None else {}
        if type(v) not in (int, float) or not math.isfinite(v) or v != n / d: return {}
        return {'': (v, 'rate')}
    if name == 'routeCoverage.v2DataState':
        return {'': (v, 'state')} if v in ('complete', 'insufficient', 'unknown') else {}
    if name == 'routeCoverage':
        if not isinstance(v, dict): return {}
        result = {k: (v.get(k), 'state' if k != 'scheduledTripCount' else 'count')
                  for k in ('dataState', 'coverageClassification', 'scheduledTripCount')}
        origin = v.get('originEvidence', {})
        if not isinstance(origin, dict): origin = {}
        result.update({'originEvidence/' + k: (origin.get(k), 'count') for k in (
            'originTripCount', 'dataInsufficientCount', 'transferDataInsufficientCount')})
        # Reason codes here are observed coverage evidence, not an unavailable value.
        result['reasonCodes'] = (tuple(sorted(metric.get('reasonCodes', []))), 'evidence')
        return result
    if name.startswith('diagnostics.'):
        if not isinstance(v, dict) or not isinstance(v.get('codes'), dict): return {}
        result = {k: (v.get(k), 'count') for k in ('codeOccurrences','affectedRowCount','affectedGeneratedRowCount')}
        other_codes = (other or {}).get('value')
        other_codes = other_codes.get('codes', {}) if isinstance(other_codes, dict) else {}
        for code in sorted(set(v['codes']) | set(other_codes)):
            entry = v['codes'].get(code)
            if entry is not None and not isinstance(entry, dict):
                entry = {'availability':'unavailable'}
            for k in ('occurrences','affectedRowCount','affectedGeneratedRowCount'):
                value = 0 if entry is None else entry.get(k)
                if entry is not None and (entry.get('availability') != 'known' or
                    (k == 'affectedGeneratedRowCount' and entry.get('affectedGeneratedRowAvailability') != 'known')):
                    value = None
                result['codes/' + _path(code) + '/' + k] = (value, 'count')
        return result
    if name.endswith('Counts'):
        if not isinstance(v, dict): return {}
        if name.endswith(('rawStatusCounts', 'observedRawStatusCounts')):
            keys = set(details.RAW_STATES)
            if set(v) != keys: return {}
        elif name.endswith('aggregatedStatusCounts'):
            keys = set(details.AGGREGATED_STATES)
            if set(v) != keys: return {}
        else:
            ov = (other or {}).get('value')
            keys = set(v) | (set(ov) if isinstance(ov, dict) else set())
        return {_path(k): (v.get(k, 0), 'count') for k in sorted(keys)}
    return {'': (v, 'count')}


def _classification(name, components):
    tags = set()
    for field in components:
        delta = field['delta']
        path = field['field']
        if delta is None or delta == 0: continue
        if name.endswith('Rate') and delta < 0: tags.add('match-rate-decreased')
        if delta > 0:
            if path == 'ambiguous': tags.add('ambiguous-increased')
            if path == 'unmatched': tags.add('unmatched-increased')
            if (name == 'diagnostics.v2Exclusions.UNKNOWN' or path == 'unknown'): tags.add('unknown-increased')
            if name in ('diagnostics.itinerary.WARNING','diagnostics.v2Exclusions.WARNING'): tags.add('warning-increased')
            if name.startswith('diagnostics.v2Validator'): tags.add('validator-error-increased')
            if name == 'trainTypeUnknownCount': tags.add('train-type-unresolved-increased')
            if name == 'destinationMissingCount': tags.add('destination-missing-increased')
    if name in ('routeCoverage', 'routeCoverage.v2DataState'):
        for f in components:
            if f['field'] in ('', 'dataState') and f['comparisonAvailability'] == 'known' and (
                f['baselineValue'] == 'complete' and f['candidateValue'] in ('insufficient', 'unknown')):
                tags.add('coverage-regressed')
    return tags


def compare_metric(name, a, b, dims, *, component_limit=1000):
    reasons = set()
    for side, metric in zip(SIDES, (a, b)):
        if metric is None: reasons.add(side + '_metric_missing_or_duplicate')
        elif metric.get('availability') != 'known':
            reasons.add(side + '_metric_not_evaluable'); reasons.update(metric.get('reasonCodes', []))
        elif metric.get('unit') != details.UNITS[name]: reasons.add('metric_definition_mismatch')
    if a is not None and b is not None:
        for key in ('definitionFingerprint', 'populationDefinition', 'denominatorDefinition', 'countingDefinition'):
            if a.get(key) != b.get(key): reasons.add('metric_definition_mismatch')
    fields = [_fields(name, m, other) for m, other in ((a,b),(b,a))]
    if not reasons and any(not f for f in fields):
        # An empty dynamic histogram is an observed empty set, not an absent metric.
        if not (name.endswith(('nativeRawStatusCounts','typeResolutionSourceCounts')) and
                all(m.get('value') == {} for m in (a,b))): reasons.add('metric_value_invalid')
    components = []
    for path in sorted(set(fields[0]) | set(fields[1])):
        av, ak = fields[0].get(path, (None, 'missing'))
        bv, bk = fields[1].get(path, (None, 'missing'))
        why = set(reasons)
        if ak == bk == 'zero-denominator' and not why:
            availability = 'not-applicable'; why.add('zero_denominator')
        else:
            valid = ak == bk and ((ak == 'count' and _count(av) and _count(bv)) or
                    (ak == 'rate') or (ak == 'state' and isinstance(av,str) and isinstance(bv,str)) or ak == 'evidence')
            if not valid: why.add('field_not_evaluable' if 'zero-denominator' not in (ak,bk) else 'zero_denominator')
            availability = 'known' if not why else 'not-evaluable'
        numeric = availability == 'known' and ak in ('rate','count')
        delta = bv-av if numeric else None
        changed = availability == 'known' and av != bv
        components.append({'field': path, 'baselineValue': av, 'candidateValue': bv, 'delta': delta,
            'comparisonAvailability': availability, 'reasonCodes': sorted(why), 'changed': changed})
    if not components and not reasons:
        availability = 'known'
    elif reasons or all(c['comparisonAvailability'] == 'not-evaluable' for c in components):
        availability = 'not-evaluable'
    elif any(c['comparisonAvailability'] == 'not-evaluable' for c in components): availability = 'partial'
    elif all(c['comparisonAvailability'] == 'not-applicable' for c in components): availability = 'not-applicable'
    else: availability = 'known'
    changed = any(c['changed'] for c in components)
    tags = _classification(name, components)
    if availability in ('not-evaluable','partial'): tags.add('not-evaluable')
    if changed: tags.add('detail-changed')
    elif availability == 'known': tags.add('unchanged')
    if name.endswith('Rate') and a is not None and b is not None and a.get('denominator') != b.get('denominator'):
        tags.add('denominator-count-changed')
    for c in components: reasons.update(c['reasonCodes'])
    held = components[:component_limit]
    scalar = name.endswith('Rate') or details.UNITS[name] in ('targets','candidate-rows','state')
    def value(key):
        return (held[0][key] if held else None) if scalar else {c['field']: c[key] for c in held}
    record = {'dimensions': dict(dims), 'metricId': name, 'baselineValue': value('baselineValue'),
        'candidateValue': value('candidateValue'), 'delta': value('delta'), 'changed': changed,
        'comparisonAvailability': availability, 'reasonCodes': sorted(reasons), 'classifications': sorted(tags),
        'componentDiffs': held, 'omittedComponentCount': len(components)-len(held),
        'numerator': {side: (m or {}).get('numerator') for side,m in zip(SIDES,(a,b))},
        'denominator': {side: (m or {}).get('denominator') for side,m in zip(SIDES,(a,b))}}
    record['sideAvailability'] = {side: (m or {}).get('availability','missing') for side,m in zip(SIDES,(a,b))}
    direction = 'unchanged' if not changed else 'state-or-mixed-change'
    if scalar and held and held[0]['delta'] is not None:
        delta = held[0]['delta']
        direction = 'candidate-increased' if delta > 0 else 'candidate-decreased' if delta < 0 else 'unchanged'
    if availability in ('not-evaluable','not-applicable'): direction = availability
    record['deltaDirection'] = direction
    return record, components


def _canonical_finding(name, indexes, cell):
    # Suppress correlated evidence only when its canonical measurement exists on both sides.
    partner = None
    for suffix in ('nativeRawStatusCounts','observedRawStatusCounts'):
        if name.endswith(suffix): partner = name[:-len(suffix)]+'rawStatusCounts'
    if name == 'routeCoverage.v2DataState': partner = 'routeCoverage'
    if name == 'diagnostics.generatorMatchStates': partner = 'matcher.generated.firstLeg.references.aggregatedStatusCounts'
    if partner is None: return True
    groups = [index.get(cell+(partner,), []) for index in indexes]
    return not all(len(g) == 1 and g[0].get('availability') == 'known' for g in groups)


def compare_details(baseline, candidate, context, *, detail_limit=1000):
    indexes = []
    for report in (baseline,candidate):
        index = defaultdict(list)
        for m in report.get('detailedMetrics', []):
            index[tuple(m['dimensions'][k] for k in DIMS)+(m['metricId'],)].append(m)
        indexes.append(index)
    cells = sorted(set(itertools.product(*(context[k] for k in ('serviceDates','stationIds','routeIds')))))
    changed_records, unevaluable_records = [], []
    inconsistency_findings, abnormal_checks = [], []
    changed_findings, unevaluable_findings = [], []
    omissions, counts, finding_counts = Counter(), Counter(), Counter()
    summaries = {}
    not_evaluated = set(TIME_NOT_EVALUATED)
    check_counts = {side: Counter() for side in SIDES}
    bad_cells = set()
    actionable_keys = set()
    for side, report in zip(SIDES, (baseline,candidate)):
        for check in sorted(report.get('detailedConsistency', []), key=lambda c: tuple(c['dimensions'][k] for k in DIMS)+(c['checkId'],)):
            check_counts[side][check['status']] += 1
            if check['status'] != 'PASS':
                item = {**copy.deepcopy(check), 'side': side}
                if len(abnormal_checks) < detail_limit: abnormal_checks.append(item)
                else: omissions['detailedConsistencyChecks'] += 1
                bad_cells.add(tuple(check['dimensions'][k] for k in DIMS))
                if check['status'] == 'FAIL':
                    counts['consistencyFailureCount'] += 1
                    if len(inconsistency_findings) < detail_limit: inconsistency_findings.append({'code':'detailed_consistency_failed', **item})
                    else: omissions['detailedFindings'] += 1
    for cell in cells:
        changed, partial = False, cell in bad_cells
        for name in sorted(details.UNITS):
            values = []
            for index in indexes:
                group = index.get(cell+(name,), [])
                values.append(group[0] if len(group) == 1 else None)
            record, components = compare_metric(name, *values, dict(zip(DIMS,cell)), component_limit=detail_limit)
            status = record['comparisonAvailability']
            counts[status+'MetricCount'] += 1
            counts['metricCount'] += 1
            counts['changedMetricCount'] += record['changed']
            if status == 'known' and not record['changed']:
                counts['unchangedMetricCount'] += 1
            changed |= record['changed']
            partial |= status in ('partial','not-evaluable')
            if status in ('partial','not-evaluable','not-applicable'):
                not_evaluated.add(name+':'+('zero-denominator' if status == 'not-applicable' else 'unavailable-fields'))
            retain_record = record['changed'] or status in ('partial','not-evaluable') or cell in bad_cells
            if retain_record:
                actionable_keys.add((cell,name))
                target = changed_records if record['changed'] else unevaluable_records
                if len(target) < detail_limit: target.append(record)
                else: omissions['detailedMetricDiffs'] += 1
                omissions['componentDiffs'] += record['omittedComponentCount']
            s = summaries.setdefault(name, {'availabilityCounts': Counter(), 'changedCellCount': 0,
                'componentTotals': {}, 'stateTransitions': {}, 'stateCellCounts':{}, 'availabilityTransitions':{}, 'baselineNumerator':0, 'candidateNumerator':0,
                'baselineDenominator':0, 'candidateDenominator':0, 'rateSupportCellCount':0, 'denominatorChangedCellCount':0})
            s['availabilityCounts'][status] += 1
            s['changedCellCount'] += record['changed']
            transition = record['sideAvailability']['baseline']+' -> '+record['sideAvailability']['candidate']
            s['availabilityTransitions'][transition] = s['availabilityTransitions'].get(transition,0)+1
            if name.endswith('Rate'):
                ns, ds = record['numerator'], record['denominator']
                if all(_count(ns[k]) and _count(ds[k]) for k in SIDES) and status in ('known','not-applicable'):
                    s['rateSupportCellCount'] += 1
                    for side in SIDES:
                        s[side+'Numerator'] += ns[side]; s[side+'Denominator'] += ds[side]
                    s['denominatorChangedCellCount'] += ds['baseline'] != ds['candidate']
            for c in components:
                key = c['field']
                if name in ('routeCoverage', 'routeCoverage.v2DataState'):
                    for side,m in zip(SIDES,values):
                        state = c[side+'Value']
                        if isinstance(state,str) and m is not None and m.get('availability') == 'known':
                            states = s['stateCellCounts'].setdefault(key, {k:{} for k in SIDES})[side]
                            states[state] = states.get(state,0)+1
                if c['comparisonAvailability'] != 'known': continue
                if c['delta'] is not None and not name.endswith('Rate'):
                    t = s['componentTotals'].setdefault(key, {'baselineValue':0,'candidateValue':0,'delta':0,'comparedCellCount':0})
                    for field in ('baselineValue','candidateValue','delta'): t[field] += c[field]
                    t['comparedCellCount'] += 1
                elif isinstance(c['baselineValue'], str):
                    t = s['stateTransitions'].setdefault(key, {})
                    pair = c['baselineValue']+' -> '+c['candidateValue']
                    t[pair] = t.get(pair,0)+1
            if _canonical_finding(name, indexes, cell) and (record['changed'] or status in ('partial','not-evaluable')):
                code = 'detailed_metric_changed' if record['changed'] else 'not-evaluable'
                finding_counts[code] += 1
                if record['changed']: counts['confirmedFindingCount'] += 1
                for tag in record['classifications']: finding_counts[tag] += 1
                # Findings are selected independently so every confirmed/unknown event
                # remains actionable even when unchanged records dominate the population.
                finding = {'code':code, **copy.deepcopy(record)}
                if record['changed']:
                    if len(changed_findings) < detail_limit: changed_findings.append(finding)
                    else: omissions['detailedFindings'] += 1
                else:
                    if len(unevaluable_findings) < detail_limit: unevaluable_findings.append(finding)
                    else: omissions['detailedFindings'] += 1
        counts['changedCellCount' if changed else 'indeterminateCellCount' if partial else 'unchangedCellCount'] += 1
        counts['partialCellCount'] += partial
    for name,s in summaries.items():
        s['availabilityCounts'] = dict(sorted(s['availabilityCounts'].items()))
        if name.endswith('Rate'):
            for side in SIDES:
                d = s[side+'Denominator']
                s[side+'Rate'] = s[side+'Numerator']/d if d else None
            s['rateDelta'] = s['candidateRate']-s['baselineRate'] if s['candidateRate'] is not None and s['baselineRate'] is not None else None
        else:
            for key in list(s):
                if key.endswith(('Numerator','Denominator')) or key in ('rateSupportCellCount','denominatorChangedCellCount'): del s[key]
    summary = {k: counts[k] for k in ('metricCount','knownMetricCount','partialMetricCount','not-evaluableMetricCount',
        'not-applicableMetricCount','changedMetricCount','confirmedFindingCount','consistencyFailureCount',
        'changedCellCount','unchangedCellCount','indeterminateCellCount','partialCellCount')}
    summary['unchangedMetricCount'] = counts['unchangedMetricCount']
    summary['aggregatedUnchangedMetricCount'] = counts['unchangedMetricCount']
    summary.update(cellCount=len(cells), metricSummaries=summaries, findingCounts=dict(sorted(finding_counts.items())),
                   consistency={side:dict(sorted(check_counts[side].items())) for side in SIDES})
    # Keep changed and unevaluable evidence first; unchanged values are represented
    # by full summary counts and are never retained as one row per cell/metric.
    detailed_findings = changed_findings[:detail_limit]
    detailed_findings += unevaluable_findings[:max(0, detail_limit-len(detailed_findings))]
    detailed_findings += inconsistency_findings[:max(0, detail_limit-len(detailed_findings))]
    omitted_findings = len(changed_findings)+len(unevaluable_findings)+len(inconsistency_findings)-len(detailed_findings)
    if omitted_findings: omissions['detailedFindings'] += omitted_findings
    detailed_records = changed_records[:detail_limit]
    detailed_records += unevaluable_records[:max(0,detail_limit-len(detailed_records))]
    omitted_records = len(changed_records)+len(unevaluable_records)-len(detailed_records)
    if omitted_records: omissions['detailedMetricDiffs'] += omitted_records
    unchanged_metric_count = counts['unchangedMetricCount']
    omitted_unchanged = max(0, unchanged_metric_count)
    return {'detailedMetricDiffs':detailed_records,
            'findings':detailed_findings, 'checks':abnormal_checks,
            'summary':summary, 'omittedDetails':{k:v for k,v in sorted(omissions.items()) if v},
            'notEvaluated':sorted(not_evaluated),
            'actionableMetricKeys':sorted(actionable_keys),
            'unchangedDetailsAggregatedCount':omitted_unchanged}
