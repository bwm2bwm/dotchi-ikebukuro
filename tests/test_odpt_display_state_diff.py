"""Synthetic boards through the unchanged JS adapter, then the Python comparator."""
import copy
import json
import subprocess
import unittest

from scripts import odpt_display_diff as diff
from scripts import odpt_display_state_diff as state
from tests.test_odpt_display_diff import evidence

INSTANT = '2026-10-29T03:00:00Z'
K = (INSTANT, 'Hikawadai', 'departure-all')
# No source files, API, public gate or browser are used by this fixture.
JS = r"""
import {buildV2QaBoard} from './_local_preview/odpt_v2_qa_adapter.mjs';
let text='';for await(const chunk of process.stdin)text+=chunk;
const o=JSON.parse(text),dates=o.dates;
const serviceDays=dates.map(serviceDate=>({serviceDate,routeCoverage:Object.fromEntries(['6','9'].map(r=>[r,
  {scheduledTripCount:10,dataState:o.coverage??'complete'}])),departures:['6','9'].flatMap(routeId=>
  (o.seconds??[12*3600+300,12*3600+600]).map((seconds,n)=>({id:`synthetic-${serviceDate}-${routeId}-${n}`,
    routeId,destination:'合成',displayType:'各駅停車',departureServiceSeconds:seconds,
    primary:{kind:'direct',departureServiceSeconds:seconds,arrivalServiceSeconds:seconds+600,transfer:null},
    directAlternative:o.noDirect?null:{kind:'direct',departureServiceSeconds:seconds,arrivalServiceSeconds:seconds+600,transfer:null},
    bestTransferAlternative:null})))}));
const payload={stationId:'Hikawadai',serviceDays,generatedAt:'2000-01-01T00:00:00Z'};
const qa={stations:{Hikawadai:Object.fromEntries(dates.map(d=>[d,{infoCount:o.info??0,
  noValidArrivalCount:o.unknown??0,otherUnknownCount:o.other??0}]))}};
process.stdout.write(JSON.stringify(buildV2QaBoard(payload,qa,{nowMs:Date.parse(o.instant),directOnly:o.directOnly??false,mode:o.mode??'departure'})));
"""


def board(instant=INSTANT, **opts):
    dates=diff.display.required_dates(instant)
    out=subprocess.run(['node','--input-type=module','-e',JS],cwd=diff.quality.ROOT,
        input=json.dumps(dict(instant=instant,dates=dates,**opts)),capture_output=True,text=True,check=True)
    return json.loads(out.stdout)


def compact(b, instant=INSTANT, **scenario):
    return state.compact_board(b,diff.display.required_dates(instant),{'directOnly':False,**scenario},diff.semantic_item)


def compare(a,b,instant=INSTANT,**kwargs):
    k=(instant,K[1],K[2])
    left,right=evidence(),evidence()
    left['stateEvidence']=a;right['stateEvidence']=b
    return diff.compare_cells({k:left},{k:right},[k],evaluate_states=True,**kwargs)


