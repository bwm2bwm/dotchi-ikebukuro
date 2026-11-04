#!/usr/bin/env python3
"""Private read-only single-Snapshot DOM smoke QA. Never persists payloads/results."""
from __future__ import annotations
import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import math
from pathlib import Path
import resource
import sys
import time

if __package__:
    from . import odpt_display_metrics as model
else:
    import odpt_display_metrics as model
quality, display = model.quality, model.display
CONTRACT = 'dotchi.odpt.dom-qa'
INSTANT = '2026-10-29T03:00:00Z'
STATIONS = ('Hikawadai', 'Senkawa')
NOT_EVALUATED = ['browser-rendering', 'css-cascade', 'font-wrapping-safe-area',
    'dialog-focus-accessibility', 'http-csp-cache', 'freshness', 'publication-eligibility',
    'all-station-dom-evaluation', 'all-boundary-dom-evaluation', 'cross-snapshot-dom-diff',
    'cross-service-date-transfer-search', 'application-period', 'public-pipeline-gate',
    'environment-probe-process-count', 'html-not-loaded-by-fake-dom']
DOM_CHECKS = ('candidateBytes','allStationQaState','adapterValidation','domInitialization',
    'v2BoardProjection','groupsAndCards','presentation','bestAndTerminal','routeNotifications','countdownAndScenario','cleanup')


def result_digest(report):
    return quality.digest({k:v for k,v in report.items() if k not in ('resultDigest','timings','resources')})


def _all_station_inputs(cache, days):
    """Reuse the strict envelope/audit binding for every real station, not just targets."""
    payloads, states, texts = {}, {}, {}
    for station in sorted(quality.STATIONS):
        if station not in cache: model._fail('all_station_evidence_missing', 'missing')
        if any(day not in cache[station] for day in days): model._fail('required_day_missing', 'missing')
        payload, state = model._envelope(station, days, cache[station])
        model._verify_binding(payload, state)
        payloads[station] = payload; states[station] = state
        texts[station] = model._json_bytes(payload).decode('utf-8')
    first = states[sorted(states)[0]]
    combined = {k:copy.deepcopy(first[k]) for k in ('schemaVersion','dataScope','serviceDates')}
    combined['stations'] = {s:states[s]['stations'][s] for s in sorted(states)}
    combined['candidateFiles'] = {s:states[s]['candidateFiles'][s] for s in sorted(states)}
    return payloads, combined, texts


def _response(response, request):
    fields = {'contract','schemaVersion','status','stationId','observationInstant','scenarioId','nowMs',
              'adapterResponse','observation','observationDigest','checks'}
    if not isinstance(response, dict) or set(response) != fields: model._fail('dom_response_schema_invalid', 'invalid')
    r = request['adapterRequest']
    if (response['contract'] != 'odpt-dom-response' or type(response['schemaVersion']) is not int or response['schemaVersion'] != 1
        or response['status'] != 'ok' or response['stationId'] != request['stationId']
        or response['observationInstant'] != r['observationInstant'] or response['scenarioId'] != r['displayScenario']['id']
        or type(response['nowMs']) is not int or response['nowMs'] != request['nowMs']):
        model._fail('dom_response_reference_mismatch', 'invalid')
    board = model._validate_response(response['adapterResponse'], r)
    dom = response['observation']
    if (not isinstance(dom, dict) or response['observationDigest'] != quality.digest(dom)
        or response['checks'] != {k:'PASS' for k in DOM_CHECKS}): model._fail('dom_evidence_invalid', 'invalid')
    try:
        expected = [[i['id'] for i in group['items']] for group in board['groups']]
        actual = [[i['id'] for i in group['cards']] for group in dom['groups']]
        if expected != actual: model._fail('dom_card_inconsistent', 'invalid')
        visible = [i for g in dom['groups'] for i in g['cards']]
        marks = sum(bool(i['best']) for i in visible)
        if marks != response['adapterResponse']['displayedBestMarkCount']: model._fail('dom_best_inconsistent', 'invalid')
        if dom['status'] != board['status'] or dom['directOnly'] != r['displayScenario']['directOnly']:
            model._fail('dom_state_inconsistent', 'invalid')
    except (KeyError, TypeError): model._fail('dom_observation_schema_invalid', 'invalid')
    return dict(itemsCount=len(board['items']), groupCount=len(board['groups']),
        groupsCardCount=sum(len(g['items']) for g in board['groups']), domCardCount=len(visible),
        bestInGroups=response['adapterResponse']['bestInGroups'], bestMarkCount=marks,
        terminalBadgeCount=sum(bool(i['terminal']) for i in visible), serviceState=board['serviceState'],
        routeStates={k:v['state'] for k,v in board['routeStates'].items()},
        terminalKnown={k:v['terminalKnown'] for k,v in board['routeStates'].items()})


