"""Board-observable state evidence only; no selection, rendering or publication gate."""
from collections import Counter
from datetime import datetime, timedelta, timezone

if __package__:
    from . import odpt_quality_input as quality
else:
    import odpt_quality_input as quality

ROUTE_STATES = frozenset(('running', 'not_started', 'ended', 'no_candidates', 'unknown',
                         'data_insufficient', 'start_unconfirmed', 'terminal_unconfirmed'))
# The adapter aggregates data_insufficient into unknown, never a serviceState of its own.
SERVICE_STATES = ROUTE_STATES - {'data_insufficient'}
ROUTE_FEATURES = ('routeState', 'routeCandidates', 'coverageState', 'terminalKnown',
                  'startGuidance', 'terminalGuidance', 'unknownSuppression')
CELL_FEATURES = ('serviceState', 'dateBoundary')
CLASSIFICATIONS = dict(routeState='route-state-changed', routeCandidates='route-candidates-changed',
    coverageState='coverage-state-changed', serviceState='service-state-changed',
    startGuidance='start-guidance-changed', terminalGuidance='terminal-guidance-changed',
    unknownSuppression='unknown-suppression-changed', dateBoundary='date-boundary-changed')


def known(value):
    return dict(value=value, availability='known', reasonCodes=[])


def unavailable(reason, value=None):
    return dict(value=value, availability='not-evaluable', reasonCodes=[reason])


def is_count(v):
    return type(v) is int and 0 <= v <= 2**53-1


def jst_date(epoch):
    return (datetime.fromtimestamp(epoch / 1000, timezone.utc) + timedelta(hours=9)).date().isoformat()


