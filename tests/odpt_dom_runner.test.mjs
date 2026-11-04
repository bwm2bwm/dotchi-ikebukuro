import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { configuredBundle } from './odpt_dom_fixture.mjs';
import { runDomRequest } from '../scripts/odpt_dom_runner.mjs';
import { withDom, assertBoardDom } from '../scripts/odpt_dom_harness.mjs';
import { ODPT_V2_QA_FILES } from '../_local_preview/odpt_v2_qa_adapter.mjs';
import { nodeRuntime, digest } from '../scripts/odpt_display_contract.mjs';
const instant = '2026-10-29T03:00:00Z';
const contexts = JSON.parse(execFileSync('python3', ['-B','-c',
  "import json; from scripts import odpt_quality_input as q, odpt_display_context as d; c=q.initial_context('0'*64); print(json.dumps([c,d.create_context(c,['2026-10-29T03:00:00Z'])]))"], {encoding:'utf8'}));
async function fixture(options = {}, time = instant) {
  const files = await configuredBundle(options);
  const decode = name => JSON.parse(new TextDecoder().decode(files.get(name)));
  const d = structuredClone(contexts[1]);
  d.observationInstants = [time];
  // These test instants remain on Oct29 JST, retaining the same required dates.
  d.requiredServiceDates = {[time]: ['2026-10-28','2026-10-29','2026-10-30']};
  const {contextFingerprint,...body} = d; d.contextFingerprint = digest(body);
  const adapterRequest = {contract:'odpt-display-adapter-request',schemaVersion:1,
    qualityContext:contexts[0],displayContext:d,expectedNodeRuntime:nodeRuntime(),
    payload:decode(ODPT_V2_QA_FILES.Hikawadai),qaState:decode('_odpt_v2_qa_state.json'),
    observationInstant:time,displayScenario:d.displayScenarios[0]};
  return {request:{contract:'odpt-dom-request',schemaVersion:1,adapterRequest,
    candidateText:new TextDecoder().decode(files.get(ODPT_V2_QA_FILES.Hikawadai)),stationId:'Hikawadai',nowMs:Date.parse(time)},files};
}

test('four scenarios use identical candidate bytes; alternatives, caps and deterministic observations', async () => {
  const {request} = await fixture();
  const results = [];
  for (const scenario of request.adapterRequest.displayContext.displayScenarios) {
    request.adapterRequest.displayScenario = scenario;
    const a = await runDomRequest(request); const b = await runDomRequest(request);
    assert.deepEqual(a,b); assert.equal(a.observation.groups.flatMap(g=>g.cards).length,6);
    assert.ok(a.adapterResponse.candidateCount > 6);
    assert.equal(Object.keys(request.adapterRequest.qaState.stations).length,8);
    assert.ok(Object.values(a.checks).every(v=>v==='PASS'));
    results.push(a);
  }
  assert.notEqual(results[0].observation.groups[0].cards[0].arrival, results[1].observation.groups[0].cards[0].arrival);
});

test('all eight state entries, candidate bytes/hash/object and fixed instant are mandatory', async () => {
  const {request} = await fixture({count:1});
  for (const mutate of [
    r=>delete r.adapterRequest.qaState.stations.Wakoshi,
    r=>r.candidateText+=' ', r=>r.adapterRequest.payload.stationId='Senkawa',
    r=>r.adapterRequest.payload.serviceDays[0].departures[0].destination='changed',
    r=>r.nowMs+=1,
    r=>delete r.adapterRequest.qaState.stations.Hikawadai['2026-10-28'],
  ]) {const r=structuredClone(request);mutate(r);await assert.rejects(runDomRequest(r));}
});

for (const [name, options] of [['hidden best',{hiddenBest:true}],['UNKNOWN',{count:1,unknown:2}],
  ['INFO',{count:1,info:3}],['coverage',{count:1,coverage:'insufficient'}],['known zero',{count:0}]]) {
  test(`DOM runner observes ${name}`,async()=>{
    const {request}=await fixture(options);const r=await runDomRequest(request);
    const cards=r.observation.groups.flatMap(g=>g.cards);
    if(name==='hidden best') {assert.equal(r.adapterResponse.bestInGroups,false);assert.ok(cards.every(c=>!c.best));}
    if(name==='UNKNOWN') {assert.equal(r.observation.statusState,'warning');assert.ok(cards.every(c=>!c.terminal));}
    if(name==='INFO') {assert.equal(r.observation.statusState,'ok');assert.match(r.observation.coverage.at(-1).text,/INFO 3件/);}
    if(name==='coverage'||name==='known zero') assert.equal(cards.length,0);
  });
}

test('terminal/first departure, 24h serviceDate and fixed countdown stay connected',async()=>{
  for(const [time,opts,state] of [[instant,{count:1},'running'],
    ['2026-10-29T01:00:00Z',{count:1},'not_started'],
    ['2026-10-29T06:00:00Z',{count:1},'ended'],
    ['2026-10-28T15:00:00Z',{count:1,departure:87000},'running']]) {
    const {request}=await fixture(opts,time);const r=await runDomRequest(request);
    assert.equal(r.adapterResponse.board.serviceState,state);
    const cards=r.observation.groups.flatMap(g=>g.cards);
    if(time===instant) {assert.equal(cards[0].countdown,'01:00');assert.equal(cards[0].red,true);assert.equal(cards[0].terminal,'終電');}
    if(opts.departure) {assert.equal(cards[0].serviceDate,'運行日 2026-10-28');assert.equal(cards[0].departure,'00:10');}
  }
});

test('DOM mismatch is rejected by the shared checker and globals are restored',async()=>{
  const {request,files}=await fixture({count:1}); const r=await runDomRequest(request);
  const before=Date.now;
  await assert.rejects(withDom(files,request.nowMs,async env=>{
    env.elements.get('board').replaceChildren();
    assertBoardDom(env,r.adapterResponse.board,request.nowMs);
  }));
  assert.equal(Date.now,before);
});

test('CLI is a bounded protocol and never echoes invalid request bodies',()=>{
  for(const raw of ['{"secret":"DO_NOT_ECHO"}','{"x":1,"x":2}','bad json']) {
    const p=spawnSync('node',['scripts/odpt_dom_runner.mjs'],{input:raw,encoding:'utf8'});
    assert.equal(p.status,2);assert.equal(JSON.parse(p.stdout).status,'failed');
    assert.ok(!p.stderr.includes('DO_NOT_ECHO'));assert.match(p.stderr,/^[a-z][a-z0-9_]*\n$/);
  }
});
