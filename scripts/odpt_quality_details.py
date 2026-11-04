"""Private observation and descriptive quality metrics; no public gates or writes."""
from collections import Counter
import re

import odpt_public_v2 as v2
from odpt_itinerary import ItineraryGenerator as BaseGenerator
from odpt_snapshot_qa import _classify_diagnostics

RAW_STATES = ('unique_match', 'ambiguous', 'unmatched', 'unavailable', 'candidate_unconfirmed')
AGGREGATED_STATES = ('unique_match', 'ambiguous', 'unmatched', 'unavailable')
POPULATIONS = ('generated.firstLeg', 'primary.firstLeg', 'primary.secondLeg',
               'bestTransferAlternative.firstLeg', 'bestTransferAlternative.secondLeg')
MATCH_FIELDS = ('targetCount', 'rawObservedTargetCount', 'rawStatusCounts', 'nativeRawStatusCounts',
                'observedRawStatusCounts', 'aggregatedStatusCounts', 'rawMatchRate', 'aggregatedMatchRate')
UNITS = {f'matcher.{p}.{counting}.{field}': ('fraction' if field.endswith('Rate') else
          'status-counts' if field.endswith('Counts') else 'targets')
         for p in POPULATIONS for counting in ('references', 'unique') for field in MATCH_FIELDS}
UNITS.update({f'diagnostics.{system}': 'diagnostic-summary' for system in (
    'itinerary.INFO', 'itinerary.WARNING', 'generatorMatchStates', 'v2Exclusions.INFO',
    'v2Exclusions.WARNING', 'v2Exclusions.UNKNOWN', 'v2ValidatorRows', 'v2ValidatorCell')})
UNITS.update({'routeCoverage': 'coverage-evidence', 'routeCoverage.v2DataState': 'state',
    **{name: 'candidate-rows' for name in ('trainTypeConfirmedCount', 'trainTypeAuxiliaryCount',
        'trainTypeUnknownCount', 'serviceBrandOnlyCount', 'destinationConfirmedCount',
        'destinationMissingCount', 'destinationUnknownCount')}, 'typeResolutionSourceCounts': 'status-counts'})


class ObservingGenerator(BaseGenerator):
    """Opt-in collector-only subclass. BaseGenerator/matcher and DTOs stay untouched.

    The proxy delegates each real match exactly once and returns the same object.
    Only its status is observed; no ODPT record/identifier enters report evidence.
    """
    def generate(self, service_date):
        self.quality_raw_matches = {}
        return super().generate(service_date)

    def _enrich(self, trip, calendar, matcher=None, active_trip_ids=()):
        if matcher is None:
            return super()._enrich(trip, calendar, matcher, active_trip_ids)
        observations = self.quality_raw_matches
        class Observer:
            def match(self, *args, **kwargs):
                result = matcher.match(*args, **kwargs)
                observations[(trip.service_date, trip.route_id, trip.trip_id)] = result.status
                return result
        return super()._enrich(trip, calendar, Observer(), active_trip_ids)


def metric(name, dims, value=None, availability='known', reasons=(), evidence=(), numerator=None, denominator=None):
    return {'metricId': name, 'dimensions': dict(dims), 'availability': availability,
            'value': value if availability == 'known' else None, 'unit': UNITS[name],
            'numerator': numerator, 'denominator': denominator,
            'reasonCodes': sorted(set(reasons)), 'evidenceRefs': list(evidence)}


def empty_cell(dims, availability, reason):
    return [metric(name, dims, availability=availability, reasons=[reason]) for name in sorted(UNITS)]


def _counts(values, states):
    return {key: values.count(key) for key in states}


