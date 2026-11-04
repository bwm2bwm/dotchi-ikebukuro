#!/usr/bin/env node
/** Private single-cell DOM protocol. Payload bodies are IPC only, never CLI diagnostics. */
import { pathToFileURL } from 'node:url';
import { webcrypto } from 'node:crypto';
import { runRequest } from './odpt_display_runner.mjs';
import { canonical, digest, exact, fail, parseRequestJson } from './odpt_display_contract.mjs';
import { validateQaState, verifyCandidateBytes, serviceSecondsToEpochMs, ODPT_V2_QA_STATIONS, ODPT_V2_QA_FILES } from '../_local_preview/odpt_v2_qa_adapter.mjs';
import { withDom, assertBoardDom } from './odpt_dom_harness.mjs';

export const CONTRACT = 'odpt-dom-response';
export function observeDom(env) {
  const text = (node, selector) => node.querySelector(selector)?.textContent ?? null;
  return {
    groups: env.elements.get('board').querySelectorAll('.line').map(group => ({
      title: text(group, '.sectionlabel'), cards: group.querySelectorAll('.train').map(card => ({
        id: card.dataset.cardId, classes: [...card.classTokens].sort(), line: text(card, '.route'),
        kind: text(card, '.type-label'), destination: text(card, '.destination-label'),
        departure: text(card, '.time-value'), arrival: text(card, '.arrival'),
        serviceDate: text(card, '.service-date-label'), journey: text(card, '.sub'),
        best: text(card, '.bestmark'), terminal: text(card, '.terminal-badge'),
        countdown: text(card, '.count'), red: card.querySelector('.count').classList.contains('red'),
      })),
    })),
    status: env.elements.get('timetable-status').textContent,
    statusState: env.elements.get('timetable-status').dataset.state,
    coverage: env.elements.get('route-coverage').querySelectorAll('.coverage-state')
      .map(n => ({ text: n.textContent, state: n.dataset.state ?? null })),
    empty: text(env.elements.get('board'), '.empty'),
    mode: Object.fromEntries(['line','departure'].map(mode => [mode, {
      pressed: env.elements.get(`mode-${mode}`).getAttribute('aria-pressed'),
      selected: env.elements.get(`mode-${mode}`).classList.contains('sel'),
    }])),
    directOnly: env.elements.get('direct-only').checked,
  };
}

function checkProjection(r, board, nowMs) {
  for (const state of Object.values(board.routeStates)) {
    const day = r.payload.serviceDays.find(d => d.serviceDate === state.serviceDate);
    const coverage = day.routeCoverage[state.routeId];
    const candidates = day.departures.filter(row => row.routeId === state.routeId
      && (r.displayScenario.directOnly ? row.directAlternative : row.primary) !== null);
    const audit = r.qaState.stations[r.payload.stationId][state.serviceDate];
    const eligible = coverage.dataState === 'complete' && coverage.scheduledTripCount > 0;
    if (state.candidateEligible !== eligible || state.candidateCount !== candidates.length
      || state.terminalKnown !== (eligible && candidates.length > 0 && audit.noValidArrivalCount + audit.otherUnknownCount === 0)) fail('dom_projection_inconsistent');
  }
  for (const item of board.items) {
    const day = r.payload.serviceDays.find(d => d.serviceDate === item.serviceDate);
    const row = day.departures.find(row => row.id === item.id);
    const journey = r.displayScenario.directOnly ? row.directAlternative : row.primary;
    if (!journey || item.departureAtMs !== serviceSecondsToEpochMs(item.serviceDate,row.departureServiceSeconds)
      || item.arrivalAtMs !== serviceSecondsToEpochMs(item.serviceDate,journey.arrivalServiceSeconds)
      || item.journeyKind !== journey.kind || item.kind !== row.displayType || item.destination !== row.destination
      || !board.routeStates[`${item.serviceDate}|${item.routeId}`].candidateEligible
      || item.departureAtMs <= nowMs || item.departureAtMs > nowMs + r.displayScenario.horizonSeconds * 1000
      || nowMs < item.departureAtMs - 3600000
      || (journey.transfer && item.transfer?.waitSeconds !== journey.transfer.waitSeconds)) fail('dom_projection_inconsistent');
  }
}

