#!/usr/bin/env python3
"""Private display-model comparison. Sequential, read-only, memory only."""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import itertools
import math
from pathlib import Path
import resource
import sys
import time

if __package__:
    from . import odpt_display_metrics as collector
    from . import odpt_display_state_diff as state_diff
else:
    import odpt_display_metrics as collector
    import odpt_display_state_diff as state_diff
quality, display = collector.quality, collector.display
SIDES = ('baseline', 'candidate')
DIMS = ('observationInstant', 'stationId', 'scenarioId')
DEFAULT_DETAIL_LIMIT = 1000
MAX_DETAIL_LIMIT = 10000
NOT_EVALUATED = sorted((set(collector.NOT_EVALUATED)-{'display-model-diff'}) | {
    'raw-route-coverage-data-state', 'warning-count-not-exposed-by-board',
    'last-eligible-candidate-outside-board',
    'cross-generation-train-or-journey-identity', 'environment-probe-process-count'})
COUNT_METRICS = ('itemsCount', 'groupsCardCount', 'directCount', 'transferCount', 'visibleBestMarkerCount')
ITEM_FIELDS = ('departureAtMs', 'arrivalAtMs', 'routeId', 'serviceDate', 'journeyKind', 'kind', 'destination')


class DiffError(ValueError):
    def __init__(self, code, category='invalid'):
        self.code, self.category = code, category
        super().__init__(code)


def fail(code, category='invalid'): raise DiffError(code, category)
def key(cell): return tuple(cell['dimensions'][k] for k in DIMS)
def count(v): return type(v) is int and 0 <= v <= 2**53-1


def semantic_item(item):
    """Selected journey only; IDs, terminal flags and best marks have other scopes."""
    if not isinstance(item, dict) or any(k not in item for k in ITEM_FIELDS+('transfer',)):
        fail('collection_item_fields_invalid')
    value = {k:item[k] for k in ITEM_FIELDS}
    for field in ('departureAtMs','arrivalAtMs'):
        if type(value[field]) is not int or abs(value[field]) > 2**53-1: fail('collection_item_time_invalid')
    if value['arrivalAtMs'] < value['departureAtMs'] or value['routeId'] not in ('6','9') or value['journeyKind'] not in ('direct','transfer'):
        fail('collection_item_invalid')
    for field in ('serviceDate','kind','destination'):
        if not isinstance(value[field],str) or not value[field]: fail('collection_item_label_invalid')
    try: quality._date(value['serviceDate'])
    except quality.QualityInputError: fail('collection_item_date_invalid')
    transfer = item['transfer']
    if value['journeyKind'] == 'direct':
        if transfer is not None: fail('collection_transfer_invalid')
        value['transfer'] = None
    else:
        if (not isinstance(transfer,dict) or set(transfer) != {'station','waitSeconds','waitMinutes','outgoingRoute'}
            or not count(transfer['waitSeconds']) or not 60 <= transfer['waitSeconds'] <= 3600
            or type(transfer['waitMinutes']) not in (int,float) or not math.isfinite(transfer['waitMinutes'])
            or transfer['waitMinutes'] != transfer['waitSeconds']/60
            or any(not isinstance(transfer[f],str) or not transfer[f] for f in ('station','outgoingRoute'))):
            fail('collection_transfer_invalid')
        value['transfer'] = {k:transfer[k] for k in ('station','waitSeconds','outgoingRoute')}
    return value


