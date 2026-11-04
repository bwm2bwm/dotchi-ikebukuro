#!/usr/bin/env node
/** One private request on stdin, one JSON response on stdout. No source reads. */
import { webcrypto } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { buildV2QaBoard, validateV2Payload, validateQaState, ODPT_V2_QA_STATIONS } from '../_local_preview/odpt_v2_qa_adapter.mjs';
import { canonical, digest, exact, fail, nodeRuntime, requiredDates, validateContexts, parseRequestJson } from './odpt_display_contract.mjs';

const STATES=['running','not_started','ended','no_candidates','unknown','data_insufficient','start_unconfirmed','terminal_unconfirmed'];
const BASE=['items','groups','routeStates','serviceState','status','missingServiceDates','applicationPeriod','generatedAt'];
const NORMAL=[...BASE,'bestId','serviceDate','noValidArrival','noValidArrivalCount','otherUnknownCount','infoCount','candidateComparisonPartial'];
const CARD='id sourceId serviceDate routeId line color kind destination departureAtMs arrivalAtMs departureText arrivalText journeyKind transfer isBest isLastDeparture terminalBasis'.split(' ');
export function normalizeBoard(board, scenario) {
  const unavailable=board?.serviceState==='unavailable';
  exact(board,unavailable?BASE:NORMAL,'board_fields_invalid');
  if(!Array.isArray(board.items)||!Array.isArray(board.groups)||!Array.isArray(board.missingServiceDates)
    ||typeof board.status!=='string'||typeof board.generatedAt!=='string'||board.applicationPeriod!==null) fail('board_shape_invalid');
  if(unavailable) {
    if(board.items.length||board.groups.length||Object.keys(board.routeStates).length||!board.missingServiceDates.length) fail('board_unavailable_invalid');
    return {board,validationStatus:'unavailable',reasonCodes:['required_service_dates_missing'],
      candidateCount:0,cardCount:0,missingFields:NORMAL.filter(k=>!Object.hasOwn(board,k))};
  }
  if(!STATES.includes(board.serviceState)||typeof board.serviceDate!=='string'||board.missingServiceDates.length
    ||typeof board.noValidArrival!=='boolean'||typeof board.candidateComparisonPartial!=='boolean'
    ||['noValidArrivalCount','otherUnknownCount','infoCount'].some(k=>!Number.isSafeInteger(board[k])||board[k]<0)) fail('board_state_invalid');
  const index=new Map();
  for(const item of board.items) {
    exact(item,item.isBest?[...CARD,'bestLabel']:CARD,'board_card_fields_invalid');
    if(typeof item.id!=='string'||item.sourceId!==item.id||index.has(item.id)||!['6','9'].includes(item.routeId)
      ||!['direct','transfer'].includes(item.journeyKind)||typeof item.isBest!=='boolean'||typeof item.isLastDeparture!=='boolean'
      ||!Number.isSafeInteger(item.departureAtMs)||!Number.isSafeInteger(item.arrivalAtMs)||item.arrivalAtMs<item.departureAtMs
      ||['serviceDate','line','color','kind','destination','departureText','arrivalText'].some(k=>typeof item[k]!=='string')
      ||item.terminalBasis!==(scenario.directOnly?'direct_only':'all_reachable')
      ||(item.isBest&& !['● 最早着','● 表示候補内の最早着'].includes(item.bestLabel))) fail('board_card_invalid');
    if(item.journeyKind==='direct' ? item.transfer!==null : !item.transfer) fail('board_transfer_invalid');
    if(item.transfer) {
      exact(item.transfer,['station','waitSeconds','waitMinutes','outgoingRoute'],'board_transfer_invalid');
      if(typeof item.transfer.station!=='string'||typeof item.transfer.outgoingRoute!=='string'
        ||!Number.isSafeInteger(item.transfer.waitSeconds)||item.transfer.waitSeconds<60||item.transfer.waitSeconds>3600
        ||item.transfer.waitMinutes!==item.transfer.waitSeconds/60) fail('board_transfer_invalid');
    }
    index.set(item.id,item);
  }
  const expected=scenario.mode==='line' ? ['6','9'].map(r=>board.items.filter(i=>i.routeId===r).slice(0,3)).filter(a=>a.length)
    : [board.items.slice(0,6)].filter(a=>a.length);
  if(board.groups.length!==expected.length) fail('board_groups_invalid');
  board.groups.forEach((g,n)=>{
    exact(g,scenario.mode==='line'?['routeId','line','items']:['line','items'],'board_group_fields_invalid');
    if(JSON.stringify(stable(g.items))!==JSON.stringify(stable(expected[n])) || (scenario.mode==='departure'?g.line!==null:g.routeId!==g.items[0].routeId||g.line!==g.items[0].line)) fail('board_groups_invalid');
  });
  const marked=board.items.filter(i=>i.isBest);
  if(board.bestId===null ? marked.length!==0||board.items.length!==0 : marked.length!==1||marked[0].id!==board.bestId) fail('board_best_invalid');
  const dates=requiredDates(board.serviceDate+'T03:00:00Z');
  exact(board.routeStates,dates.flatMap(d=>['6','9'].map(r=>d+'|'+r)),'board_routes_invalid');
  for(const [key,s] of Object.entries(board.routeStates)) {
    exact(s,['serviceDate','routeId','state','candidateEligible','candidateCount','scheduledTripCount','noValidArrivalCount','otherUnknownCount','terminalKnown'],'board_route_fields_invalid');
    if(key!==s.serviceDate+'|'+s.routeId||!STATES.includes(s.state)||typeof s.terminalKnown!=='boolean'||typeof s.candidateEligible!=='boolean'
      ||['candidateCount','scheduledTripCount','noValidArrivalCount','otherUnknownCount'].some(k=>!Number.isSafeInteger(s[k])||s[k]<0)) fail('board_route_invalid');
  }
  const visible=board.groups.flatMap(g=>g.items);
  // IDs remain evidence local to this board; content keys are not train identities.
  const itemContentKeys=board.items.map(({id,sourceId,...value})=>digestForBoard(value));
  return {board,validationStatus:'validated',reasonCodes:[],missingFields:[],candidateCount:board.items.length,
    cardCount:visible.length,bestInGroups:visible.some(i=>i.id===board.bestId),
    displayedBestMarkCount:visible.filter(i=>i.isBest).length,itemContentKeys,
    terminalKnownByRouteDate:Object.fromEntries(Object.entries(board.routeStates).map(([k,v])=>[k,v.terminalKnown])),
    unknownRouteStateCount:Object.values(board.routeStates).filter(v=>['unknown','data_insufficient','start_unconfirmed','terminal_unconfirmed'].includes(v.state)).length};
}
// Board waitMinutes can be fractional, unlike context numeric values.
function stable(v) { if(Array.isArray(v))return v.map(stable); if(v&&typeof v==='object')return Object.fromEntries(Object.keys(v).sort().map(k=>[k,stable(v[k])])); if(typeof v==='number'&&!Number.isFinite(v))fail('board_number_invalid');return v; }
import { createHash } from 'node:crypto';
const digestForBoard=v=>createHash('sha256').update(JSON.stringify(stable(v))).digest('hex');
export async function runRequest(request) {
  if(Buffer.byteLength(JSON.stringify(request))>8*1024*1024)fail('request_size_limit');
  exact(request,['contract','schemaVersion','qualityContext','displayContext','expectedNodeRuntime','payload','qaState','observationInstant','displayScenario'],'request_fields_invalid');
  if(request.contract!=='odpt-display-adapter-request'||request.schemaVersion!==1) fail('request_contract_invalid');
  if(canonical(request.expectedNodeRuntime)!==canonical(nodeRuntime())) fail('node_runtime_mismatch');
  const c=validateContexts(request.displayContext,request.qualityContext);
  if(!c.observationInstants.includes(request.observationInstant)) fail('observation_not_in_context');
  const scenario=c.displayScenarios.find(s=>s.id===request.displayScenario?.id);
  if(!scenario||canonical(scenario)!==canonical(request.displayScenario)) fail('scenario_not_in_context');
  const dates=requiredDates(request.observationInstant);
  await validateV2Payload(request.payload,{stationId:request.payload?.stationId,serviceDates:dates,cryptoImpl:webcrypto});
  for(const day of request.payload.serviceDays)for(const row of day.departures) {
    for(const journey of [row.primary,row.directAlternative,row.bestTransferAlternative]) {
      if(journey?.transfer && journey.transfer.waitSeconds>request.qualityContext.maximumWaitSeconds) fail('quality_transfer_policy_mismatch');
    }
  }
  // Validate exactly the stations declared by the supplied state, including target membership.
  const stations=Object.keys(request.qaState?.stations??{});
  if(!stations.includes(request.payload.stationId)||stations.some(s=>!Object.hasOwn(ODPT_V2_QA_STATIONS,s))) fail('qa_station_set_invalid');
  validateQaState(request.qaState,stations,dates);
  const normalized=normalizeBoard(buildV2QaBoard(request.payload,request.qaState,{nowMs:Date.parse(request.observationInstant),
    horizonMs:scenario.horizonSeconds*1000,directOnly:scenario.directOnly,mode:scenario.mode}),scenario);
  const {generatedAt,...stableBoard}=normalized.board;
  return stable({contract:'odpt-display-adapter-response',schemaVersion:1,status:'ok',contextFingerprint:c.contextFingerprint,
    observationInstant:request.observationInstant,displayScenarioId:scenario.id,nodeRuntime:nodeRuntime(),
    ...normalized,boardDigest:digestForBoard(stableBoard),
    notEvaluated:['dom-presentation','visual-quality','publication-eligibility','source-snapshot-binding','candidate-byte-integrity']});
}
export async function main() {
  try {
    const chunks=[];let count=0;
    for await(const chunk of process.stdin) { count+=chunk.length;if(count>8*1024*1024)fail('request_size_limit');chunks.push(chunk); }
    const text=new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks));
    const result=await runRequest(parseRequestJson(text));
    process.stdout.write(JSON.stringify(result)+'\n');return 0;
  } catch(e) {
    const code=e.code&&/^[a-z][a-z0-9_]*$/.test(e.code)?e.code:'request_or_adapter_invalid';
    process.stdout.write(JSON.stringify({contract:'odpt-display-adapter-response',schemaVersion:1,status:'failed',reasonCodes:[code]})+'\n');
    process.stderr.write(code+'\n');return 2;
  }
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)process.exitCode=await main();