class DisplayStateDiffTests(unittest.TestCase):
    def test_all_known_route_states_and_no_candidates_are_observed(self):
        for opts,instant,expected in [({},INSTANT,'running'),({},'2026-10-29T01:00:00Z','not_started'),
            ({},'2026-10-29T06:00:00Z','ended'),({'seconds':[]},INSTANT,'no_candidates'),
            ({'coverage':'unknown'},INSTANT,'unknown'),({'coverage':'insufficient'},INSTANT,'data_insufficient'),
            ({'unknown':1},'2026-10-29T01:00:00Z','start_unconfirmed'),
            ({'unknown':1},'2026-10-29T06:00:00Z','terminal_unconfirmed')]:
            with self.subTest(expected=expected):
                c=compact(board(instant,**opts),instant)
                self.assertEqual(c['routes']['2026-10-29|6']['routeState']['value'],expected)
                r=compare(c,c,instant)
                self.assertEqual(r['stateSummary']['unchangedCellCount'],1)
                self.assertEqual(r['stateSummary']['inconsistencyCount'],0)
                self.assertFalse(r['stateDiffs']);self.assertFalse(r['findings'])

    def test_running_ended_service_and_certainty_transitions(self):
        running=compact(board());ended=compact(board(seconds=[11*3600]))
        r=compare(running,ended)
        self.assertEqual(r['summary']['changedCellCount'],0) # Basic scope is independent.
        self.assertEqual(r['displaySummary']['changedCellCount'],1)
        self.assertIn('route-state-changed',r['findings'][0]['classifications'])
        self.assertIn('service-state-changed',r['findings'][0]['classifications'])
        self.assertTrue(any(t['feature']=='serviceState' and t['transition']==['running','ended'] for t in r['stateTransitions']))
        reverse=compare(ended,running)
        self.assertTrue(any(t['transition']==['ended','running'] for t in reverse['stateTransitions']))
        unknown=compact(board(unknown=1))
        lost=compare(running,unknown);gained=compare(unknown,running)
        self.assertEqual(lost['stateSummary']['classificationCounts']['terminal-certainty-lost'],1)
        self.assertEqual(gained['stateSummary']['classificationCounts']['terminal-certainty-gained'],1)
        self.assertEqual(lost['stateSummary']['featureCounts']['terminalKnown']['changed'],6)
        self.assertTrue(all(f['qualityImpact']=='not-assessed' for f in lost['stateFindings']))

    def test_ended_to_unknown_and_insufficient_propagates_to_service(self):
        ended=compact(board(seconds=[3600]))
        for opts in ({'coverage':'unknown'},{'coverage':'insufficient'},{'unknown':1}):
            c=compact(board(seconds=[3600],**opts));r=compare(ended,c)
            self.assertEqual(r['stateSummary']['featureCounts']['serviceState']['changed'],1)
            self.assertNotEqual(c['serviceState']['value'],'data_insufficient')

    def test_start_gate_departure_exact_and_final_candidate_boundaries(self):
        for instant,expected,items in [('2026-10-29T02:59:59Z','not_started',0),
            ('2026-10-29T03:00:00Z','running',2),('2026-10-29T04:00:00Z','ended',0)]:
            b=board(instant,seconds=[13*3600]);c=compact(b,instant)
            self.assertEqual(len(b['items']),items)
            self.assertEqual(c['routes']['2026-10-29|6']['routeState']['value'],expected)
        for instant,expected in [('2026-10-29T03:09:59Z','running'),('2026-10-29T03:10:00Z','ended'),
                                 ('2026-10-29T03:10:01Z','ended')]:
            c=compact(board(instant),instant)
            self.assertEqual(c['routes']['2026-10-29|6']['routeState']['value'],expected)
        # Cross-generation shift at the SAME instant crosses the first-departure gate.
        r=compare(compact(board(seconds=[13*3600+1])),compact(board(seconds=[13*3600])))
        self.assertIn('start-guidance-changed',r['findings'][0]['classifications'])

    def test_terminal_labels_visibility_direct_filter_and_no_final_trip_matching(self):
        seconds=[12*3600+60*n for n in range(1,9)]
        b=board(seconds=seconds);c=compact(b)
        for route in ('6','9'):
            g=c['routes']['2026-10-29|'+route]['terminalGuidance']['value']
            self.assertEqual(g['terminalCandidateCount'],1)
            self.assertEqual(g['hiddenByCardLimitCount'],1)
            self.assertEqual(g['terminalCandidates'][0]['label'],'終電')
        direct=compact(board(seconds=seconds,directOnly=True),directOnly=True)
        self.assertEqual(direct['routes']['2026-10-29|6']['terminalGuidance']['value']['terminalCandidates'][0]['label'],'直通終電')
        self.assertTrue(compare(c,direct)['stateSummary']['featureCounts']['terminalGuidance']['changed'])
        # Selected terminal candidate exists and becomes visible as early cards depart.
        few=compact(board(seconds=seconds[-2:]))
        self.assertEqual(few['routes']['2026-10-29|6']['terminalGuidance']['value']['visibleTerminalCount'],1)
        self.assertTrue(compare(c,few)['stateSummary']['featureCounts']['terminalGuidance']['changed'])
        no_direct=compact(board(directOnly=True,noDirect=True),directOnly=True)
        self.assertEqual(no_direct['routes']['2026-10-29|6']['routeState']['value'],'no_candidates')

    def test_unknown_propagation_and_info_does_not_suppress(self):
        for instant,field in [('2026-10-29T01:00:00Z','startUnconfirmed'),('2026-10-29T06:00:00Z','terminalUnconfirmed')]:
            for opts in ({'unknown':1},{'other':1}):
                c=compact(board(instant,**opts),instant)
                for route in ('6','9'):
                    self.assertTrue(c['routes']['2026-10-29|'+route]['unknownSuppression']['value'][field])
                r=compare(compact(board(instant),instant),c,instant)
                affected=[d['dimensions'] for d in r['stateDiffs'] if d['feature']=='unknownSuppression']
                self.assertEqual(len(affected),6)
                self.assertEqual({d['routeId'] for d in affected},{'6','9'})
        c=compact(board(info=99));r=compare(compact(board()),c)
        self.assertFalse(r['findings']);self.assertEqual(c['auditEvidence']['infoCount'],99)
        self.assertTrue(all(e['terminalKnown']['value'] for e in c['routes'].values()))

    def test_coverage_unknown_and_qa_missing_are_distinct(self):
        coverage=compact(board(coverage='insufficient'))
        unknown=compact(board(unknown=1))
        v=coverage['routes']['2026-10-29|6']['unknownSuppression']['value']
        self.assertTrue(v['coverageUnconfirmed']);self.assertFalse(v['hasUnknown'])
        self.assertTrue(unknown['routes']['2026-10-29|6']['unknownSuppression']['value']['hasUnknown'])
        b=board();del b['routeStates']['2026-10-29|6']['noValidArrivalCount']
        r=compare(compact(board()),compact(b))
        self.assertEqual(r['stateSummary']['notEvaluableCellCount'],1)
        self.assertEqual(r['stateSummary']['featureCounts']['unknownSuppression']['not-evaluable'],1)
        self.assertEqual(r['stateSummary']['featureCounts']['terminalKnown']['unchanged'],6)

    def test_warning_exclusion_is_not_promoted_to_unknown_by_existing_qa_converter(self):
        days=diff.display.required_dates(INSTANT)
        rows=[]
        for day in days:
            reasons={reason:0 for reason in diff.collector.v2.EXCLUSION_REASONS}
            reasons.update(explicit_pass_info=2,quality_warning=3)
            rows.append(dict(stationId='Hikawadai',serviceDate=day,reasonCounts=reasons))
        manifest=dict(quality={'exclusionAudit':{'byStationDate':rows}},
            candidateFiles={'Hikawadai':{'path':diff.collector.v2.ROUTE_FILENAMES['Hikawadai'],'sha256':'0'*64,'bytes':1}})
        qa=diff.collector._qa_state(manifest,['Hikawadai'],days)['stations']['Hikawadai'][days[1]]
        self.assertEqual(qa,dict(infoCount=2,noValidArrivalCount=0,otherUnknownCount=0))
        c=compact(board(info=qa['infoCount'],unknown=qa['noValidArrivalCount'],other=qa['otherUnknownCount'],coverage='insufficient'))
        suppression=c['routes'][days[1]+'|6']['unknownSuppression']['value']
        self.assertFalse(suppression['hasUnknown']);self.assertTrue(suppression['coverageUnconfirmed'])

    def test_missing_route_envelope_unknown_values_keep_other_confirmed_changes(self):
        original=board();b=copy.deepcopy(original)
        del b['routeStates']['2026-10-28|6']
        b['routeStates']['2026-10-29|9']['terminalKnown']=False
        r=compare(compact(original),compact(b))
        self.assertEqual(r['stateSummary']['changedCellCount'],1)
        self.assertEqual(r['stateSummary']['notEvaluableCellCount'],1)
        missing=[d for d in r['stateDiffs'] if d['dimensions'].get('serviceDate')=='2026-10-28']
        self.assertTrue(all(d['candidateValue'] is None for d in missing))
        b=copy.deepcopy(original);b['routeStates']['2026-10-29|6']['state']='future_state'
        r=compare(compact(original),compact(b))
        raw=next(d for d in r['stateDiffs'] if d['feature']=='routeState')
        self.assertEqual(raw['candidateValue'],'future_state');self.assertFalse(raw['changed'])
        b=copy.deepcopy(original);b['missingServiceDates']=['2026-10-28']
        r=compare(compact(original),compact(b))
        self.assertEqual(r['stateSummary']['featureCounts']['dateBoundary']['not-evaluable'],1)
        self.assertEqual(r['stateSummary']['featureCounts']['serviceState']['not-evaluable'],1)

    def test_midnight_and_over_24h_service_date_retained_and_format_ignored(self):
        for instant in ('2026-10-29T14:59:59Z','2026-10-29T15:00:00Z'):
            b=board(instant,seconds=[24*3600+600]);c=compact(b,instant)
            mappings=c['dateBoundary']['value']['candidateDepartures']
            self.assertTrue(any(m['serviceDate']=='2026-10-29' and m['departureJstDate']=='2026-10-30' for m in mappings))
            self.assertEqual(c['dateBoundary']['value']['observationJstDate'],diff.display.required_dates(instant)[1])
            altered=copy.deepcopy(b)
            for i in altered['items']:i['departureText']='任意フォーマット';i['id']='new-'+i['id']
            # groups share the actual card objects in JS; Python clone IDs explicitly.
            for g in altered['groups']:
                for i in g['items']:i['id']='new-'+i['id']
            self.assertEqual(c,compact(altered,instant))

    def test_1000_detail_limit_counts_everything_and_determinism(self):
        a=compact(board());b=compact(board(unknown=1))
        keys=[(INSTANT,f's{i:04}',K[2]) for i in range(1024)]
        left={k:dict(evidence(),stateEvidence=a) for k in keys}
        right={k:dict(evidence(),stateEvidence=b) for k in reversed(keys)}
        r=diff.compare_cells(left,right,reversed(keys),evaluate_states=True)
        self.assertEqual(r['stateSummary']['changedCellCount'],1024)
        self.assertEqual(len(r['stateDiffs']),1000)
        self.assertEqual(len(r['stateTransitions']),1000)
        self.assertEqual(len(r['findings']),1000)
        self.assertEqual(r['omittedDetails']['stateFindings'],24)
        self.assertEqual(r,diff.compare_cells(left,right,keys,evaluate_states=True))
        self.assertEqual(diff.comparison_digest(r),diff.comparison_digest(copy.deepcopy(r)))
        self.assertEqual(diff.exit_code(dict(r,inputReadiness='ready')),2)
        same=diff.compare_cells(left,left,keys,evaluate_states=True)
        self.assertFalse(same['omittedDetails']);self.assertFalse(same['findings'])
        self.assertEqual(same['stateSummary']['unchangedCellCount'],1024)
        self.assertEqual(diff.exit_code(dict(same,inputReadiness='ready')),0)

    def test_inconsistent_propagation_not_silently_repaired_and_findings_deduplicated(self):
        a=board();b=copy.deepcopy(a)
        b['routeStates']['2026-10-29|6'].update(noValidArrivalCount=1,terminalKnown=False)
        r=compare(compact(a),compact(b))
        self.assertEqual(r['stateSummary']['inconsistentCellCount'],1)
        self.assertTrue(any(c['code']=='station-date-unknown-propagation' for c in r['stateChecks']))
        self.assertEqual(len(r['findings']),1)
        self.assertTrue(r['findings'][0]['confirmedDifference'])
        self.assertEqual(diff.exit_code(dict(r,inputReadiness='ready')),2)


if __name__=='__main__':unittest.main()