def _compact_cell(cell, scenario, dates, snapshot_id):
    if not isinstance(cell,dict) or not isinstance(cell.get('reasonCodes'),list) or any(not isinstance(c,str) for c in cell['reasonCodes']):
        fail('collection_cell_invalid')
    dims = cell.get('dimensions')
    if not isinstance(dims,dict) or set(dims) != {'snapshotId',*DIMS} or dims['snapshotId'] != snapshot_id:
        fail('collection_cell_dimensions_invalid')
    status = cell.get('availability')
    if status not in {'known','unavailable','out-of-range'}: fail('collection_availability_invalid')
    if status != 'known':
        if cell.get('metrics') is not None or not cell['reasonCodes']: fail('collection_unavailable_invalid')
        return {'availability':status,'reasonCodes':sorted(set(cell['reasonCodes'])),'values':None}
    if cell['reasonCodes']: fail('collection_known_reasons_invalid')
    m, model = cell.get('metrics'), cell.get('model')
    if not isinstance(m,dict) or not isinstance(model,dict): fail('collection_known_model_missing')
    if not isinstance(model.get('items'),list) or not isinstance(model.get('groups'),list): fail('collection_model_invalid')
    items = model['items']; normalized = []; index = {}
    for item in items:
        value = semantic_item(item)
        if value['serviceDate'] not in dates or (scenario['directOnly'] and value['journeyKind'] != 'direct'):
            fail('collection_scenario_item_mismatch')
        if not isinstance(item.get('id'),str) or item['id'] in index or item.get('sourceId') != item['id']:
            fail('collection_local_id_invalid')
        if type(item.get('isBest')) is not bool: fail('collection_best_flag_invalid')
        index[item['id']] = (item,value); normalized.append(value)
    groups, visible, markers = [], [], []
    for group in model['groups']:
        fields = {'line','items'} | ({'routeId'} if scenario['mode']=='line' else set())
        if not isinstance(group,dict) or set(group) != fields or not isinstance(group['items'],list): fail('collection_group_invalid')
        group_id = group['routeId'] if scenario['mode']=='line' else 'departure'
        if (scenario['mode']=='line' and group_id not in ('6','9')) or (scenario['mode']=='departure' and group['line'] is not None):
            fail('collection_group_invalid')
        seq = []
        for position, item in enumerate(group['items']):
            if not isinstance(item,dict) or item.get('id') not in index or item != index[item['id']][0]: fail('collection_group_reference_invalid')
            value = index[item['id']][1]
            if scenario['mode']=='line' and value['routeId'] != group_id: fail('collection_group_route_invalid')
            seq.append(value); visible.append(item)
            if item['isBest']:
                if item.get('bestLabel') not in ('● 最早着','● 表示候補内の最早着'): fail('collection_best_label_invalid')
                markers.append({'groupId':group_id,'position':position,'content':value,'label':item['bestLabel']})
        groups.append({'groupId':group_id,'items':seq})
    expected = ([normalized[:6]] if normalized else []) if scenario['mode']=='departure' else [v for r in ('6','9') if (v := [i for i in normalized if i['routeId']==r][:3])]
    if [g['items'] for g in groups] != expected or len(set(g['groupId'] for g in groups)) != len(groups): fail('collection_card_limit_inconsistent')
    if scenario['mode']=='line' and [g['groupId'] for g in groups] != [r for r in ('6','9') if any(i['routeId']==r for i in normalized)]: fail('collection_group_order_invalid')
    best_id = model.get('bestId'); marked = [i for i in items if i['isBest']]
    if best_id is None:
        if marked or items: fail('collection_best_inconsistent')
        best = None
    else:
        if best_id not in index or len(marked)!=1 or marked[0]['id']!=best_id: fail('collection_best_inconsistent')
        best = index[best_id][1]
    visible_best = any(i['id']==best_id for i in visible)
    expected_counts = {'itemsCount':len(items),'groupsCardCount':len(visible),
        'directCount':sum(i['journeyKind']=='direct' for i in normalized),
        'transferCount':sum(i['journeyKind']=='transfer' for i in normalized),
        'displayedBestMarkCount':len(markers)}
    if any(not count(m.get(k)) or m[k]!=v for k,v in expected_counts.items()): fail('collection_metric_inconsistent')
    if (type(m.get('bestExists')) is not bool or m['bestExists'] != (best is not None)
        or type(m.get('bestInGroups')) is not bool or m['bestInGroups'] != visible_best
        or len(markers) != int(visible_best)): fail('collection_best_metric_inconsistent')
    expected_ref = None if best is None else collector._js_digest({k:v for k,v in index[best_id][0].items() if k not in ('id','sourceId')})
    if m.get('bestContentReference') != expected_ref: fail('collection_best_reference_invalid')
    route_counts = {r:sum(i['routeId']==r for i in visible) for r in ('6','9')}
    date_counts = dict(sorted(Counter(i['serviceDate'] for i in normalized).items()))
    if (any(not isinstance(m.get(f),dict) or any(not count(v) for v in m[f].values()) for f in ('routeCardCounts','serviceDateCandidateCounts'))
        or m.get('routeCardCounts') != route_counts or m.get('serviceDateCandidateCounts') != date_counts):
        fail('collection_histogram_inconsistent')
    if cell.get('boardDigest') != collector._js_digest(model): fail('collection_board_digest_invalid')
    values = {k:m[k] for k in COUNT_METRICS if k!='visibleBestMarkerCount'}
    values.update(visibleBestMarkerCount=m['displayedBestMarkCount'], routeCardCounts=route_counts,
        serviceDateItemsCounts={d:date_counts.get(d,0) for d in dates}, best=best, bestInGroups=visible_best)
    return {'availability':'known','reasonCodes':[],'values':values,'items':normalized,'groups':groups,'markers':markers,
            'stateEvidence':state_diff.compact_board(model,dates,scenario,semantic_item)}


