import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { buildV2QaBoard, computeV2PublicId, ODPT_V2_QA_STATIONS,
  ODPT_V2_QA_STATE_SCOPE, parseJstInput, serviceSecondsToEpochMs, validateQaState, validateV2Payload,
  verifyCandidateBytes } from '../_local_preview/odpt_v2_qa_adapter.mjs';

const dates = ['2026-10-28', '2026-10-29', '2026-10-30'];
const ROUTES = ['6', '9'];
function jst(value) { return Date.parse(`${value}+09:00`); }

async function row(stationId, serviceDate, { routeId = '6', kind = 'direct', departure = 6 * 3600,
  arrival = departure + 20 * 60, direct = true } = {}) {
  const journey = kind === 'direct'
    ? { kind, departureServiceSeconds: departure, arrivalServiceSeconds: arrival, transfer: null }
    : { kind, departureServiceSeconds: departure, arrivalServiceSeconds: arrival,
      transfer: { stationId: 'KotakeMukaihara', waitSeconds: 180,
        outgoingRouteId: routeId === '6' ? '9' : '6' } };
  const directJourney = direct ? { kind: 'direct', departureServiceSeconds: departure,
    arrivalServiceSeconds: arrival + 5 * 60, transfer: null } : null;
  const transferJourney = kind === 'transfer' ? journey : null;
  const value = { routeId, destination: '森林公園', displayType: '各駅停車',
    departureServiceSeconds: departure, primary: journey,
    directAlternative: kind === 'direct' ? journey : directJourney,
    bestTransferAlternative: transferJourney };
  value.id = await computeV2PublicId(stationId, serviceDate, value, webcrypto);
  return value;
}

async function payload(stationId = 'Hikawadai', serviceDateSet = dates) {
  const serviceDays = [];
  for (const serviceDate of serviceDateSet) {
    const direct = await row(stationId, serviceDate, { routeId: '6', departure: 6 * 3600 });
    const transfer = await row(stationId, serviceDate, { routeId: '9', kind: 'transfer',
      departure: 6 * 3600 + 300, arrival: 6 * 3600 + 45 * 60, direct: false });
    serviceDays.push({ serviceDate,
      routeCoverage: { '6': { scheduledTripCount: 439, dataState: 'complete' },
        '9': { scheduledTripCount: 500, dataState: 'complete' } },
      departures: [direct, transfer] });
  }
  return { schemaVersion: 2, dataScope: 'public-display-v2', generatedAt: '2026-10-29T12:00:00Z',
    timezone: 'Asia/Tokyo', applicationPeriod: null, stationId, originStationId: 'Ikebukuro', serviceDays };
}

function qaState(unknownDate = null, unknownCount = 0, serviceDateSet = dates) {
  const stations = Object.fromEntries(Object.keys(ODPT_V2_QA_STATIONS).map(stationId => [stationId,
    Object.fromEntries(serviceDateSet.map(serviceDate => [serviceDate, {
      infoCount: 0,
      noValidArrivalCount: stationId === 'Hikawadai' && serviceDate === unknownDate ? unknownCount : 0,
      otherUnknownCount: 0,
    }]))]));
  const candidateFiles = Object.fromEntries(Object.keys(ODPT_V2_QA_STATIONS).map(stationId => [stationId,
    { sha256: 'a'.repeat(64), bytes: 1 }]));
  return { schemaVersion: 1, dataScope: ODPT_V2_QA_STATE_SCOPE, serviceDates: serviceDateSet, stations, candidateFiles };
}

test('v2 validator requires explicit profile, exact schema, dates, and recomputed public IDs', async () => {
  const source = await payload();
  await assert.doesNotReject(validateV2Payload(source, { stationId: 'Hikawadai', serviceDates: dates, cryptoImpl: webcrypto }));
  const wrongProfile = structuredClone(source);
  wrongProfile.dataScope = 'public-display-v1';
  await assert.rejects(validateV2Payload(wrongProfile, { stationId: 'Hikawadai', serviceDates: dates, cryptoImpl: webcrypto }), /profile_invalid/);
  const extra = structuredClone(source);
  extra.private = true;
  await assert.rejects(validateV2Payload(extra, { stationId: 'Hikawadai', serviceDates: dates, cryptoImpl: webcrypto }), /payload_fields_invalid/);
  const tampered = structuredClone(source);
  tampered.serviceDays[0].departures[0].destination = '改ざん';
  await assert.rejects(validateV2Payload(tampered, { stationId: 'Hikawadai', serviceDates: dates, cryptoImpl: webcrypto }), /public_id_mismatch/);
});

