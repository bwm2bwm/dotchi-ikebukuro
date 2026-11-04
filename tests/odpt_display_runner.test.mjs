import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { webcrypto } from 'node:crypto';
import { runRequest, normalizeBoard } from '../scripts/odpt_display_runner.mjs';
import { digest, nodeRuntime, requiredDates, scenarios, parseRequestJson } from '../scripts/odpt_display_contract.mjs';
import { buildV2QaBoard, computeV2PublicId } from '../_local_preview/odpt_v2_qa_adapter.mjs';
const dates=['2026-10-28','2026-10-29','2026-10-30'];
const instant='2026-10-29T03:00:00Z'; // JST noon
const contexts=JSON.parse(execFileSync('python3',['-B','-c',
  "import json; from scripts import odpt_quality_input as q, odpt_display_context as d; c=q.initial_context('0'*64); print(json.dumps([c,d.create_context(c,['2026-10-29T03:00:00Z','2026-10-28T15:00:00Z'])]))"],{encoding:'utf8'}));
async function fixture({count=2,unknown=0,coverage='complete',seconds=12*3600+300,transfer=false}={}) {
  const serviceDays=[];
  for(const date of dates) {
    const departures=[];
    for(let n=0;n<count;n++) {
      const dep=seconds+n*60,routeId=n%2?'9':'6';
      const direct={kind:'direct',departureServiceSeconds:dep,arrivalServiceSeconds:dep+1200,transfer:null};
      const xfer={kind:'transfer',departureServiceSeconds:dep,arrivalServiceSeconds:dep+600,
        transfer:{stationId:'KotakeMukaihara',waitSeconds:90,outgoingRouteId:routeId==='6'?'9':'6'}};
      const row={routeId,destination:'合成行先',displayType:'各駅停車',departureServiceSeconds:dep,
        primary:transfer?xfer:direct,directAlternative:direct,bestTransferAlternative:transfer?xfer:null};
      row.id=await computeV2PublicId('Hikawadai',date,row,webcrypto);departures.push(row);
    }
    serviceDays.push({serviceDate:date,routeCoverage:{'6':{scheduledTripCount:10,dataState:coverage},'9':{scheduledTripCount:10,dataState:coverage}},departures});
  }
  const payload={schemaVersion:2,dataScope:'public-display-v2',generatedAt:'2000-01-01T00:00:00Z',timezone:'Asia/Tokyo',applicationPeriod:null,
    stationId:'Hikawadai',originStationId:'Ikebukuro',serviceDays};
  return {contract:'odpt-display-adapter-request',schemaVersion:1,qualityContext:structuredClone(contexts[0]),displayContext:structuredClone(contexts[1]),
    expectedNodeRuntime:nodeRuntime(),payload,qaState:{schemaVersion:1,dataScope:'private-local-odpt-v2-qa-state',serviceDates:dates,
      stations:{Hikawadai:Object.fromEntries(dates.map(d=>[d,{infoCount:0,noValidArrivalCount:unknown,otherUnknownCount:0}]))},
      candidateFiles:{Hikawadai:{sha256:'0'.repeat(64),bytes:1}}},observationInstant:instant,displayScenario:scenarios[0]};
}
function clock(r,i) { r.observationInstant=i;r.displayContext.observationInstants=[i];r.displayContext.requiredServiceDates={[i]:requiredDates(i)};
  const {contextFingerprint,...body}=r.displayContext;r.displayContext.contextFingerprint=digest(body); }
async function ids(r) { for(const d of r.payload.serviceDays)for(const row of d.departures)row.id=await computeV2PublicId('Hikawadai',d.serviceDate,row,webcrypto); }