def _compact_report_impl(report, q, d, engine, snapshot_id, fingerprint):
    if (not isinstance(report,dict) or report.get('contract')!='odpt-display-model-collection'
        or type(report.get('schemaVersion')) is not int or report['schemaVersion']!=1): fail('collection_report_contract_invalid')
    if report.get('inputReadiness') != 'ready':
        category = report.get('inputReadiness')
        if category not in ('invalid','unavailable','incomparable'):fail('collection_input_readiness_invalid')
        fail('collection_input_'+category,category)
    if report.get('collectionStatus') not in ('partial','complete','failed'): fail('collection_report_status_invalid')
    if report.get('snapshotId') != snapshot_id or report.get('contentFingerprint') != fingerprint: fail('collection_snapshot_binding_mismatch')
    if (report.get('engineFingerprint') != engine['engineFingerprint'] or report.get('environment') != engine['environment']
        or report.get('qualityContextFingerprint') != q['contextFingerprint'] or report.get('displayContextFingerprint') != d['contextFingerprint']
        or report.get('qualityEvaluationContext') != q or report.get('displayEvaluationContext') != d
        or report.get('observationInstants') != d['observationInstants'] or report.get('scenarios') != d['displayScenarios']):
        fail('collection_conditions_mismatch','incomparable')
    if report.get('collectionDigest') != quality.digest({k:v for k,v in report.items() if k!='collectionDigest'}): fail('collection_report_digest_invalid')
    checks = report.get('checks',{})
    if checks.get('inputImmutability',{}).get('status') != 'PASS': fail('collection_inputs_not_confirmed')
    for field in ('inputStart','inputEnd'):
        evidence = checks.get(field,{})
        if evidence.get('comparisonReadiness') != 'ready': fail('collection_input_checks_not_confirmed')
        if any(evidence.get(side+'SnapshotId') != snapshot_id or evidence.get(side+'ContentFingerprint') != fingerprint for side in SIDES):
            fail('collection_input_binding_mismatch')
    if not isinstance(report.get('cells'),list) or not isinstance(report.get('aggregateMetrics'),dict): fail('collection_report_cells_invalid')
    index = {}; scenarios = {s['id']:s for s in d['displayScenarios']}
    expected = set(itertools.product(d['observationInstants'],q['stationIds'],scenarios))
    for cell in report['cells']:
        try: k = key(cell)
        except (KeyError,TypeError): fail('collection_cell_dimensions_invalid')
        if k not in expected or k in index: fail('collection_cell_duplicate_or_unexpected')
        reasons=cell.get('reasonCodes',[])
        if isinstance(reasons,list) and all(isinstance(r,str) for r in reasons):
            if any('node_runtime_mismatch' in r for r in reasons):fail('collection_runtime_mismatch','incomparable')
            if any(r.endswith(('_invalid','_inconsistent','_mismatch')) or r.startswith(('node_board_','node_item_content_')) or r in {'duplicate_public_journey','public_id_collision','node_unexpected_stderr'} for r in reasons):
                fail('collection_payload_or_response_invalid')
        index[k] = _compact_cell(cell,scenarios[k[2]],d['requiredServiceDates'][k[0]],snapshot_id)
    summary = report['aggregateMetrics']; omissions=report.get('omittedDetails')
    if not isinstance(omissions,dict) or any(not count(v) for v in omissions.values()): fail('collection_omissions_invalid')
    if not count(summary.get('cellCount')) or summary['cellCount'] != len(expected): fail('collection_cell_count_inconsistent')
    if not count(summary.get('evaluatedCellCount')): fail('collection_evaluated_count_invalid')
    retained_known = [c for c in index.values() if c['availability']=='known']
    if omissions.get('cells',0) != len(expected)-len(index): fail('collection_missing_cells_without_omission')
    if not omissions.get('cells'):
        if summary['evaluatedCellCount'] != len(retained_known): fail('collection_evaluated_count_inconsistent')
        observed=Counter(c['availability'] for c in index.values())
        if (not isinstance(summary.get('availabilityCounts'),dict) or any(not count(v) for v in summary['availabilityCounts'].values())
            or summary['availabilityCounts']!=dict(observed)):fail('collection_availability_aggregate_invalid')
        if report['collectionStatus']=='failed' and retained_known:fail('collection_failed_status_inconsistent')
        for field in ('itemsCount','groupsCardCount','directCount','transferCount'):
            observed = sum(c['values'][field] for c in retained_known) if retained_known else None
            if summary.get(field) != observed: fail('collection_aggregate_inconsistent')
        derived = {
            'bestExistsCount':sum(c['values']['best'] is not None for c in retained_known),
            'bestInGroupsCount':sum(c['values']['bestInGroups'] for c in retained_known),
            'bestOutsideGroupsCount':sum(c['values']['best'] is not None and not c['values']['bestInGroups'] for c in retained_known),
            'displayedBestMarkCount':sum(c['values']['visibleBestMarkerCount'] for c in retained_known),
            'zeroCandidateCellCount':sum(c['values']['itemsCount']==0 for c in retained_known),
            'bestConsistencyPassCount':len(retained_known)}
        if any((not count(summary.get(k)) or summary[k]!=v) if retained_known else summary.get(k) is not None for k,v in derived.items()): fail('collection_best_aggregate_inconsistent')
    return {'cells':index,'summary':copy.deepcopy(summary),'omittedDetails':copy.deepcopy(omissions),
        'execution':{'generationDayCalls':checks.get('generationCellCount'),
                     'nodeRunnerSuccessfulStarts':checks.get('protocolTotals',{}).get('successfulRequests',0),
                     'failedCells':checks.get('protocolTotals',{}).get('failedCells',0)}}