def collect_dom_qa(store, source_dir, *, quality_context=None, display_context=None, engine=None,
                   root=quality.ROOT, detail_limit=1000, timeout=20):
    if type(detail_limit) is not int or not 0 <= detail_limit <= 10000: raise ValueError('detail_limit_invalid')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 120: raise ValueError('timeout_invalid')
    store, source_dir, root = Path(store), Path(source_dir), Path(root)
    started = time.perf_counter()
    report = dict(contract=CONTRACT, schemaVersion=1, snapshotId=None, contentFingerprint=None,
        qualityContextFingerprint=None, displayContextFingerprint=None, engineFingerprint=None,
        environment=None, evaluationScope=None, cells=[], checks={}, findings=[], notEvaluated=list(NOT_EVALUATED),
        domQaStatus='failed', inputReadiness='ready', reasonCodes=[], summary=None, omittedDetails={})
    before = None; frozen_engine = None; errors = []; cells = []; generation = []; findings = []
    starts = 0; transport_totals = Counter()
    def validate():
        return quality.validate_inputs(store,store,source_dir,source_dir,q,q,frozen_engine,frozen_engine,root=root)
    try:
        frozen_engine = copy.deepcopy(engine) if engine is not None else quality.build_engine(root)
        quality._validate_engine(frozen_engine)
        q = quality.normalize_context(quality_context if quality_context is not None else quality.initial_context(frozen_engine['engineFingerprint']))
        d = display.normalize_context(display_context, q) if display_context is not None else display.create_context(q,[INSTANT])
        # Phase 3d-3a evaluates one explicit instant and only these two stations.
        if len(d['observationInstants']) != 1: quality.fail('dom_smoke_scope_invalid')
        instant = d['observationInstants'][0]; days = d['requiredServiceDates'][instant]
        report.update(qualityContextFingerprint=q['contextFingerprint'], displayContextFingerprint=d['contextFingerprint'],
            engineFingerprint=frozen_engine['engineFingerprint'], environment=copy.deepcopy(frozen_engine['environment']),
            evaluationScope=dict(kind='node-dom-semantics', observationInstants=[instant], stationIds=list(STATIONS),
                scenarioIds=[s['id'] for s in d['displayScenarios']], timezone='Asia/Tokyo',
                qaStateStationIds=sorted(quality.STATIONS), requiredServiceDates=days),
            qualityEvaluationContext=q, displayEvaluationContext=d)
        before = model.itinerary_metrics._inventory(store,source_dir)
        start = validate(); report['checks']['inputStart'] = start
        report.update(snapshotId=start['baselineSnapshotId'], contentFingerprint=start['baselineContentFingerprint'])
        if start['comparisonReadiness'] != 'ready':
            errors.extend((start['comparisonReadiness'], code) for code in start['reasonCodes'])
        else:
            cache = {}
            for station in sorted(quality.STATIONS):
                generator = None
                try:
                    generator = model.ItineraryGenerator(gtfs_zip=source_dir/'TokyoMetro-Train-GTFS.zip', odpt_dir=source_dir,
                        destination_station_id=station, min_transfer_seconds=q['minimumWaitSeconds'], max_transfer_seconds=q['maximumWaitSeconds'])
                except Exception: pass
                cache[station] = {}
                for day in days:
                    cache[station][day], evidence = model._generate_day(generator,station,day)
                    if evidence['availability'] == 'known':
                        rows = cache[station][day]['payload']['serviceDays'][0]['departures']
                        evidence['primaryDirectCount'] = sum(r['primary']['kind']=='direct' for r in rows)
                        evidence['primaryTransferCount'] = sum(r['primary']['kind']=='transfer' for r in rows)
                    generation.append(evidence)
                del generator
            try:
                payloads, state, texts = _all_station_inputs(cache,days)
                envelope_error = None
                report['checks']['allStationQaState'] = dict(status='PASS', stationCount=8, stationDateCount=24)
            except (model.DisplayCollectionError, model.v2.V2Error, model.PrepareError) as exc:
                envelope_error = exc.code
                report['checks']['allStationQaState'] = dict(status='FAIL', reasonCode=exc.code)
            del cache
            epoch = int(datetime.strptime(instant,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()*1000)
            for station in STATIONS:
                for scenario in d['displayScenarios']:
                    cell = dict(stationId=station, observationInstant=instant, scenarioId=scenario['id'],
                        availability='unavailable', reasonCodes=[], metrics=None)
                    try:
                        if envelope_error: model._fail(envelope_error)
                        adapter = dict(contract='odpt-display-adapter-request',schemaVersion=1,qualityContext=q,displayContext=d,
                            expectedNodeRuntime=frozen_engine['environment']['node'], payload=payloads[station],qaState=state,
                            observationInstant=instant,displayScenario=scenario)
                        request = dict(contract='odpt-dom-request',schemaVersion=1,adapterRequest=adapter,
                            candidateText=texts[station],stationId=station,nowMs=epoch)
                        starts += 1
                        response, transport = model._run_node(request,root=root,timeout=timeout,
                            runner='odpt_dom_runner.mjs',response_contract='odpt-dom-response')
                        transport_totals.update({k:transport[k] for k in ('requestBytes','responseBytes')})
                        cell.update(availability='known', metrics=_response(response,request), observation=response['observation'],
                            observationDigest=response['observationDigest'], checks=response['checks'])
                    except model.DisplayCollectionError as exc:
                        code = exc.code
                        if 'node_runtime_mismatch' in code: errors.append(('incomparable',code))
                        invalid = exc.availability == 'invalid' or code.endswith(('_invalid','_mismatch','_inconsistent')) or 'dom_board_inconsistent' in code
                        cell.update(availability='failed' if invalid else 'unavailable',reasonCodes=[code])
                        findings.append(dict(code=code, stationId=station, scenarioId=scenario['id']))
                    cells.append(cell)
    except (quality.QualityInputError, quality.StoreError) as exc:
        errors.append((getattr(exc,'category','unavailable' if exc.code=='store_not_found' else 'invalid'),exc.code))
    finally:
        if before is not None:
            try:
                end = validate(); report['checks']['inputEnd'] = end
                if end['comparisonReadiness'] != 'ready': errors.extend((end['comparisonReadiness'],code) for code in end['reasonCodes'])
                same = before == model.itinerary_metrics._inventory(store,source_dir)
                report['checks']['inputImmutability'] = dict(status='PASS' if same else 'FAIL',sourceFileCount=7,storeFileCount=8)
                if not same: errors.append(('invalid','inputs_changed_during_dom_qa'))
            except (quality.QualityInputError, quality.StoreError) as exc: errors.append(('invalid',exc.code))
    report['checks']['generationCount'] = len(generation)
    report['checks']['generation'] = generation[:detail_limit]
    report['checks']['nodeStarts'] = starts  # attempted cell runner starts, excludes environment probes
    report['checks']['transportTotals'] = dict(transport_totals)
    known_gen = [g for g in generation if g['availability']=='known']
    report['checks']['generationKnownCount'] = len(known_gen)
    report['checks']['successfulNodeRequests'] = sum(c['availability']=='known' for c in cells)
    report['checks']['generationTotals'] = ({k:sum(g[k] for g in known_gen) for k in
        ('generatedCount','candidateCount','excludedCount','primaryDirectCount','primaryTransferCount')} if known_gen else None)
    report['findings'] = findings[:detail_limit]
    # Abnormal cells first; totals are always calculated before detail retention.
    report['cells'] = sorted(cells,key=lambda c:(c['availability']=='known',c['stationId'],c['scenarioId']))[:detail_limit]
    for name,total,kept in [('cells',len(cells),len(report['cells'])),('generation',len(generation),len(report['checks']['generation'])),('findings',len(findings),len(report['findings']))]:
        if total > kept: report['omittedDetails'][name] = total-kept
    known = [c for c in cells if c['availability']=='known']
    report['summary'] = dict(cellCount=len(cells),evaluatedCellCount=len(known),findingCount=len(findings),
        availabilityCounts=dict(sorted(Counter(c['availability'] for c in cells).items())),
        checkCounts=dict(sorted(Counter(v for c in known for v in c['checks'].values()).items())),
        serviceStateCounts=dict(sorted(Counter(c['metrics']['serviceState'] for c in known).items())),
        routeStateCounts=dict(sorted(Counter(v for c in known for v in c['metrics']['routeStates'].values()).items())),
        terminalKnownCounts=dict(sorted(Counter(str(v).lower() for c in known for v in c['metrics']['terminalKnown'].values()).items())),
        zeroCandidateCellCount=sum(c['metrics']['itemsCount']==0 for c in known) if known else None,
        **{k:sum(c['metrics'][k] for c in known) if known else None for k in
           ('itemsCount','groupCount','groupsCardCount','domCardCount','bestMarkCount','terminalBadgeCount')})
    if errors:
        category = next(cat for cat in ('invalid','unavailable','incomparable') if any(c==cat for c,_ in errors))
        report.update(inputReadiness=category,domQaStatus='incomparable' if category=='incomparable' else 'failed',
            reasonCodes=sorted({code for _,code in errors}),cells=[],summary=None,findings=[])
        report['checks']['generation'] = []; report['checks']['generationTotals'] = None
    elif any(c['availability']=='failed' for c in cells): report['domQaStatus'] = 'failed'
    elif len(known) == 8 and not report['omittedDetails']: report['domQaStatus'] = 'complete'
    elif known or report['omittedDetails']: report['domQaStatus'] = 'partial'
    if report['omittedDetails']: report['reasonCodes'].append('detail_limit_reached')
    report['timings'] = dict(elapsedSeconds=time.perf_counter()-started)
    scale = 1 if sys.platform=='darwin' else 1024
    report['resources'] = dict(parentPeakRssBytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*scale,
        nodeChildrenPeakRssBytes=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss*scale)
    report['resultDigest'] = result_digest(report)
    return report


def exit_code(report):
    if report['inputReadiness']=='incomparable': return 2
    if report['inputReadiness']=='invalid': return 3
    if report['inputReadiness']=='unavailable': return 4
    if report['domQaStatus']=='complete': return 0
    if report['domQaStatus']=='partial': return 2
    if report['summary'] and report['summary']['availabilityCounts'].get('failed',0): return 3
    return 4


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store',type=Path,required=True)
    parser.add_argument('--source-dir',type=Path,required=True)
    args = parser.parse_args(argv)
    report = collect_dom_qa(args.store,args.source_dir)
    # Safe summary only; observations, candidate IDs and journey text stay inside private IPC/memory.
    import json
    for key in ('snapshotId','contentFingerprint','engineFingerprint','qualityContextFingerprint','displayContextFingerprint','evaluationScope','summary','domQaStatus','reasonCodes','notEvaluated','resultDigest','timings','resources'):
        print(key+'='+json.dumps(report[key],ensure_ascii=False,sort_keys=True))
    for key in ('allStationQaState','generationCount','generationTotals','nodeStarts','inputImmutability'):
        print(key+'='+json.dumps(report['checks'].get(key),sort_keys=True))
    print('findings='+json.dumps(report['findings'],sort_keys=True))
    return exit_code(report)


if __name__=='__main__': raise SystemExit(main())