def compact_board(board, dates, scenario, semantic_item):
    """Keep missing/unknown fields local. Never fill a missing route with no_candidates.

    routeCoverage.dataState and WARNING are not exposed by the board. Coverage evidence
    deliberately contains only adapter-observed eligibility/count/insufficient state.
    QA counts on each route are the adapter's station x serviceDate propagation.
    """
    routes = board.get('routeStates', {})
    if not isinstance(routes, dict):
        routes = {}
    result = {'routes': {}, 'checks': [], 'auditEvidence': {}, 'unexpectedRoutes': sorted(set(routes)-{
        d+'|'+r for d in dates for r in ('6', '9')})}
    items = board['items']
    visible_ids = {i['id'] for g in board['groups'] for i in g['items']}
    missing_dates = board.get('missingServiceDates')
    envelope_known = missing_dates == [] and board.get('serviceDate') == dates[1]
    service = board.get('serviceState')
    service_valid = isinstance(service, str) and service in SERVICE_STATES
    result['serviceState'] = (known(service) if envelope_known and service_valid
        else unavailable('service-state-or-envelope-unavailable', service))
    mappings = sorted((dict(serviceDate=i['serviceDate'], routeId=i['routeId'],
        departureAtMs=i['departureAtMs'], departureJstDate=jst_date(i['departureAtMs'])) for i in items),
        key=quality.canonical)
    actual_dates = sorted({s.get('serviceDate') for s in routes.values()
                           if isinstance(s, dict) and isinstance(s.get('serviceDate'), str)})
    boundary = dict(observationJstDate=dates[1], boardServiceDate=board.get('serviceDate'),
        requiredServiceDates=list(dates), observedServiceDates=actual_dates,
        missingServiceDates=missing_dates, candidateDepartures=mappings)
    result['dateBoundary'] = (known(boundary) if envelope_known and actual_dates == list(dates)
        else unavailable('three-day-envelope-incomplete', boundary))
    for day in dates:
        for route in ('6', '9'):
            address = day+'|'+route
            raw = routes.get(address)
            if (not isinstance(raw, dict) or raw.get('serviceDate') != day
                    or raw.get('routeId') != route or day in (missing_dates or [])):
                result['routes'][address] = {f: unavailable('route-date-missing') for f in ROUTE_FEATURES}
                continue
            state = raw.get('state')
            state_valid = isinstance(state, str) and state in ROUTE_STATES
            entry = {'routeState': known(state) if state_valid else unavailable('unknown-route-state-value', state)}
            candidates = raw.get('candidateCount')
            eligible, scheduled = raw.get('candidateEligible'), raw.get('scheduledTripCount')
            coverage_valid = type(eligible) is bool and is_count(scheduled)
            counts_valid = is_count(candidates)
            entry['routeCandidates'] = (known(dict(candidateCount=candidates, hasCandidates=candidates > 0))
                if counts_valid else unavailable('route-candidate-count-missing'))
            coverage = dict(candidateEligible=eligible, scheduledTripCount=scheduled,
                            dataInsufficient=state == 'data_insufficient')
            entry['coverageState'] = known(coverage) if coverage_valid and state_valid else unavailable('coverage-evidence-missing', coverage)
            terminal = raw.get('terminalKnown')
            entry['terminalKnown'] = known(terminal) if type(terminal) is bool else unavailable('terminal-known-missing', terminal)
            entry['startGuidance'] = (known(state if state in {'not_started', 'start_unconfirmed'} else None)
                if state_valid else unavailable('start-state-unavailable', state))
            nv, other = raw.get('noValidArrivalCount'), raw.get('otherUnknownCount')
            qa_valid = is_count(nv) and is_count(other)
            if qa_valid and coverage_valid and state_valid:
                has_unknown = nv + other > 0
                suppression = dict(noValidArrivalCount=nv, otherUnknownCount=other,
                    hasUnknown=has_unknown, startUnconfirmed=has_unknown and state == 'start_unconfirmed',
                    terminalUnconfirmed=has_unknown and state == 'terminal_unconfirmed',
                    coverageUnconfirmed=not eligible)
                entry['unknownSuppression'] = known(suppression)
            else:
                entry['unknownSuppression'] = unavailable('qa-state-or-coverage-evidence-missing',
                    dict(noValidArrivalCount=nv, otherUnknownCount=other))
            selected = [i for i in items if i['serviceDate'] == day and i['routeId'] == route]
            flags_valid = all(type(i.get('isLastDeparture')) is bool and
                i.get('terminalBasis') == ('direct_only' if scenario['directOnly'] else 'all_reachable') for i in selected)
            terminal_cards = []
            if flags_valid:
                for item in selected:
                    if item['isLastDeparture']:
                        terminal_cards.append(dict(content=semantic_item(item), terminalBasis=item['terminalBasis'],
                            label='直通終電' if item['terminalBasis'] == 'direct_only' else '終電',
                            inGroups=item['id'] in visible_ids))
            guidance = dict(state=state if state_valid and state in {'ended', 'terminal_unconfirmed'} else None,
                terminalCandidates=sorted(terminal_cards, key=quality.canonical),
                terminalCandidateCount=len(terminal_cards),
                visibleTerminalCount=sum(c['inGroups'] for c in terminal_cards),
                hiddenByCardLimitCount=sum(not c['inGroups'] for c in terminal_cards))
            entry['terminalGuidance'] = (known(guidance) if state_valid and flags_valid
                else unavailable('terminal-guidance-fields-missing', guidance))
            result['routes'][address] = entry
            # Evidence consistency is independent of confirmed cross-Snapshot changes.
            def check(code, condition):
                result['checks'].append(dict(code=code, routeDate=address, status='PASS' if condition else 'inconsistency'))
            if qa_valid and type(terminal) is bool:
                check('unknown-terminal-certainty', not (nv + other > 0 and terminal))
            if coverage_valid and counts_valid and qa_valid and type(terminal) is bool:
                check('terminal-certainty-evidence', terminal == (eligible and candidates > 0 and nv + other == 0))
            if counts_valid:
                check('selected-within-route-candidates', len(selected) <= candidates)
            if flags_valid and type(terminal) is bool:
                check('terminal-card-certainty', not terminal_cards or terminal)
                check('single-terminal-candidate', len(terminal_cards) <= 1)
    for day in dates:
        a, b = (result['routes'][day+'|'+r]['unknownSuppression'] for r in ('6', '9'))
        if a['availability'] == b['availability'] == 'known':
            result['checks'].append(dict(code='station-date-unknown-propagation', routeDate=day,
                status='PASS' if all(a['value'][f] == b['value'][f] for f in ('noValidArrivalCount', 'otherUnknownCount')) else 'inconsistency'))
    result['auditEvidence'] = {f: board.get(f) for f in ('infoCount', 'noValidArrivalCount', 'otherUnknownCount')}
    if envelope_known and all(is_count(board.get(f)) for f in result['auditEvidence']):
        for route in ('6', '9'):
            audit = result['routes'][dates[1]+'|'+route]['unknownSuppression']
            if audit['availability'] == 'known':
                result['checks'].append(dict(code='today-qa-counts-binding', routeDate=dates[1]+'|'+route,
                    status='PASS' if all(board[f] == audit['value'][f] for f in ('noValidArrivalCount', 'otherUnknownCount')) else 'inconsistency'))
    if service_valid and envelope_known:
        today_states = [result['routes'][dates[1]+'|'+r]['routeState'] for r in ('6', '9')]
        if items:
            result['checks'].append(dict(code='service-state-items-running', routeDate=None,
                status='PASS' if service == 'running' else 'inconsistency'))
        elif all(s['availability'] == 'known' for s in today_states):
            states = [s['value'] for s in today_states]
            # Validate the observed aggregation; never use this to fill missing serviceState.
            expected = ('unknown' if any(s in {'unknown', 'data_insufficient'} for s in states)
                else 'terminal_unconfirmed' if 'terminal_unconfirmed' in states
                else 'start_unconfirmed' if 'start_unconfirmed' in states
                else 'ended' if all(s == 'ended' for s in states)
                else 'no_candidates' if all(s == 'no_candidates' for s in states) else 'not_started')
            result['checks'].append(dict(code='service-state-today-aggregation', routeDate=None,
                status='PASS' if service == expected else 'inconsistency'))
    return result