def _compact_report(*args):
    try: return _compact_report_impl(*args)
    except (DiffError,quality.QualityInputError): raise
    except (TypeError,KeyError,ValueError,AttributeError,IndexError,OverflowError):
        fail('collection_report_schema_invalid')


class Details:
    """Separate global budgets for each evidence list. All totals precede retention."""
    def __init__(self,limit): self.limit=limit;self.used=Counter();self.omitted=Counter()
    def retain(self,kind,value):
        if self.used[kind]<self.limit:
            self.used[kind]+=1;return value
        self.omitted[kind]+=1;return None


def _sequence_diff(a,b,budget,addresses_a=None,addresses_b=None):
    tokens_a=[quality.canonical(v).decode('utf-8') for v in a];tokens_b=[quality.canonical(v).decode('utf-8') for v in b]
    ca,cb=Counter(tokens_a),Counter(tokens_b); shared=set(ca)&set(cb)
    duplicate_shared={s for s in shared if ca[s]>1 or cb[s]>1}
    unique_shared={s for s in shared if ca[s]==cb[s]==1}
    content_changed=ca!=cb
    if not content_changed:
        ordered=tokens_a!=tokens_b;order_availability='known'
    else:
        ordered=[s for s in tokens_a if s in unique_shared]!=[s for s in tokens_b if s in unique_shared]
        order_availability='ambiguous' if duplicate_shared else 'known' if len(unique_shared)>=2 else 'not-applicable'
    changes=[];positions=[]
    for token in sorted(set(ca)|set(cb)):
        if ca[token]!=cb[token]:
            value={'content':quality.loads(token),'contentFingerprint':quality.digest(quality.loads(token)),
                'baselineMultiplicity':ca[token],'candidateMultiplicity':cb[token],'delta':cb[token]-ca[token]}
            retained=budget.retain('contentChanges',value)
            if retained is not None: changes.append(retained)
    ia={s:i for i,s in enumerate(tokens_a) if s in unique_shared};ib={s:i for i,s in enumerate(tokens_b) if s in unique_shared}
    position_count=0
    for token in sorted(unique_shared):
        if ia[token]!=ib[token]:
            position_count+=1
            position={'contentFingerprint':quality.digest(quality.loads(token)),
                'baselinePosition':ia[token],'candidatePosition':ib[token]}
            if addresses_a is not None:
                position.update(baselineAddress=addresses_a[ia[token]],candidateAddress=addresses_b[ib[token]])
            retained=budget.retain('positionChanges',position)
            if retained is not None: positions.append(retained)
    return {'baselineCount':len(a),'candidateCount':len(b),'delta':len(b)-len(a),
        'contentChanged':content_changed,'orderChanged':ordered,'orderComparisonAvailability':order_availability,
        'identityAvailability':'ambiguous' if duplicate_shared else 'known',
        'ambiguousContentCount':len(duplicate_shared),'addedCount':sum((cb-ca).values()),'removedCount':sum((ca-cb).values()),
        'baselineContentDigest':quality.digest(sorted(ca.items())),'candidateContentDigest':quality.digest(sorted(cb.items())),
        'baselineOrderDigest':quality.digest(a),'candidateOrderDigest':quality.digest(b),
        'contentChanges':changes,'positionChangeCount':position_count,'positionChanges':positions}


