#!/usr/bin/env python3
"""Private read-only single-Snapshot display collection; no artifacts are written."""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import re
import selectors
import shutil
import subprocess
import sys
import time

# Existing generator/projector use script-local imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))
if __package__:
    from . import odpt_quality_input as quality
    from . import odpt_quality_metrics as itinerary_metrics
    from . import odpt_display_context as display
else:
    import odpt_quality_input as quality
    import odpt_quality_metrics as itinerary_metrics
    import odpt_display_context as display
import odpt_public_v2 as v2
from odpt_itinerary import ItineraryGenerator
from prepare_odpt_v2_qa import _qa_state, PrepareError

DEFAULT_INSTANTS = ('2026-10-29T03:00:00Z',)  # Explicit JST noon, never today's date.
DEFAULT_DETAIL_LIMIT = 1000
MAX_DETAIL_LIMIT = 10000
REQUEST_LIMIT = 8 * 1024 * 1024
RESPONSE_LIMIT = 32 * 1024 * 1024
STDERR_LIMIT = 4096
NOT_EVALUATED = ['dom-presentation', 'visual-quality', 'browser-runtime', 'display-model-diff',
                 'freshness', 'application-period', 'publication-eligibility', 'public-pipeline-gate',
                 'cross-service-date-transfer-search']
STATES = {'running', 'not_started', 'ended', 'no_candidates', 'unknown', 'data_insufficient',
          'start_unconfirmed', 'terminal_unconfirmed'}
RESPONSE_FIELDS = set('contract schemaVersion status contextFingerprint observationInstant displayScenarioId nodeRuntime board validationStatus reasonCodes missingFields candidateCount cardCount bestInGroups displayedBestMarkCount itemContentKeys terminalKnownByRouteDate unknownRouteStateCount boardDigest notEvaluated'.split())


class DisplayCollectionError(ValueError):
    def __init__(self, code, availability='unavailable'):
        self.code, self.availability = code, availability
        super().__init__(code)


def _fail(code, availability='unavailable'):
    raise DisplayCollectionError(code, availability)


def _count(v):
    return type(v) is int and 0 <= v <= 2**53-1


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _js_digest(value):
    # JSON.stringify writes integral JS numbers without a .0 suffix.
    def normalized(v):
        if isinstance(v, dict): return {k: normalized(x) for k, x in v.items()}
        if isinstance(v, list): return [normalized(x) for x in v]
        if isinstance(v, float):
            if not math.isfinite(v): _fail('node_response_number_invalid')
            return int(v) if v.is_integer() else v
        return v
    return hashlib.sha256(_json_bytes(normalized(value))).hexdigest()