test('four scenarios and deterministic output; best and candidate/card counts',async()=>{
  const r=await fixture({count:10});
  for(const s of scenarios) {r.displayScenario=s;const out=await runRequest(r);assert.equal(out.candidateCount,10);assert.equal(out.cardCount,6);assert.equal(out.displayedBestMarkCount,1);assert.equal(out.bestInGroups,true);
    assert.deepEqual(out,await runRequest(structuredClone(r)));}
});
test('directAlternative changes arrival and kind without inventing a new ID',async()=>{
  const r=await fixture({transfer:true});const all=await runRequest(r);r.displayScenario=scenarios[1];const direct=await runRequest(r);
  assert.equal(all.board.items[0].journeyKind,'transfer');assert.equal(direct.board.items[0].journeyKind,'direct');
  assert.equal(direct.board.items[0].id,all.board.items[0].id);assert.equal(direct.board.items[0].arrivalAtMs-all.board.items[0].arrivalAtMs,600000);
});
test('each candidate has a 60 minute gate, inclusive start, exclusive departure',async()=>{
  const r=await fixture({count:1,seconds:13*3600});
  for(const [i,n] of [['2026-10-29T02:59:59Z',0],['2026-10-29T03:00:00Z',1],['2026-10-29T04:00:00Z',0]]) {
    clock(r,i);assert.equal((await runRequest(r)).candidateCount,n);
  }
});
test('24 and 25 hour service times retain previous serviceDate',async()=>{
  for(const hour of [24,25]) {const r=await fixture({count:1,seconds:hour*3600+600});clock(r,`2026-10-28T${hour===24?'15':'16'}:00:00Z`);
    const out=await runRequest(r);assert.equal(out.board.items[0].serviceDate,'2026-10-28');
    assert.equal(out.board.items[0].departureAtMs,Date.parse(`2026-10-29T0${hour-24}:10:00+09:00`));}
});
test('earliest arrival tie prefers earlier departure; best can be outside groups',async()=>{
  const r=await fixture({count:8});let day=r.payload.serviceDays[1];
  day.departures[0].primary.arrivalServiceSeconds=day.departures[1].primary.arrivalServiceSeconds;
  await ids(r);assert.equal((await runRequest(r)).board.bestId,day.departures[0].id);
  day.departures[7].primary.arrivalServiceSeconds=day.departures[7].departureServiceSeconds;
  await ids(r);const out=await runRequest(r);assert.equal(out.board.bestId,day.departures[7].id);assert.equal(out.bestInGroups,false);assert.equal(out.displayedBestMarkCount,0);
});
test('route states, UNKNOWN start/terminal suppression, known empty versus unavailable',async()=>{
  for(const [opts,i,state,terminal] of [
    [{},instant,'running',true],[{},'2026-10-29T01:00:00Z','not_started',true],[{},'2026-10-29T06:00:00Z','ended',true],
    [{unknown:1},'2026-10-29T01:00:00Z','start_unconfirmed',false],[{unknown:1},'2026-10-29T06:00:00Z','terminal_unconfirmed',false],
    [{coverage:'unknown'},instant,'unknown',false],[{coverage:'insufficient'},instant,'data_insufficient',false],[{count:0},instant,'no_candidates',false]]) {
    const r=await fixture(opts);clock(r,i);const out=await runRequest(r);assert.equal(out.board.routeStates['2026-10-29|6'].state,state);assert.equal(out.terminalKnownByRouteDate['2026-10-29|6'],terminal);
    assert.equal(out.validationStatus,'validated');
  }
  const r=await fixture();r.payload.serviceDays.pop();await assert.rejects(runRequest(r),/service_days_invalid/);
  const raw=buildV2QaBoard(r.payload,r.qaState,{nowMs:Date.parse(instant)});const out=normalizeBoard(raw,scenarios[0]);
  assert.equal(out.validationStatus,'unavailable');assert.ok(out.missingFields.includes('bestId'));assert.ok(!Object.hasOwn(out,'bestInGroups'));
});
test('bad schema, runtime, fingerprints, dates, state and board are rejected',async()=>{
  const r=await fixture();
  for(const change of [r=>r.extra=true,r=>r.expectedNodeRuntime.versions.icu='other',r=>r.displayContext.contextFingerprint='a'.repeat(64),
    r=>r.qualityContext.contextFingerprint='a'.repeat(64),r=>r.qaState.stations.Hikawadai[dates[0]].infoCount=-1,
    r=>r.payload.serviceDays[0].serviceDate='2026-10-27',r=>r.displayScenario.cardLimit=9]) {
    const x=structuredClone(r);change(x);await assert.rejects(runRequest(x));
  }
  const board=buildV2QaBoard(r.payload,r.qaState,{nowMs:Date.parse(instant)});delete board.bestId;assert.throws(()=>normalizeBoard(board,scenarios[0]));
});
test('CLI emits only protocol JSON and safe fixed diagnostics',async()=>{
  const r=await fixture();const out=spawnSync('node',['scripts/odpt_display_runner.mjs'],{input:JSON.stringify(r),encoding:'utf8'});
  assert.equal(out.status,0);assert.equal(out.stderr,'');assert.equal(JSON.parse(out.stdout).status,'ok');
  const bad=spawnSync('node',['scripts/odpt_display_runner.mjs'],{input:'{"secret":"DO_NOT_ECHO"}',encoding:'utf8'});
  assert.equal(bad.status,2);assert.ok(!bad.stderr.includes('DO_NOT_ECHO'));assert.equal(JSON.parse(bad.stdout).status,'failed');
});

test('JSON transport rejects duplicate keys and nested resource abuse',()=>{
  assert.throws(()=>parseRequestJson('{"x":1,"x":2}'),/request_json_duplicate_key/);
  assert.throws(()=>parseRequestJson('['.repeat(66)+'0'+']'.repeat(66)),/request_depth_limit/);
  assert.throws(()=>parseRequestJson('{"x":1,}'));
  assert.deepEqual(JSON.parse(JSON.stringify(parseRequestJson('{"x":[true,null,"字\\\"列"]}'))),{x:[true,null,'字"列']});
});