def _match_metrics(population, targets, dims, observations):
    result = []
    for counting in ('references', 'unique'):
        prefix = f'matcher.{population}.{counting}.'
        if targets is None:
            result.extend(metric(prefix + f, dims, availability='unavailable', reasons=['leg_evidence_unavailable'])
                          for f in MATCH_FIELDS)
            continue
        selected = targets
        if counting == 'unique':
            grouped = {}
            for key, status in targets:
                if key in grouped and grouped[key] != status:
                    grouped[key] = None
                else:
                    grouped[key] = status
            selected = sorted(grouped.items())
        native = [observations.get(key) for key, _ in selected]
        # MatchResult uses native "confirmed"; quality profile spells this "unique_match".
        raw = ['unique_match' if s == 'confirmed' else s for s in native]
        aggregated = [s for _, s in selected]
        observed = [s for s in raw if s in RAW_STATES]
        n = len(selected)
        full_raw = len(observed) == n
        full_aggregated = all(s in AGGREGATED_STATES for s in aggregated)
        data = {'targetCount': n, 'rawObservedTargetCount': len(observed),
                'observedRawStatusCounts': _counts(observed, RAW_STATES),
                'rawStatusCounts': _counts(observed, RAW_STATES),
                'nativeRawStatusCounts': dict(sorted(Counter(s for s in native if isinstance(s, str)).items())),
                'aggregatedStatusCounts': _counts(aggregated, AGGREGATED_STATES)}
        for field, value in data.items():
            full = full_raw if field in {'rawStatusCounts', 'nativeRawStatusCounts'} else (
                   full_aggregated if field == 'aggregatedStatusCounts' else True)
            result.append(metric(prefix + field, dims, value, availability='known' if full else 'unavailable',
                reasons=[] if full else ['aggregate_status_unavailable' if field == 'aggregatedStatusCounts' else 'raw_match_not_observed'],
                evidence=['matcher.match.status', 'generator._enrich']))
        for field, statuses, full in (('rawMatchRate', raw, full_raw), ('aggregatedMatchRate', aggregated, full_aggregated)):
            numerator = statuses.count('unique_match') if full else None
            result.append(metric(prefix + field, dims, numerator / n if full and n else None,
                availability='known' if full else 'unavailable', numerator=numerator, denominator=n,
                reasons=(['zero_denominator'] if n == 0 else []) if full else ['match_evidence_incomplete'],
                evidence=['matcher.match.status', 'generator._enrich']))
    return result


def _summary(events, dims=None, affected_generated=True):
    """events: (generated/candidate row index, code); preserve repeated code occurrences."""
    codes = sorted({code for _, code in events})
    generated_known = affected_generated or not events
    return {'codeOccurrences': len(events), 'affectedRowCount': len({i for i, _ in events}),
            'affectedGeneratedRowCount': len({i for i, _ in events}) if generated_known else None,
            'codes': {code: {'occurrences': sum(c == code for _, c in events),
                             'affectedRowCount': len({i for i, c in events if c == code}),
                             'affectedGeneratedRowCount': len({i for i, c in events if c == code}) if affected_generated else None,
                             'affectedGeneratedRowAvailability': 'known' if affected_generated else 'unavailable',
                             'availability': 'known', 'reasonCodes': [] if affected_generated else ['affected_generated_rows_not_resolved'],
                             'affectedCells': [dict(dims)] if dims else []} for code in codes}}


def coverage(generator, day, all_rows, dims):
    route = dims['routeId']
    routes = getattr(generator, 'last_destination_status', {}).get('routes', {})
    evidence = routes.get(route) if isinstance(routes, dict) else None
    state = v2._route_state(route, evidence, all_rows)
    metrics = [metric('routeCoverage.v2DataState', dims, state['dataState'], evidence=['v2._route_state'])]
    fields = ('scheduledTripCount', 'originTripCount', 'dataInsufficientCount', 'transferDataInsufficientCount')
    if not isinstance(evidence, dict) or any(not v2._safe_nonnegative_int(evidence.get(f)) for f in fields):
        metrics.append(metric('routeCoverage', dims, availability='unavailable',
                              reasons=['route_metrics_unavailable'], evidence=['generator.last_destination_status']))
        return metrics
    rows = [r for r in all_rows if str(r.route_id) == route]
    reasons = []
    if evidence['dataInsufficientCount']: reasons.append('origin_data_insufficient')
    if evidence['transferDataInsufficientCount']: reasons.append('transfer_data_insufficient')
    if evidence['originTripCount'] != len(rows): reasons.append('origin_row_count_mismatch')
    if any(_classify_diagnostics(r)['WARNING'] for r in rows): reasons.append('itinerary_warning')
    if any(r.odpt.status not in {'matched', 'unique_match'} for r in rows): reasons.append('matcher_unresolved')
    classification = state['dataState']
    if evidence['scheduledTripCount'] == 0:
        try:
            active = generator.active_service_ids(day)
            classification = 'no-active-service' if not active else 'no-scheduled-route-service'
        except Exception:
            classification = 'unknown'; reasons.append('service_calendar_evidence_unavailable')
    elif reasons:
        classification = 'data-insufficient'
    elif not rows:
        classification = 'no-origin-direction-candidates'
    return metrics + [metric('routeCoverage', dims, {
        'routeId': route, 'dataState': state['dataState'], 'scheduledTripCount': evidence['scheduledTripCount'],
        'originEvidence': {f: evidence[f] for f in fields[1:]},
        'coverageClassification': classification}, reasons=reasons,
        evidence=['generator.last_destination_status.routes', 'v2._route_state', 'generator.active_service_ids'])]