test('v2 validator rejects missing dates, duplicate IDs, invalid times, and transfer errors', async () => {
  const missing = structuredClone(await payload());
  missing.serviceDays.pop();
  await assert.rejects(validateV2Payload(missing, { stationId: 'Hikawadai', serviceDates: dates, cryptoImpl: webcrypto }), /service_days_invalid/);
  const badTime = structuredClone(await payload());
  badTime.serviceDays[0].departures[0].primary.arrivalServiceSeconds = -1;
  await assert.rejects(validateV2Payload(badTime, { stationId: 'Hikawadai', serviceDates: dates, cryptoImpl: webcrypto }), /primary_invalid/);
  const badTransfer = structuredClone(await payload());
  badTransfer.serviceDays[0].departures[1].bestTransferAlternative.transfer.waitSeconds = 9999;
  await assert.rejects(validateV2Payload(badTransfer, { stationId: 'Hikawadai', serviceDates: dates, cryptoImpl: webcrypto }), /primary_transfer_invalid/);
  const duplicate = structuredClone(await payload());
  duplicate.serviceDays[0].departures[1].id = duplicate.serviceDays[0].departures[0].id;
  await assert.rejects(validateV2Payload(duplicate, { stationId: 'Hikawadai', serviceDates: dates, cryptoImpl: webcrypto }), /departure_invalid/);
  const badCoverage = structuredClone(await payload());
  badCoverage.serviceDays[0].routeCoverage['6'].dataState = 'complete-ish';
  await assert.rejects(validateV2Payload(badCoverage, { stationId: 'Hikawadai', serviceDates: dates, cryptoImpl: webcrypto }), /route_coverage_invalid/);
});

test('service seconds preserve JST service dates after midnight and through 25:xx', () => {
  assert.equal(serviceSecondsToEpochMs('2026-10-28', 24 * 3600 + 10 * 60), jst('2026-10-29T00:10:00'));
  assert.equal(serviceSecondsToEpochMs('2026-10-28', 25 * 3600 + 30 * 60), jst('2026-10-29T01:30:00'));
});

test('JST virtual datetime accepts optional seconds and rejects invalid calendar/time values', () => {
  const expected = Date.parse('2026-10-28T20:30:00Z');
  assert.equal(parseJstInput('2026-10-29T05:30'), expected);
  assert.equal(parseJstInput('2026-10-29T05:30:00'), expected);
  assert.equal(new Date(parseJstInput('2026-10-29T05:30')).toISOString(), '2026-10-28T20:30:00.000Z');
  for (const invalid of ['2026-02-29T05:30', '2026-10-29T24:00', '2026-10-29T05:60',
    '2026-10-29T05:30:60', '2026/10/29 05:30:00', '']) {
    assert.equal(parseJstInput(invalid), null, invalid);
  }
});

test('candidate byte count and SHA-256 are checked before normalization', async () => {
  const bytes = new TextEncoder().encode('{"qa":true}');
  const sha256 = Buffer.from(await webcrypto.subtle.digest('SHA-256', bytes)).toString('hex');
  assert.equal(await verifyCandidateBytes(bytes, { bytes: bytes.length, sha256 }, webcrypto), true);
  await assert.rejects(verifyCandidateBytes(bytes, { bytes: bytes.length + 1, sha256 }, webcrypto), /candidate_bytes_mismatch/);
  await assert.rejects(verifyCandidateBytes(bytes, { bytes: bytes.length, sha256: '0'.repeat(64) }, webcrypto), /candidate_hash_mismatch/);
});

test('board selects destination journeys, direct-only alternative, ordering, and earliest arrival', async () => {
  const source = await payload();
  const board = buildV2QaBoard(source, qaState(), { nowMs: jst('2026-10-29T05:30:00'), mode: 'departure' });
  assert.ok(board.items.length > 0);
  assert.equal(board.items[0].id, source.serviceDays[1].departures[0].id);
  assert.equal(board.bestId, source.serviceDays[1].departures[0].id);
  assert.equal(board.items[0].line, '有楽町線');
  const direct = buildV2QaBoard(source, qaState(), { nowMs: jst('2026-10-29T05:30:00'), directOnly: true });
  assert.ok(direct.items.every(item => item.journeyKind === 'direct'));
  assert.ok(direct.items.every(item => item.id.startsWith('p2-')));
  const lineMode = buildV2QaBoard(source, qaState(), { nowMs: jst('2026-10-29T05:30:00'), mode: 'line' });
  assert.deepEqual(lineMode.groups.map(group => group.line), ['有楽町線', '副都心線']);
});