def compare_cells(a,b,expected,*,detail_limit=DEFAULT_DETAIL_LIMIT,evaluate_states=False):
    """Compare compact, already validated evidence; missing cells remain unknown."""
    budget=Details(detail_limit);counts=Counter();totals={};records=[];findings=[];classes=Counter()
    expected=sorted(expected);basic_changed=set();basic_unknown=set()
    for k in expected:
        sides=[index.get(k) for index in (a,b)]
        cell={'dimensions':dict(zip(DIMS,k)), 'availability':{side:(c['availability'] if c else 'missing') for side,c in zip(SIDES,sides)},
              'comparisonAvailability':'known','reasonCodes':[],'changed':False,'classifications':[],'metricDiffs':[]}
        counts['cellCount']+=1
        if any(c is None or c['availability']!='known' for c in sides):
            cell.update(comparisonAvailability='not-evaluable',reasonCodes=sorted({reason for c in sides for reason in (['cell-missing'] if c is None else c['reasonCodes'])}),classifications=['not-evaluable'])
            cell['values']={side:None if c is None or c['availability']!='known' else c['values'] for side,c in zip(SIDES,sides)}
            for name in (*COUNT_METRICS,'routeCardCounts','serviceDateItemsCounts','best','bestInGroups'):
                cell['metricDiffs'].append({'metricId':name,
                    'baselineValue':cell['values']['baseline'][name] if cell['values']['baseline'] is not None else None,
                    'candidateValue':cell['values']['candidate'][name] if cell['values']['candidate'] is not None else None,
                    'delta':None,'comparisonAvailability':'not-evaluable','reasonCodes':cell['reasonCodes']})
            counts['notEvaluableCellCount']+=1
        else:
            x,y=sides;vx,vy=x['values'],y['values'];tags=set()
            for name in (*COUNT_METRICS,'routeCardCounts','serviceDateItemsCounts','best','bestInGroups'):
                base,cand=vx[name],vy[name]
                delta=cand-base if type(base) is int and type(cand) is int else {k:cand[k]-base[k] for k in sorted(base)} if name in ('routeCardCounts','serviceDateItemsCounts') else None
                cell['metricDiffs'].append({'metricId':name,'baselineValue':base,'candidateValue':cand,'delta':delta,
                                          'comparisonAvailability':'known','reasonCodes':[]})
                if base!=cand: cell['changed']=True
                if name in COUNT_METRICS:
                    t=totals.setdefault(name,{'baselineValue':0,'candidateValue':0,'delta':0,'comparedCellCount':0})
                    t['baselineValue']+=base;t['candidateValue']+=cand;t['delta']+=delta;t['comparedCellCount']+=1
            if vy['itemsCount']!=vx['itemsCount']:tags.add('items-increased' if vy['itemsCount']>vx['itemsCount'] else 'items-decreased')
            if vy['groupsCardCount']!=vx['groupsCardCount']:tags.add('cards-increased' if vy['groupsCardCount']>vx['groupsCardCount'] else 'cards-decreased')
            item_diff=_sequence_diff(x['items'],y['items'],budget)
            # Group ID is presentation structure, never a train identifier.
            cards_a=[{'groupId':g['groupId'],'content':i} for g in x['groups'] for i in g['items']]
            cards_b=[{'groupId':g['groupId'],'content':i} for g in y['groups'] for i in g['items']]
            card_diff=_sequence_diff(cards_a,cards_b,budget,
                [{'groupId':g['groupId'],'position':n} for g in x['groups'] for n,_ in enumerate(g['items'])],
                [{'groupId':g['groupId'],'position':n} for g in y['groups'] for n,_ in enumerate(g['items'])])
            cell['items']=item_diff;cell['groups']=card_diff
            cell['groupPresence']={'baselineValue':[g['groupId'] for g in x['groups']], 'candidateValue':[g['groupId'] for g in y['groups']]}
            for label,diff in (('item',item_diff),('card',card_diff)):
                if diff['contentChanged']:tags.add(label+'-content-changed')
                if diff['orderChanged']:tags.add(label+'-order-changed')
            cell['best']={'baselineValue':vx['best'],'candidateValue':vy['best'],
                'comparisonAvailability':'known','identityAvailability':'known','reasonCodes':[]}
            if vx['best']!=vy['best']:tags.add('best-changed');counts['bestChangedCellCount']+=1
            ambiguous=any(d['ambiguousContentCount'] for d in (item_diff,card_diff))
            for side,c in zip(SIDES,sides):
                best=c['values']['best']
                if best is not None and sum(i==best for i in c['items'])>1:
                    cell['best']['identityAvailability']='ambiguous';cell['best']['reasonCodes'].append(side+'-best-semantic-duplicate');ambiguous=True
            cell['best']['reasonCodes'].sort()
            if x['markers']!=y['markers'] or vx['visibleBestMarkerCount']!=vy['visibleBestMarkerCount']:
                tags.add('best-marker-changed');counts['bestMarkerChangedCellCount']+=1
            if vy['best'] is not None and not vy['bestInGroups']:
                counts['candidateBestNotVisibleCellCount']+=1
                if vx['bestInGroups'] or vx['best']!=vy['best']:tags.add('best-not-visible')
            if vx['best'] is not None and not vx['bestInGroups']:counts['baselineBestNotVisibleCellCount']+=1
            cell['bestMarkers']={'baselineValue':x['markers'],'candidateValue':y['markers'],'comparisonAvailability':'known','reasonCodes':[]}
            definite=tags-{'ambiguous','best-not-visible'}
            cell['changed'] = cell['changed'] or bool(definite) or cell['groupPresence']['baselineValue']!=cell['groupPresence']['candidateValue']
            if ambiguous:
                tags.add('ambiguous');counts['ambiguousCellCount']+=1
                cell['comparisonAvailability']='partial';cell['reasonCodes']=['semantic-duplicate-correspondence-ambiguous']
            counts['comparedCellCount']+=1
            counts['changedCellCount' if cell['changed'] else 'unchangedCellCount']+=1
            cell['classifications']=sorted(tags) if tags else ['unchanged']
            if cell['changed']:counts['confirmedFindingCount']+=1
        if not cell['changed'] and cell['comparisonAvailability']=='known':counts['aggregatedUnchangedCellCount']+=1
        classes.update(cell['classifications'])
        if cell['changed']:basic_changed.add(k)
        if cell['comparisonAvailability']!='known':basic_unknown.add(k)
        if cell['changed'] or cell['comparisonAvailability']!='known':
            retained=budget.retain('cellDiffs',cell)
            if retained is not None:records.append(retained)
            finding={'code':'display-cell-changed' if cell['changed'] else 'ambiguous' if 'ambiguous' in cell['classifications'] else 'not-evaluable',
                     'dimensions':cell['dimensions'],'classifications':cell['classifications'],'reasonCodes':cell['reasonCodes'],
                     'confirmedDifference':cell['changed']}
            retained=budget.retain('findings',finding)
            if retained is not None:findings.append(retained)
    summary={name:counts[name] for name in ('cellCount','comparedCellCount','changedCellCount','unchangedCellCount','notEvaluableCellCount',
        'ambiguousCellCount','confirmedFindingCount','bestChangedCellCount','bestMarkerChangedCellCount','baselineBestNotVisibleCellCount','candidateBestNotVisibleCellCount')}
    summary.update(metricDiffTotals=totals,classificationCounts=dict(sorted(classes.items())),
                   unchangedDetailsAggregatedCount=counts['aggregatedUnchangedCellCount'])
    result={'cellDiffs':records,'findings':findings,'summary':summary}
    if evaluate_states:
        states,changed,unknown,inconsistent=state_diff.compare_states(a,b,expected,budget)
        result.update(states)
        # One finding per observed cell, with independent certainty and evaluation status.
        merged={tuple(f['dimensions'][d] for d in DIMS):copy.deepcopy(f) for f in findings}
        for f in states['stateFindings']:
            k=tuple(f['dimensions'][d] for d in DIMS)
            if k not in merged:merged[k]=copy.deepcopy(f)
            else:
                m=merged[k];m['classifications']=sorted(set(m['classifications'])|set(f['classifications']))
                m['reasonCodes']=sorted(set(m['reasonCodes'])|set(f['reasonCodes']))
                m['confirmedDifference'] |= f['confirmedDifference']
                if m['confirmedDifference']:m['code']='display-cell-changed'
        all_findings=[merged[k] for k in sorted(merged)]
        result['findings']=all_findings[:detail_limit]
        if len(all_findings)>detail_limit:budget.omitted['mergedFindings']+=len(all_findings)-detail_limit
        union_changed=basic_changed|changed;union_unknown=basic_unknown|unknown
        result['displaySummary']=dict(cellCount=len(expected),changedCellCount=len(union_changed),
            unchangedCellCount=len(set(expected)-union_changed-union_unknown-inconsistent),
            notEvaluableCellCount=len(union_unknown),inconsistentCellCount=len(inconsistent),
            confirmedFindingCount=len(union_changed))
    result['omittedDetails']=dict(sorted(budget.omitted.items()))
    return result