def _payload(rows, all_coverage, dims):
    # A fixed validator-only envelope, never a public artifact or real run timestamp.
    return {'schemaVersion': 2, 'dataScope': 'public-display-v2', 'generatedAt': '2000-01-01T00:00:00Z',
            'timezone': 'Asia/Tokyo', 'applicationPeriod': None, 'stationId': dims['stationId'],
            'originStationId': 'Ikebukuro', 'serviceDays': [{'serviceDate': dims['serviceDate'],
            'routeCoverage': all_coverage, 'departures': rows}]}


def _validator_error(rows, all_coverage, dims):
    try:
        v2.validate_v2_payload(_payload(rows, all_coverage, dims))
        return None
    except v2.V2Error as exc:
        # Keep stable error identities, not per-row position-dependent field paths.
        return re.sub(r'service_day_\d+', 'service_day', re.sub(r'departure_\d+', 'departure', exc.code))


def measure_cell(rows, all_rows, dims, generator, day):
    """Detailed cell metrics. Failures are scoped to the affected family."""
    observations = getattr(generator, 'quality_raw_matches', {})
    populations = {p: [] for p in POPULATIONS}
    result = []
    info, warning, match_events = [], [], []
    excluded = {s: [] for s in ('INFO', 'WARNING', 'UNKNOWN')}
    public, candidate_results = [], []
    projection_ok = True
    for i, row in enumerate(rows):
        try:
            key = (dims['serviceDate'], str(row.route_id), row.origin_trip_id)
            populations['generated.firstLeg'].append((key, row.odpt.status))
            match_events.append((i, row.odpt.status))
        except AttributeError:
            populations['generated.firstLeg'] = None
        for severity, events in (('INFO', info), ('WARNING', warning)):
            classified = _classify_diagnostics(row)[severity]
            events.extend((i, code) for code in row.data_quality if code in classified)
        projected = None
        try:
            projected = v2._public_departure(row)
            if projected is None:
                code, severity = v2._exclusion_detail(row)
                excluded[severity].append((i, code))
            else:
                projected['id'] = v2.public_id(dims['stationId'], dims['serviceDate'], projected)
                public.append(projected); candidate_results.append(row)
        except Exception:
            projection_ok = False
        # Primary legs cover C only; alternatives cover G and are never pooled with primary.
        for scope, itinerary in (('primary', row.primary_itinerary if projection_ok and projected is not None else None),
                                 ('bestTransferAlternative', row.best_transfer_alternative)):
            if itinerary is None: continue
            for leg_id in ('firstLeg', 'secondLeg'):
                population = scope + '.' + leg_id
                if leg_id == 'secondLeg' and itinerary.kind != 'transfer': continue
                try:
                    trip = getattr(itinerary, 'first_leg' if leg_id == 'firstLeg' else 'second_leg').trip
                    target = ((trip.service_date, str(trip.route_id), trip.trip_id), trip.odpt.status)
                    if populations[population] is not None: populations[population].append(target)
                except AttributeError:
                    populations[population] = None
    if not projection_ok:
        for p in ('primary.firstLeg', 'primary.secondLeg'): populations[p] = None
    for p in POPULATIONS:
        result.extend(_match_metrics(p, populations[p], dims, observations))
    result.extend(metric('diagnostics.itinerary.' + severity, dims, _summary(events, dims),
                         evidence=['generator.data_quality', 'snapshot_qa._classify_diagnostics'])
                  for severity, events in (('INFO', info), ('WARNING', warning)))
    result.append(metric('diagnostics.generatorMatchStates', dims, _summary(match_events, dims),
                         availability='known' if populations['generated.firstLeg'] is not None else 'unavailable',
                         reasons=[] if populations['generated.firstLeg'] is not None else ['aggregate_status_unavailable']))
    result.extend(metric('diagnostics.v2Exclusions.' + s, dims, _summary(excluded[s], dims),
                         availability='known' if projection_ok else 'unavailable',
                         reasons=[] if projection_ok else ['v2_projection_incomplete'], evidence=['v2._exclusion_detail'])
                  for s in ('INFO', 'WARNING', 'UNKNOWN'))
    result.extend(coverage(generator, day, all_rows, dims))
    routes = getattr(generator, 'last_destination_status', {}).get('routes', {})
    all_coverage = {r: v2._route_state(r, routes.get(r), all_rows) for r in v2.ROUTES}
    for name, batches in (('v2ValidatorRows', [[r] for r in public]), ('v2ValidatorCell', [public])):
        events = [(i, error) for i, batch in enumerate(batches)
                  if (error := _validator_error(batch, all_coverage, dims)) is not None] if projection_ok else []
        result.append(metric('diagnostics.' + name, dims, _summary(events, dims, name != 'v2ValidatorCell'),
            availability='known' if projection_ok else 'unavailable',
            reasons=['fail_fast_per_probe'] if projection_ok else ['v2_projection_incomplete'],
            evidence=['v2.validate_v2_payload']))
    result.extend(display_quality(candidate_results if projection_ok else None, dims))
    return result