def _run_node(request, *, root=quality.ROOT, timeout=20):
    """Bound all three pipes in memory, including a child producing endless output."""
    raw = _json_bytes(request)
    if len(raw) > REQUEST_LIMIT: _fail('node_request_size_limit')
    node = shutil.which('node')
    if not node: _fail('node_runtime_unavailable')
    try:
        process = subprocess.Popen([node, str(Path(root)/'scripts/odpt_display_runner.mjs')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError: _fail('node_subprocess_failed')
    out, err, sent = bytearray(), bytearray(), 0
    deadline = time.monotonic()+timeout
    try:
        with selectors.DefaultSelector() as selector:
            for pipe, events, role in ((process.stdin, selectors.EVENT_WRITE, 'input'),
                                      (process.stdout, selectors.EVENT_READ, 'output'),
                                      (process.stderr, selectors.EVENT_READ, 'error')):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, events, role)
            while selector.get_map():
                remaining = deadline-time.monotonic()
                if remaining <= 0: _fail('node_timeout')
                for key, _ in selector.select(min(remaining, .2)):
                    pipe = key.fileobj
                    if key.data == 'input':
                        try: sent += os.write(pipe.fileno(), raw[sent:sent+65536])
                        except BrokenPipeError: sent = len(raw)
                        if sent == len(raw): selector.unregister(pipe); pipe.close()
                    else:
                        chunk = os.read(pipe.fileno(), 65536)
                        if not chunk: selector.unregister(pipe); pipe.close(); continue
                        target, limit = (out, RESPONSE_LIMIT) if key.data == 'output' else (err, STDERR_LIMIT)
                        if len(target)+len(chunk) > limit: _fail('node_response_size_limit')
                        target.extend(chunk)
        try: code = process.wait(timeout=max(.001, deadline-time.monotonic()))
        except subprocess.TimeoutExpired: _fail('node_timeout')
    except DisplayCollectionError:
        raise
    except (OSError, ValueError):
        _fail('node_subprocess_failed')
    finally:
        if process.poll() is None: process.kill()
        process.wait()
        for pipe in (process.stdin, process.stdout, process.stderr):
            if not pipe.closed: pipe.close()
    try:
        response = quality.loads(bytes(out).decode('utf-8'))
        stderr = bytes(err).decode('ascii').strip()
    except (UnicodeError, quality.QualityInputError): _fail('node_response_json_invalid')
    if code != 0:
        reasons = response.get('reasonCodes') if isinstance(response, dict) else None
        if not isinstance(response, dict) or code != 2 or set(response) != {'contract','schemaVersion','status','reasonCodes'} or response['contract'] != 'odpt-display-adapter-response' or response['schemaVersion'] != 1 or response['status'] != 'failed' or not isinstance(reasons, list) or len(reasons) != 1 or stderr != reasons[0] or not re.fullmatch('[a-z][a-z0-9_]*', stderr):
            _fail('node_exit_protocol_invalid')
        _fail('node_runner_'+stderr)
    if stderr: _fail('node_unexpected_stderr')
    return response, {'exitCode': code, 'stderrCode': None, 'requestBytes': len(raw), 'responseBytes': len(out)}


def _validate_response_impl(response, request):
    """Cross-check protocol/board evidence without choosing candidates a second time."""
    if not isinstance(response, dict) or set(response) != RESPONSE_FIELDS: _fail('node_response_schema_invalid')
    if (response['contract'] != 'odpt-display-adapter-response' or type(response['schemaVersion']) is not int
        or response['schemaVersion'] != 1 or response['status'] != 'ok' or response['validationStatus'] != 'validated'
        or response['reasonCodes'] != [] or response['missingFields'] != []
        or response['contextFingerprint'] != request['displayContext']['contextFingerprint']
        or response['observationInstant'] != request['observationInstant']
        or response['displayScenarioId'] != request['displayScenario']['id']
        or response['nodeRuntime'] != request['expectedNodeRuntime']
        or response['notEvaluated'] != ['dom-presentation','visual-quality','publication-eligibility','source-snapshot-binding','candidate-byte-integrity']): _fail('node_response_reference_mismatch')
    board = response['board']
    fields = set('items groups routeStates serviceState status missingServiceDates applicationPeriod generatedAt bestId serviceDate noValidArrival noValidArrivalCount otherUnknownCount infoCount candidateComparisonPartial'.split())
    if not isinstance(board, dict) or set(board) != fields: _fail('node_board_schema_invalid')
    items, groups = board['items'], board['groups']
    if not isinstance(items, list) or not isinstance(groups, list) or not isinstance(board['routeStates'], dict): _fail('node_board_schema_invalid')
    ds = request['displayContext']['requiredServiceDates'][request['observationInstant']]
    if board['serviceDate'] != ds[1] or board['missingServiceDates'] != [] or board['serviceState'] not in STATES or board['applicationPeriod'] is not None or board['generatedAt'] != request['payload']['generatedAt']:
        _fail('node_board_reference_mismatch')
    if (type(board['noValidArrival']) is not bool or type(board['candidateComparisonPartial']) is not bool
        or any(not _count(board[k]) for k in ('noValidArrivalCount','otherUnknownCount','infoCount'))): _fail('node_board_schema_invalid')
    index = {}
    allowed = {(d['serviceDate'], r['id']) for d in request['payload']['serviceDays'] for r in d['departures']}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or (item.get('serviceDate'), item['id']) not in allowed or item['id'] in index or item.get('sourceId') != item['id'] or type(item.get('isBest')) is not bool or type(item.get('isLastDeparture')) is not bool or item.get('routeId') not in ('6','9') or item.get('journeyKind') not in ('direct','transfer'):
            _fail('node_board_item_invalid')
        index[item['id']] = item
    visible = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get('items'), list): _fail('node_board_group_invalid')
        for item in group['items']:
            if not isinstance(item, dict) or index.get(item.get('id')) != item: _fail('node_board_group_invalid')
            visible.append(item)
    scenario = request['displayScenario']
    expected = ([items[:6]] if items else []) if scenario['mode'] == 'departure' else [x for r in ('6','9') if (x := [i for i in items if i['routeId'] == r][:3])]
    if [g['items'] for g in groups] != expected: _fail('node_board_card_limit_inconsistent')
    best = [i for i in items if i['isBest']]
    if board['bestId'] is None:
        if items or best: _fail('node_board_best_inconsistent')
    elif len(best) != 1 or best[0]['id'] != board['bestId']: _fail('node_board_best_inconsistent')
    if set(board['routeStates']) != {d+'|'+r for d in ds for r in ('6','9')}: _fail('node_board_routes_invalid')
    for key, state in board['routeStates'].items():
        if not isinstance(state, dict) or state.get('state') not in STATES or type(state.get('terminalKnown')) is not bool or key != state.get('serviceDate','')+'|'+state.get('routeId',''):
            _fail('node_board_routes_invalid')
        audit = request['qaState']['stations'][request['payload']['stationId']][state['serviceDate']]
        if state['noValidArrivalCount'] != audit['noValidArrivalCount'] or state['otherUnknownCount'] != audit['otherUnknownCount'] or (audit['noValidArrivalCount']+audit['otherUnknownCount'] > 0 and state['terminalKnown']):
            _fail('node_board_unknown_inconsistent')
    known = {k:s['terminalKnown'] for k,s in board['routeStates'].items()}
    in_groups = any(i['id'] == board['bestId'] for i in visible)
    marks = sum(i['isBest'] for i in visible)
    if (not _count(response['candidateCount']) or response['candidateCount'] != len(items)
        or not _count(response['cardCount']) or response['cardCount'] != len(visible)
        or type(response['bestInGroups']) is not bool or response['bestInGroups'] != in_groups
        or not _count(response['displayedBestMarkCount']) or response['displayedBestMarkCount'] != marks
        or response['terminalKnownByRouteDate'] != known or marks != int(in_groups)
        or not _count(response['unknownRouteStateCount'])
        or response['unknownRouteStateCount'] != sum(s['state'] in {'unknown','data_insufficient','start_unconfirmed','terminal_unconfirmed'} for s in board['routeStates'].values())):
        _fail('node_board_summary_inconsistent')
    stable = {k:v for k,v in board.items() if k != 'generatedAt'}
    if response['boardDigest'] != _js_digest(stable): _fail('node_board_digest_mismatch')
    if response['itemContentKeys'] != [_js_digest({k:v for k,v in i.items() if k not in ('id','sourceId')}) for i in items]:
        _fail('node_item_content_mismatch')
    return board