def comparison_digest(result):
    return quality.digest({k:v for k,v in result.items() if k not in {'comparisonDigest','timings','resources'}})


def compare_display_models(baseline_store,candidate_store,baseline_source_dir,candidate_source_dir,*,
        quality_context=None,display_context=None,engine=None,baseline_context=None,candidate_context=None,
        baseline_display_context=None,candidate_display_context=None,baseline_engine=None,candidate_engine=None,
        root=quality.ROOT,detail_limit=DEFAULT_DETAIL_LIMIT):
    result=dict(contract='dotchi.odpt.display-model-diff',schemaVersion=1,baselineSnapshotId=None,candidateSnapshotId=None,
        contentFingerprints=None,evaluationContexts=None,engineFingerprint=None,environment=None,
        baselineSummary=None,candidateSummary=None,cellDiffs=[],stateDiffs=[],stateTransitions=[],stateFindings=[],
        stateChecks=[],stateSummary=None,displaySummary=None,findings=[],checks={},notEvaluated=list(NOT_EVALUATED),
        comparisonStatus='failed',displayDiffStatus='indeterminate',basicDisplayDiffStatus='indeterminate',
        stateDisplayDiffStatus='indeterminate',
        inputReadiness='ready',reasonCodes=[],summary=None,omittedDetails={},timings={},resources={})
    problems=[];before={};compact=[];compared=None;paths=[(Path(baseline_store),Path(baseline_source_dir)),(Path(candidate_store),Path(candidate_source_dir))]
    started=time.perf_counter()
    try:
        if type(detail_limit) is not int or not 0<=detail_limit<=MAX_DETAIL_LIMIT:fail('detail_limit_invalid')
        engine=copy.deepcopy(engine) if engine is not None else quality.build_engine(root)
        quality._validate_engine(engine)
        default_q=quality_context if quality_context is not None else quality.initial_context(engine['engineFingerprint'])
        qs=[quality.normalize_context(c if c is not None else default_q) for c in (baseline_context,candidate_context)]
        es=[copy.deepcopy(e if e is not None else engine) for e in (baseline_engine,candidate_engine)]
        ds=[display.normalize_context(c if c is not None else display_context,q) if (c is not None or display_context is not None) else display.create_context(q,list(collector.DEFAULT_INSTANTS)) for c,q in zip((baseline_display_context,candidate_display_context),qs)]
        result['evaluationContexts']={'quality':dict(zip(SIDES,qs)),'display':dict(zip(SIDES,ds))}
        if ds[0]!=ds[1]:fail('display_context_conditions_mismatch','incomparable')
        for side,(store,source) in zip(SIDES,paths):before[side]=collector.itinerary_metrics._inventory(store,source)
        def validate():return quality.validate_inputs(paths[0][0],paths[1][0],paths[0][1],paths[1][1],*qs,*es,root=root)
        start=validate();result['checks']['inputStart']=start
        result.update(baselineSnapshotId=start['baselineSnapshotId'],candidateSnapshotId=start['candidateSnapshotId'],
            contentFingerprints={side:start[side+'ContentFingerprint'] for side in SIDES})
        if start['comparisonReadiness']!='ready':problems.append((start['comparisonReadiness'],start['reasonCodes']))
        else:
            result.update(engineFingerprint=es[0]['engineFingerprint'],environment=es[0]['environment'])
            for side,(store,source),q,d,e in zip(SIDES,paths,qs,ds,es):
                phase=time.perf_counter()
                report=collector.collect_display_models(store,source,quality_context=q,display_context=d,engine=e,root=root,
                                                        detail_limit=collector.MAX_DETAIL_LIMIT)
                result['timings'][side+'Seconds']=time.perf_counter()-phase
                compact.append(_compact_report(report,q,d,e,result[side+'SnapshotId'],result['contentFingerprints'][side]))
                del report  # Keep compact semantic/state evidence before evaluating the other side.
                result[side+'Summary']=compact[-1]['summary']
                result['checks'][side+'ExecutionCounts']=compact[-1]['execution']
                result['checks'][side+'CollectionOmissions']=compact[-1]['omittedDetails']
                if compact[-1]['omittedDetails'].get('cells'):
                    result['notEvaluated'].append(side+'-collector-cell-details-omitted')
            expected=itertools.product(ds[0]['observationInstants'],qs[0]['stationIds'],(s['id'] for s in ds[0]['displayScenarios']))
            compared=compare_cells(compact[0]['cells'],compact[1]['cells'],expected,detail_limit=detail_limit,evaluate_states=True)
        # Covers both collections and the comparison itself, including a failed report validation.
        end=validate();result['checks']['inputEnd']=end
        if end['comparisonReadiness']!='ready':problems.append((end['comparisonReadiness'],end['reasonCodes']))
    except (quality.QualityInputError,quality.StoreError,DiffError) as exc:
        problems.append((getattr(exc,'category','unavailable' if exc.code=='store_not_found' else 'invalid'),[exc.code]))
        if before and 'validate' in locals():
            try:
                end=validate();result['checks']['inputEnd']=end
                if end['comparisonReadiness']!='ready':problems.append((end['comparisonReadiness'],end['reasonCodes']))
            except (quality.QualityInputError,quality.StoreError) as error:problems.append((getattr(error,'category','invalid'),[error.code]))
    finally:
        for side,(store,source) in zip(SIDES,paths):
            if side not in before:continue
            try:
                same=before[side]==collector.itinerary_metrics._inventory(store,source)
                result['checks'][side+'InputImmutability']={'status':'PASS' if same else 'FAIL','sourceFileCount':7,'storeFileCount':8}
                if not same:problems.append(('invalid',[side+'_inputs_changed_during_display_comparison']))
            except (quality.QualityInputError,quality.StoreError) as exc:
                result['checks'][side+'InputImmutability']={'status':'not-confirmed'}
                problems.append((getattr(exc,'category','invalid'),[exc.code]))
    limit=detail_limit if type(detail_limit) is int and 0<=detail_limit<=MAX_DETAIL_LIMIT else 0
    if problems:
        result['inputReadiness']=next(c for c in ('invalid','unavailable','incomparable') if any(p[0]==c for p in problems))
        result['comparisonStatus']='incomparable' if result['inputReadiness']=='incomparable' else 'failed'
        result['reasonCodes']=sorted({code for _,codes in problems for code in codes})
        result['findings']=[{'code':'context-mismatch' if 'context' in code else 'not-evaluable','reasonCodes':[code],'confirmedDifference':False} for code in result['reasonCodes']][:limit]
        result['baselineSummary']=result['candidateSummary']=None
        result['notEvaluated']=sorted(set(result['notEvaluated'])|{'basic-display-model-diff','detailed-display-state-diff'})
    elif compared is not None:
        result.update(compared);s=result['summary']
        result['comparisonStatus']='partial' if s['comparedCellCount'] else 'failed'
        if s['confirmedFindingCount']:result['displayDiffStatus']=result['basicDisplayDiffStatus']='changed'
        elif not s['notEvaluableCellCount'] and not s['ambiguousCellCount']:result['basicDisplayDiffStatus']='unchanged'
        ss=result['stateSummary']
        if ss['confirmedFindingCount']:result['displayDiffStatus']=result['stateDisplayDiffStatus']='changed'
        elif not ss['notEvaluableCellCount'] and not ss['inconsistencyCount']:result['stateDisplayDiffStatus']='unchanged'
        result['checks']['stateEvidence']={'status':'inconsistency' if ss['inconsistencyCount'] else 'partial' if ss['notEvaluableCellCount'] else 'PASS',
            'checkCount':ss['checkCount'],'inconsistencyCount':ss['inconsistencyCount']}
        if ss['notEvaluableCellCount']:result['notEvaluated'].append('some-display-state-features')
        if ss['inconsistencyCount']:result['notEvaluated'].append('inconsistent-display-state-evidence')
        if s['notEvaluableCellCount']:result['notEvaluated'].append('some-display-cells')
        if s['ambiguousCellCount']:result['notEvaluated'].append('semantic-duplicate-correspondence')
        if result['omittedDetails']:
            result['reasonCodes'].append('detail_limit_reached');result['notEvaluated'].append('omitted-display-diff-details')
    result['notEvaluated']=sorted(set(result['notEvaluated']))
    result['timings']['totalSeconds']=time.perf_counter()-started
    scale=1 if sys.platform=='darwin' else 1024
    result['resources']={'parentPeakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*scale,
                         'nodeChildrenPeakRssBytes':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss*scale}
    result['comparisonDigest']=comparison_digest(result)
    return result