def compare_states(a, b, expected, budget):
    """All cells/features are counted before bounded actionable evidence retention."""
    counts, features, classes, transitions = Counter(), {}, Counter(), Counter()
    records, findings, state_transitions, checks = [], [], [], []
    changed_keys, unknown_keys, inconsistent_keys = set(), set(), set()
    for key in sorted(expected):
        dims = dict(zip(('observationInstant', 'stationId', 'scenarioId'), key))
        sides = [index.get(key, {}).get('stateEvidence') for index in (a, b)]
        tags, reasons = set(), set()
        changed = unevaluated = False
        for side, evidence in zip(('baseline', 'candidate'), sides):
            if evidence is None:
                continue
            for address in evidence['unexpectedRoutes']:
                unevaluated = True
                reasons.add(side+'-unexpected-route-date')
            for check in evidence['checks']:
                counts['checkCount'] += 1
                if check['status'] == 'inconsistency':
                    inconsistent_keys.add(key)
                    counts['inconsistencyCount'] += 1
                    retained = budget.retain('stateChecks', dict(dimensions=dims, side=side, **check))
                    if retained is not None: checks.append(retained)
        dates = quality_dates(key[0])
        addresses = [(None, f) for f in CELL_FEATURES] + [
            (d+'|'+r, f) for d in dates for r in ('6', '9') for f in ROUTE_FEATURES]
        for address, feature in addresses:
            pair = [(e.get(feature) if address is None else e['routes'].get(address, {}).get(feature))
                    if e is not None else None for e in sides]
            valid = all(v is not None and v['availability'] == 'known' for v in pair)
            values = [v['value'] if v is not None else None for v in pair]
            feature_counts = features.setdefault(feature, Counter())
            feature_counts['comparisonCount'] += 1
            status = 'changed' if valid and values[0] != values[1] else 'unchanged' if valid else 'not-evaluable'
            feature_counts[status] += 1
            rdims = dict(dims)
            if address is not None: rdims.update(serviceDate=address.split('|')[0], routeId=address.split('|')[1])
            evidence = dict(dimensions=rdims, feature=feature, baselineValue=values[0], candidateValue=values[1],
                comparisonAvailability='known' if valid else 'not-evaluable', changed=status == 'changed', reasonCodes=[])
            if feature in {'routeState', 'terminalKnown', 'serviceState'} and valid:
                transition = quality.canonical(values).decode('utf-8')
                transitions[(feature, transition)] += 1
                if status == 'changed':
                    retained = budget.retain('stateTransitions', dict(evidence, transition=values))
                    if retained is not None: state_transitions.append(retained)
            if status == 'unchanged':
                continue
            if status == 'changed':
                changed = True
                tags.add(('terminal-certainty-lost' if values == [True, False] else 'terminal-certainty-gained')
                         if feature == 'terminalKnown' else CLASSIFICATIONS[feature])
            else:
                unevaluated = True
                evidence['reasonCodes'] = sorted({side+'-'+reason for side, v in zip(('baseline', 'candidate'), pair)
                    for reason in (v['reasonCodes'] if v is not None else ['state-evidence-missing'])})
                reasons.update(evidence['reasonCodes'])
            retained = budget.retain('stateDiffs', evidence)
            if retained is not None: records.append(retained)
        if key in inconsistent_keys: tags.add('inconsistency')
        if unevaluated:
            tags.add('not-evaluable'); unknown_keys.add(key)
        if changed: changed_keys.add(key)
        counts['cellCount'] += 1
        counts['changedCellCount' if changed else 'notEvaluableOnlyCellCount' if unevaluated
               else 'inconsistentOnlyCellCount' if key in inconsistent_keys else 'unchangedCellCount'] += 1
        classes.update(tags)
        if tags:
            finding = dict(code='display-state-cell-changed' if changed else 'not-evaluable' if unevaluated else 'inconsistency',
                dimensions=dims, classifications=sorted(tags), reasonCodes=sorted(reasons), confirmedDifference=changed,
                qualityImpact='not-assessed')
            retained = budget.retain('stateFindings', finding)
            if retained is not None: findings.append(retained)
    summary = {k: counts[k] for k in ('cellCount', 'changedCellCount', 'unchangedCellCount', 'checkCount', 'inconsistencyCount')}
    summary.update(notEvaluableCellCount=len(unknown_keys), inconsistentCellCount=len(inconsistent_keys),
        confirmedFindingCount=len(changed_keys), classificationCounts=dict(sorted(classes.items())),
        featureCounts={f: {k: c[k] for k in ('comparisonCount', 'changed', 'unchanged', 'not-evaluable')}
                       for f, c in sorted(features.items())},
        transitionCounts=[dict(feature=f, transition=quality.loads(t), count=n)
                          for (f, t), n in sorted(transitions.items())])
    return dict(stateDiffs=records, stateFindings=findings, stateTransitions=state_transitions,
        stateChecks=checks, stateSummary=summary), changed_keys, unknown_keys, inconsistent_keys


def quality_dates(instant):
    day = (datetime.strptime(instant, '%Y-%m-%dT%H:%M:%SZ') + timedelta(hours=9)).date()
    return [(day + timedelta(days=n)).isoformat() for n in (-1, 0, 1)]