def display_quality(rows, dims):
    fields = ('trainTypeConfirmedCount', 'trainTypeAuxiliaryCount', 'trainTypeUnknownCount',
              'serviceBrandOnlyCount', 'typeResolutionSourceCounts', 'destinationConfirmedCount',
              'destinationMissingCount', 'destinationUnknownCount')
    if rows is None:
        return [metric(f, dims, availability='unavailable', reasons=['v2_projection_incomplete']) for f in fields]
    types = Counter(); heads = Counter(); sources = Counter(); brand_only = 0
    type_known = destination_known = True
    for row in rows:
        t = row.type_resolution
        try:
            sources[t.source] += 1
            if t.source == 'gtfs_stop_pattern': types['auxiliary'] += 1
            elif t.source == 'unknown' or t.label == '種別不明' or t.train_type is None:
                types['unknown'] += 1
            elif t.source in {'odpt_confirmed', 'official_route_rule'}: types['confirmed'] += 1
            else: type_known = False
            brand_only += t.train_type is None and t.service_brand is not None
        except AttributeError:
            type_known = False
        try:
            if row.headsign is None or (isinstance(row.headsign, str) and not row.headsign.strip()): heads['missing'] += 1
            elif not isinstance(row.headsign, str): destination_known = False
            elif row.odpt.status == 'unique_match' and row.odpt.destination: heads['confirmed'] += 1
            else: heads['unknown'] += 1
        except AttributeError:
            destination_known = False
    values = {'trainTypeConfirmedCount': types['confirmed'], 'trainTypeAuxiliaryCount': types['auxiliary'],
        'trainTypeUnknownCount': types['unknown'], 'serviceBrandOnlyCount': brand_only,
        'typeResolutionSourceCounts': dict(sorted(sources.items())), 'destinationConfirmedCount': heads['confirmed'],
        'destinationMissingCount': heads['missing'], 'destinationUnknownCount': heads['unknown']}
    return [metric(f, dims, values[f], availability='known' if (destination_known if f.startswith('destination') else type_known) else 'unavailable',
                   reasons=[] if (destination_known if f.startswith('destination') else type_known) else ['display_provenance_unavailable'],
                   evidence=['generator.type_resolution', 'generator.headsign', 'generator.odpt.destination']) for f in fields]


def checks(metrics):
    by_id = {m['metricId']: m for m in metrics}
    dims = metrics[0]['dimensions']; result = []
    def check(code, names, predicate):
        available = all(by_id[n]['availability'] == 'known' for n in names)
        result.append({'checkId': code, 'dimensions': dict(dims), 'status':
                       ('PASS' if predicate([by_id[n] for n in names]) else 'FAIL') if available else 'not-evaluated'})
    for family, names in (
        ('train_type_partition', ['trainTypeConfirmedCount','trainTypeAuxiliaryCount','trainTypeUnknownCount']),
        ('destination_partition', ['destinationConfirmedCount','destinationMissingCount','destinationUnknownCount'])):
        check(family, ['C']+names, lambda m: m[0]['value'] == sum(x['value'] for x in m[1:]))
    for p in POPULATIONS:
        for counting in ('references', 'unique'):
            prefix = f'matcher.{p}.{counting}.'
            for field in ('rawStatusCounts', 'nativeRawStatusCounts', 'aggregatedStatusCounts'):
                check(prefix+field+'_equals_targets', [prefix+field,prefix+'targetCount'],
                      lambda m: sum(m[0]['value'].values()) == m[1]['value'])
            check(prefix+'observed_counts_equal_observed_targets', [prefix+'observedRawStatusCounts',prefix+'rawObservedTargetCount'],
                  lambda m: sum(m[0]['value'].values()) == m[1]['value'])
            check(prefix+'observed_not_above_targets', [prefix+'rawObservedTargetCount',prefix+'targetCount'],
                  lambda m: m[0]['value'] <= m[1]['value'])
            for field in ('rawMatchRate','aggregatedMatchRate'):
                check(prefix+field+'_fraction', [prefix+field], lambda m:
                      0 <= m[0]['numerator'] <= m[0]['denominator'] and m[0]['value'] ==
                      (m[0]['numerator']/m[0]['denominator'] if m[0]['denominator'] else None))
        check(f'matcher.{p}.unique_not_above_references',
              [f'matcher.{p}.unique.targetCount',f'matcher.{p}.references.targetCount'],
              lambda m: m[0]['value'] <= m[1]['value'])
    return result