def _validate_response(response, request):
    try: return _validate_response_impl(response, request)
    except DisplayCollectionError: raise
    except (TypeError, KeyError, ValueError, AttributeError, IndexError, OverflowError):
        _fail('node_response_schema_invalid')


def _verify_binding(payload, state):
    station = payload['stationId']
    raw = _json_bytes(payload)
    expected = {'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()}
    if state['candidateFiles'].get(station) != expected:
        _fail('qa_payload_integrity_mismatch')


def _envelope(station, days, cache):
    if any(cache[d]['availability'] != 'known' for d in days):
        bad = [cache[d] for d in days if cache[d]['availability'] != 'known']
        _fail(bad[0]['reasonCode'], bad[0]['availability'])
    payload = copy.deepcopy(cache[days[0]]['payload'])
    payload['serviceDays'] = [copy.deepcopy(cache[d]['payload']['serviceDays'][0]) for d in days]
    v2.validate_v2_payload(payload)
    if [d['serviceDate'] for d in payload['serviceDays']] != days or payload['stationId'] != station:
        _fail('payload_date_or_station_inconsistent')
    rows = [copy.deepcopy(cache[d]['audit']) for d in days]
    audit = v2._build_exclusion_audit(rows)
    actual = {(station,d['serviceDate']):len(d['departures']) for d in payload['serviceDays']}
    v2._validate_exclusion_audit(audit, [station], days, actual, audit['totalGeneratedCount'])
    raw = _json_bytes(payload)
    integrity = {'path':v2.ROUTE_FILENAMES[station], 'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()}
    manifest = {'quality':{'exclusionAudit':audit}, 'candidateFiles':{station:integrity}}
    state = _qa_state(manifest, [station], days)
    if state['candidateFiles'][station] != {k:integrity[k] for k in ('bytes','sha256')}:
        _fail('qa_payload_integrity_mismatch')
    # _qa_state has permissive .get defaults; the strict audit validator above
    # requires all reason/classification fields before it is called.
    expected = {d:{'infoCount':cache[d]['audit']['reasonCounts']['explicit_pass_info'],
                  'noValidArrivalCount':cache[d]['audit']['reasonCounts']['no_valid_arrival'],
                  'otherUnknownCount':sum(cache[d]['audit']['reasonCounts'][k] for k in ('primary_arrival_missing','unknown'))} for d in days}
    if state['stations'][station] != expected: _fail('qa_exclusion_binding_inconsistent')
    return payload, state


def _cell_metrics(board, response):
    items = board['items']; visible = [i for g in board['groups'] for i in g['items']]
    best = next((i for i in items if i['id'] == board['bestId']), None)
    metrics = dict(itemsCount=len(items), groupsCardCount=len(visible),
        routeCardCounts={r:sum(i['routeId'] == r for i in visible) for r in ('6','9')},
        serviceDateCandidateCounts=dict(sorted(Counter(i['serviceDate'] for i in items).items())),
        directCount=sum(i['journeyKind'] == 'direct' for i in items),
        transferCount=sum(i['journeyKind'] == 'transfer' for i in items),
        bestExists=best is not None, bestContentReference=None if best is None else response['itemContentKeys'][items.index(best)],
        bestInGroups=response['bestInGroups'], displayedBestMarkCount=response['displayedBestMarkCount'],
        routeStates=board['routeStates'], terminalKnown=response['terminalKnownByRouteDate'],
        serviceState=board['serviceState'], uncertainRouteStateCount=response['unknownRouteStateCount'],
        unknownSuppressedRouteCount=sum(s['noValidArrivalCount']+s['otherUnknownCount']>0 for s in board['routeStates'].values()),
        unknownStartSuppressedRouteCount=sum(s['state']=='start_unconfirmed' for s in board['routeStates'].values()),
        unknownTerminalSuppressedRouteCount=sum(s['state']=='terminal_unconfirmed' for s in board['routeStates'].values()),
        zeroCandidates=len(items) == 0, noValidArrivalCount=board['noValidArrivalCount'],
        otherUnknownCount=board['otherUnknownCount'], infoCount=board['infoCount'],
        validationErrors=[], candidateComparisonPartial=board['candidateComparisonPartial'])
    return metrics


def _key(cell):
    return tuple(cell['dimensions'][k] for k in ('observationInstant','stationId','scenarioId'))


def collect_display_models(store, source_dir, *, quality_context=None, display_context=None,
                           engine=None, root=quality.ROOT, detail_limit=DEFAULT_DETAIL_LIMIT, timeout=20):
    if type(detail_limit) is not int or not 0 <= detail_limit <= MAX_DETAIL_LIMIT:
        raise ValueError('detail_limit_invalid')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 120:
        raise ValueError('node_timeout_invalid')
    store, source_dir, root = Path(store), Path(source_dir), Path(root)
    report = dict(contract='odpt-display-model-collection', schemaVersion=1, snapshotId=None,
        contentFingerprint=None, qualityContextFingerprint=None, displayContextFingerprint=None,
        engineFingerprint=None, environment=None, observationInstants=[], scenarios=[],
        cells=[], aggregateMetrics=None, checks={}, findings=[], notEvaluated=list(NOT_EVALUATED),
        collectionStatus='failed', inputReadiness='ready', reasonCodes=[], omittedDetails={})
    before = None; ready = False; global_errors = []; normal = []; abnormal = []
    generation_normal = []; generation_abnormal = []; total_generation = 0; finding_count = 0
    generation_totals = Counter(); generation_availability = Counter()
    counts = Counter(); states = Counter(); route_states = Counter(); terminal = Counter(); date_counts = Counter(); route_cards = Counter(); availability = Counter()
    protocol = Counter(); error_codes = Counter()
    def finding(value):
        nonlocal finding_count
        finding_count += 1
        if len(report['findings']) < detail_limit: report['findings'].append(value)
    def validate():
        return quality.validate_inputs(store,store,source_dir,source_dir,q,q,engine,engine,root=root)
    def stop(code, category='invalid'):
        global_errors.append((code,category))
    try:
        engine = copy.deepcopy(engine) if engine is not None else quality.build_engine(root)
        quality._validate_engine(engine)
        q = quality.normalize_context(quality_context if quality_context is not None else quality.initial_context(engine['engineFingerprint']))
        d = display.normalize_context(display_context, q) if display_context is not None else display.create_context(q,list(DEFAULT_INSTANTS))
        report.update(qualityContextFingerprint=q['contextFingerprint'], displayContextFingerprint=d['contextFingerprint'],
                      engineFingerprint=engine['engineFingerprint'], environment=copy.deepcopy(engine['environment']),
                      observationInstants=d['observationInstants'], scenarios=d['displayScenarios'],
                      qualityEvaluationContext=q, displayEvaluationContext=d)
        before = itinerary_metrics._inventory(store,source_dir)
        start = validate(); report['checks']['inputStart'] = start
        report.update(snapshotId=start['baselineSnapshotId'],contentFingerprint=start['baselineContentFingerprint'])
        if start['comparisonReadiness'] != 'ready':
            for code in start['reasonCodes']: stop(code,start['comparisonReadiness'])
        else:
            ready = True
            needed = sorted({day for days in d['requiredServiceDates'].values() for day in days})
            report['checks']['requiredServiceDates'] = needed
            for station in q['stationIds']:
                cache = {}; generator = None
                try:
                    generator = ItineraryGenerator(gtfs_zip=source_dir/'TokyoMetro-Train-GTFS.zip', odpt_dir=source_dir,
                        destination_station_id=station, min_transfer_seconds=q['minimumWaitSeconds'], max_transfer_seconds=q['maximumWaitSeconds'])
                except Exception: pass
                for day in needed:
                    total_generation += 1
                    entry = {'stationId':station,'serviceDate':day,'availability':'unavailable','reasonCode':'generator_input_unavailable'}
                    try:
                        if generator is None: _fail('generator_input_unavailable')
                        payload, measured = v2._build_station_payload(generator,station,[day],'2000-01-01T00:00:00Z')
                        v2.validate_v2_payload(payload)
                        audit = v2._build_exclusion_audit(measured['exclusionAudit'])
                        actual = {(station,day):len(payload['serviceDays'][0]['departures'])}
                        v2._validate_exclusion_audit(audit,[station],[day],actual,measured['itineraryResultCount'])
                        cache[day] = {'availability':'known','payload':payload,'audit':audit['byStationDate'][0]}
                        entry = dict(stationId=station,serviceDate=day,availability='known',
                                     generatedCount=audit['totalGeneratedCount'],candidateCount=audit['candidateCount'],
                                     excludedCount=audit['excludedCount'],reasonCounts=audit['reasonCounts'],
                                     classificationCounts=audit['classificationCounts'],routeCoverage=payload['serviceDays'][0]['routeCoverage'],status='PASS')
                    except v2.V2Error as exc:
                        entry.update(reasonCode=exc.code,availability='out-of-range' if exc.code == 'requested_service_date_outside_feed' else 'unavailable')
                    except DisplayCollectionError as exc: entry.update(reasonCode=exc.code,availability=exc.availability)
                    except Exception: entry.update(reasonCode='payload_generation_failed')
                    if day not in cache:
                        cache[day] = {k:entry[k] for k in ('availability','reasonCode')}
                        finding({'code':entry['reasonCode'],'stationId':station,'serviceDate':day})
                    # Day evidence is separate from observation cell totals (never summed across scenarios).
                    generation_availability[entry['availability']] += 1
                    if entry['availability'] == 'known':
                        for k in ('generatedCount','candidateCount','excludedCount'): generation_totals[k] += entry[k]
                    generation_target = generation_normal if entry['availability'] == 'known' else generation_abnormal
                    if len(generation_target) < detail_limit: generation_target.append(entry)
                for instant in d['observationInstants']:
                    days = d['requiredServiceDates'][instant]
                    try: payload, state = _envelope(station,days,cache); envelope_error = None
                    except (DisplayCollectionError, v2.V2Error, PrepareError) as exc:
                        envelope_error = (exc.code,getattr(exc,'availability','unavailable'))
                    for scenario in d['displayScenarios']:
                        dims = dict(snapshotId=report['snapshotId'],observationInstant=instant,stationId=station,scenarioId=scenario['id'])
                        cell = dict(dimensions=dims,availability='known',reasonCodes=[],metrics=None)
                        counts['cellCount'] += 1
                        try:
                            if envelope_error: _fail(*envelope_error)
                            _verify_binding(payload,state)
                            request = dict(contract='odpt-display-adapter-request',schemaVersion=1,
                                qualityContext=q,displayContext=d,expectedNodeRuntime=engine['environment']['node'],
                                payload=payload,qaState=state,observationInstant=instant,displayScenario=scenario)
                            response, transport = _run_node(request,root=root,timeout=timeout)
                            board = _validate_response(response,request)
                            protocol.update({k:transport[k] for k in ('requestBytes','responseBytes')});protocol['successfulRequests'] += 1
                            cell['metrics'] = _cell_metrics(board,response)
                            cell['model'] = {k:v for k,v in board.items() if k != 'generatedAt'}
                            cell['protocol'] = transport; cell['boardDigest'] = response['boardDigest']
                            cell['checks'] = {k:'PASS' for k in ('payloadValidation','qaStateBinding','candidateIntegrity','nodeResponse','bestDisplayConsistency')}
                            m = cell['metrics']; counts['evaluatedCellCount'] += 1
                            counts['itemsCount'] += m['itemsCount']; counts['groupsCardCount'] += m['groupsCardCount']
                            counts['directCount'] += m['directCount']; counts['transferCount'] += m['transferCount']
                            counts['bestExistsCount'] += m['bestExists']; counts['bestInGroupsCount'] += m['bestInGroups']
                            counts['bestOutsideGroupsCount'] += m['bestExists'] and not m['bestInGroups']
                            counts['displayedBestMarkCount'] += m['displayedBestMarkCount']
                            counts['zeroCandidateCellCount'] += m['zeroCandidates']; counts['bestConsistencyPassCount'] += 1
                            for k in ('unknownSuppressedRouteCount','unknownStartSuppressedRouteCount','unknownTerminalSuppressedRouteCount','uncertainRouteStateCount'):
                                counts[k] += m[k]
                            states[m['serviceState']] += 1; route_cards.update(m['routeCardCounts']); date_counts.update(m['serviceDateCandidateCounts'])
                            route_states.update(s['state'] for s in m['routeStates'].values())
                            terminal.update('known' if v else 'unconfirmed' for v in m['terminalKnown'].values())
                        except DisplayCollectionError as exc:
                            cell.update(availability=exc.availability,reasonCodes=[exc.code])
                            protocol['failedCells'] += 1; error_codes[exc.code] += 1
                            finding({'code':exc.code,'dimensions':dims})
                        availability[cell['availability']] += 1
                        target = normal if cell['availability'] == 'known' else abnormal
                        if len(target) < detail_limit: target.append(cell)
                del generator, cache
    except (quality.QualityInputError, quality.StoreError) as exc:
        stop(exc.code,getattr(exc,'category','unavailable' if exc.code == 'store_not_found' else 'invalid'))
    finally:
        if before is not None:
            try:
                end = validate(); report['checks']['inputEnd'] = end
                if end['comparisonReadiness'] != 'ready':
                    for code in end['reasonCodes']: stop(code,end['comparisonReadiness'])
                after = itinerary_metrics._inventory(store,source_dir)
                report['checks']['inputImmutability'] = {'status':'PASS' if before == after else 'FAIL',
                    'sourceFileCount':7,'storeFileCount':8,'before':before[0],'after':after[0]}
                if before != after: stop('inputs_changed_during_display_collection')
            except (quality.QualityInputError, quality.StoreError) as exc:
                stop(exc.code,getattr(exc,'category','invalid'))
                report['checks']['inputImmutability'] = {'status':'not-confirmed'}
    generation = sorted((generation_abnormal+generation_normal)[:detail_limit],key=lambda e:(e['serviceDate'],e['stationId']))
    report['checks']['generation'] = generation
    report['checks']['generationCellCount'] = total_generation
    report['checks']['generationSummary'] = {'availabilityCounts':dict(sorted(generation_availability.items())),
        **{k:generation_totals[k] if generation_availability['known'] else None for k in ('generatedCount','candidateCount','excludedCount')}}
    report['checks']['protocolTotals'] = dict(sorted(protocol.items()))
    report['cells'] = sorted((abnormal+normal)[:detail_limit],key=_key)
    report['aggregateMetrics'] = {**dict(sorted(counts.items())), 'cellCount':counts['cellCount'], 'evaluatedCellCount':counts['evaluatedCellCount'],
        'unavailableCellCount':availability['unavailable'], 'outOfRangeCellCount':availability['out-of-range'],
        'partialCellCount':counts['cellCount']-counts['evaluatedCellCount'],
        'availabilityCounts':dict(sorted(availability.items())),
        'serviceStates':dict(sorted(states.items())), 'routeStateCounts':dict(sorted(route_states.items())),
        'terminalKnownCounts':dict(sorted(terminal.items())), 'routeCardCounts':dict(sorted(route_cards.items())),
        'serviceDateCandidateCounts':dict(sorted(date_counts.items())), 'validationErrorCounts':dict(sorted(error_codes.items()))}
    for key,total,kept in [('cells',counts['cellCount'],len(report['cells'])),('generation',total_generation,len(generation)),('findings',finding_count,len(report['findings']))]:
        if total > kept: report['omittedDetails'][key] = total-kept
    report['aggregateMetrics']['findingCount'] = finding_count
    for k in ('itemsCount','groupsCardCount','directCount','transferCount','bestExistsCount','bestInGroupsCount',
              'bestOutsideGroupsCount','displayedBestMarkCount','zeroCandidateCellCount','bestConsistencyPassCount',
              'unknownSuppressedRouteCount','unknownStartSuppressedRouteCount','unknownTerminalSuppressedRouteCount','uncertainRouteStateCount'):
        report['aggregateMetrics'][k] = counts[k] if counts['evaluatedCellCount'] else None
    report['checks']['engineDependencyCount'] = len(engine['files']) if isinstance(engine,dict) and isinstance(engine.get('files'),list) else None
    if global_errors:
        report.update(collectionStatus='failed',inputReadiness=next(c for c in ('invalid','unavailable','incomparable') if any(cat==c for _,cat in global_errors)),
                      reasonCodes=sorted({code for code,_ in global_errors}),cells=[],aggregateMetrics=None,findings=[])
        report['findings'] = [{'code':code} for code in report['reasonCodes']][:detail_limit]
        report['checks']['generationSummary'] = None
        report['checks']['generation'] = []  # Not confirmed evidence after global invalidation.
        report['notEvaluated'].append('display-models-input-not-confirmed')
    elif ready:
        report['collectionStatus'] = 'partial' if counts['evaluatedCellCount'] else 'failed'  # DOM/visual quality is deliberately outside this stage.
    if report['omittedDetails']:
        report['notEvaluated'].append('omitted-display-details')
        report['reasonCodes'] = sorted(set(report['reasonCodes']) | {'detail_limit_reached'})
    report['notEvaluated'] = sorted(set(report['notEvaluated']))
    # Physical timestamps are immutability evidence, never part of the digest.
    report['collectionDigest'] = quality.digest(report)
    return report


def exit_code(report):
    if report['inputReadiness'] == 'invalid': return 3
    if report['inputReadiness'] == 'unavailable': return 4
    if report['collectionStatus'] == 'failed' or report['omittedDetails']: return 2
    if report['aggregateMetrics']['availabilityCounts'].get('known',0) != report['aggregateMetrics'].get('cellCount',0): return 2
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store',type=Path,required=True)
    parser.add_argument('--source-dir',type=Path,required=True)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    report = collect_display_models(args.store,args.source_dir)
    print('snapshot='+(report['snapshotId'] or 'unavailable'))
    print(f'observation_count={len(report["observationInstants"])} scenario_count={len(report["scenarios"])}')
    print('aggregate_metrics='+json.dumps(report['aggregateMetrics'],sort_keys=True))
    print('collection_status='+report['collectionStatus']+' input_readiness='+report['inputReadiness'])
    print('not_evaluated='+','.join(report['notEvaluated']))
    print('reasons='+(','.join(report['reasonCodes']) or 'none'))
    print('input_immutability='+report['checks'].get('inputImmutability',{}).get('status','not-confirmed'))
    print('collection_digest='+report['collectionDigest'])
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f'elapsed_seconds={time.perf_counter()-started:.3f} peak_rss_bytes={rss if sys.platform == "darwin" else rss*1024}')
    return exit_code(report)


if __name__ == '__main__': raise SystemExit(main())