export async function runDomRequest(request) {
  exact(request, ['contract','schemaVersion','adapterRequest','candidateText','stationId','nowMs'], 'dom_request_fields_invalid');
  if (request.contract !== 'odpt-dom-request' || request.schemaVersion !== 1) fail('dom_request_contract_invalid');
  const r = request.adapterRequest;
  if (typeof request.candidateText !== 'string' || !r || request.stationId !== r.payload?.stationId
      || !Number.isSafeInteger(request.nowMs) || request.nowMs !== Date.parse(r.observationInstant)) fail('dom_observation_mismatch');
  // Every station must have real caller-audited evidence; no synthetic missing-station fallback.
  validateQaState(r.qaState, Object.keys(ODPT_V2_QA_STATIONS), r.displayContext?.requiredServiceDates?.[r.observationInstant]);
  const bytes = new TextEncoder().encode(request.candidateText);
  await verifyCandidateBytes(bytes, r.qaState.candidateFiles[request.stationId], webcrypto);
  if (canonical(parseRequestJson(request.candidateText)) !== canonical(r.payload)) fail('dom_payload_bytes_mismatch');
  const adapterResponse = await runRequest(r);
  checkProjection(r, adapterResponse.board, request.nowMs);
  const files = new Map([[ODPT_V2_QA_FILES[request.stationId], bytes],
    ['_odpt_v2_qa_state.json', new TextEncoder().encode(JSON.stringify(r.qaState))]]);
  const scenario = r.displayScenario;
  const observation = await withDom(files, request.nowMs, async env => {
    if (env.elements.get('timetable-status').dataset.state === 'error') fail('dom_initialization_failed');
    env.elements.get(`mode-${scenario.mode}`).dispatch('click');
    env.elements.get('direct-only').checked = scenario.directOnly;
    env.elements.get('direct-only').dispatch('change');
    try { assertBoardDom(env, adapterResponse.board, request.nowMs, scenario.mode, scenario.directOnly); }
    catch { fail('dom_board_inconsistent'); }
    const audit = env.fetchAudit.filter(a => a.filename === ODPT_V2_QA_FILES[request.stationId]);
    if (audit.length !== 1 || canonical({bytes: audit[0].bytes, sha256: audit[0].sha256}) !== canonical(r.qaState.candidateFiles[request.stationId])) fail('dom_fetch_integrity_mismatch');
    return observeDom(env);
  }, { destination: request.stationId });
  const checks = Object.fromEntries(['candidateBytes','allStationQaState','adapterValidation','domInitialization',
    'v2BoardProjection','groupsAndCards','presentation','bestAndTerminal','routeNotifications','countdownAndScenario','cleanup'].map(k => [k,'PASS']));
  return { contract: CONTRACT, schemaVersion: 1, status: 'ok', stationId: request.stationId,
    observationInstant: r.observationInstant, scenarioId: scenario.id, nowMs: request.nowMs,
    adapterResponse, observation, observationDigest: digest(observation), checks };
}

export async function main() {
  try {
    const chunks = []; let size = 0;
    for await (const chunk of process.stdin) {
      size += chunk.length; if (size > 8 * 1024 * 1024) fail('request_size_limit'); chunks.push(chunk);
    }
    const result = await runDomRequest(parseRequestJson(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks))));
    const output = JSON.stringify(result);
    if (Buffer.byteLength(output) > 32 * 1024 * 1024) fail('response_size_limit');
    process.stdout.write(output + '\n'); return 0;
  } catch (error) {
    const code = /^[a-z][a-z0-9_]*$/.test(error.code ?? '') ? error.code : 'dom_request_or_runtime_invalid';
    process.stdout.write(JSON.stringify({contract:CONTRACT,schemaVersion:1,status:'failed',reasonCodes:[code]})+'\n');
    process.stderr.write(code+'\n'); return 2;
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) process.exitCode = await main();