def exit_code(result):
    if result['inputReadiness']=='invalid':return 3
    if result['inputReadiness']=='unavailable':return 4
    s=result['summary']
    if result['inputReadiness']!='ready' or s is None or not s['comparedCellCount'] or s['notEvaluableCellCount'] or s['ambiguousCellCount'] or result['omittedDetails']:return 2
    ss=result.get('stateSummary')
    if ss and (ss['notEvaluableCellCount'] or ss['inconsistencyCount']):return 2
    return 0


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('baseline-store','candidate-store','baseline-source-dir','candidate-source-dir'):p.add_argument('--'+flag,type=Path,required=True)
    a=p.parse_args(argv)
    r=compare_display_models(a.baseline_store,a.candidate_store,a.baseline_source_dir,a.candidate_source_dir)
    import json
    print('summary='+json.dumps(r['summary'],sort_keys=True))
    print('state_summary='+json.dumps(r.get('stateSummary'),sort_keys=True))
    print('display_summary='+json.dumps(r.get('displaySummary'),sort_keys=True))
    print('comparison_status='+r['comparisonStatus']+' display_diff_status='+r['displayDiffStatus']+' basic_display_diff_status='+r['basicDisplayDiffStatus'])
    print('not_evaluated='+','.join(r['notEvaluated']))
    print('reasons='+(','.join(r['reasonCodes']) or 'none'))
    print('comparison_digest='+r['comparisonDigest'])
    print('timings='+json.dumps(r['timings'],sort_keys=True));print('resources='+json.dumps(r['resources'],sort_keys=True))
    code=exit_code(r);print('exit_code='+str(code));return code


if __name__=='__main__':raise SystemExit(main())