test('unknown or insufficient route coverage hides only that route while complete route cards remain', async () => {
  const source = await payload();
  source.serviceDays[1].routeCoverage['9'].dataState = 'unknown';
  const unknownRoute = buildV2QaBoard(source, qaState(), { nowMs: jst('2026-10-29T05:30:00') });
  assert.equal(unknownRoute.routeStates['2026-10-29|9'].state, 'unknown');
  assert.ok(unknownRoute.items.every(item => item.routeId !== '9'));
  const insufficientSource = await payload();
  insufficientSource.serviceDays[1].routeCoverage['6'].dataState = 'insufficient';
  const insufficientRoute = buildV2QaBoard(insufficientSource, qaState(), { nowMs: jst('2026-10-29T05:30:00') });
  assert.equal(insufficientRoute.routeStates['2026-10-29|6'].state, 'data_insufficient');
  assert.ok(insufficientRoute.items.every(item => item.routeId !== '6' || item.serviceDate !== '2026-10-29'));

  const withUnknownExclusion = buildV2QaBoard(await payload(), qaState('2026-10-29', 4),
    { nowMs: jst('2026-10-29T05:30:00') });
  assert.equal(withUnknownExclusion.noValidArrival, true);
  assert.match(withUnknownExclusion.status, /no_valid_arrival UNKNOWN 4件.*検証済み候補.*両路線の終電は未確認/);
  assert.equal(withUnknownExclusion.routeStates['2026-10-29|6'].state, 'running');
  assert.equal(withUnknownExclusion.routeStates['2026-10-29|9'].state, 'running');
  assert.ok(withUnknownExclusion.items.some(item => item.routeId === '6' && item.serviceDate === '2026-10-29'));
  assert.ok(withUnknownExclusion.items.some(item => item.routeId === '9' && item.serviceDate === '2026-10-29'));
  assert.ok(withUnknownExclusion.items.every(item => !item.isLastDeparture));
  assert.equal(withUnknownExclusion.items.find(item => item.isBest)?.bestLabel, '● 表示候補内の最早着');
  const unknownDirectOnly = buildV2QaBoard(await payload(), qaState('2026-10-29', 4),
    { nowMs: jst('2026-10-29T05:30:00'), directOnly: true });
  assert.ok(unknownDirectOnly.items.every(item => item.journeyKind === 'direct'));
  assert.equal(unknownDirectOnly.items.find(item => item.isBest)?.bestLabel, '● 表示候補内の最早着');
  const unknownLineMode = buildV2QaBoard(await payload(), qaState('2026-10-29', 4),
    { nowMs: jst('2026-10-29T05:30:00'), mode: 'line' });
  assert.deepEqual(unknownLineMode.groups.map(group => group.line), ['有楽町線', '副都心線']);
  assert.equal(unknownLineMode.groups.flatMap(group => group.items).find(item => item.isBest)?.bestLabel,
    '● 表示候補内の最早着');

  const afterKnownCandidates = buildV2QaBoard(await payload(), qaState('2026-10-29', 4),
    { nowMs: jst('2026-10-29T06:30:00'), horizonMs: 60 * 60 * 1000 });
  assert.equal(afterKnownCandidates.serviceState, 'terminal_unconfirmed');
  assert.equal(afterKnownCandidates.routeStates['2026-10-29|6'].state, 'terminal_unconfirmed');
  assert.equal(afterKnownCandidates.routeStates['2026-10-29|9'].state, 'terminal_unconfirmed');
  assert.equal(afterKnownCandidates.items.length, 0);
});

test('explicit pass-through INFO does not block complete route terminal status', async () => {
  const state = qaState();
  state.stations.Hikawadai['2026-10-29'].infoCount = 68;
  const board = buildV2QaBoard(await payload(), state, { nowMs: jst('2026-10-29T05:30:00') });
  assert.equal(board.noValidArrival, false);
  assert.equal(board.infoCount, 68);
  assert.equal(board.routeStates['2026-10-29|6'].state, 'running');
  assert.equal(board.items.find(item => item.routeId === '6' && item.serviceDate === '2026-10-29')?.isLastDeparture, true);
  assert.equal(board.items.find(item => item.isBest)?.bestLabel, '● 最早着');
});

test('UNKNOWN state refreshes by destination and service date without persisting an old warning', async () => {
  const hikawadai = buildV2QaBoard(await payload('Hikawadai'), qaState('2026-10-29', 4),
    { nowMs: jst('2026-10-29T05:30:00') });
  assert.equal(hikawadai.noValidArrival, true);
  assert.match(hikawadai.status, /終電は未確認/);

  const senkawa = buildV2QaBoard(await payload('Senkawa'), qaState('2026-10-29', 4),
    { nowMs: jst('2026-10-29T05:30:00') });
  assert.equal(senkawa.noValidArrival, false);
  assert.doesNotMatch(senkawa.status, /UNKNOWN|未確認/);

  const shiftedDates = ['2026-10-27', '2026-10-28', '2026-10-29'];
  const previousDay = buildV2QaBoard(await payload('Hikawadai', shiftedDates),
    qaState('2026-10-29', 4, shiftedDates), { nowMs: jst('2026-10-28T05:30:00') });
  assert.equal(previousDay.serviceDate, '2026-10-28');
  assert.equal(previousDay.noValidArrival, false);
  assert.doesNotMatch(previousDay.status, /UNKNOWN|未確認/);
});

test('missing virtual-clock service dates fail closed rather than claiming ended service', async () => {
  const board = buildV2QaBoard(await payload(), qaState(), { nowMs: jst('2026-11-15T12:00:00') });
  assert.equal(board.serviceState, 'unavailable');
  assert.equal(board.items.length, 0);
  assert.equal(board.applicationPeriod, null);
});

