import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import {
  buildBoard,
  LOCAL_DATA_SCOPE,
  prepareTimetablePayload,
  PUBLIC_DATA_SCOPE,
} from '../scripts/timetable_adapter.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SCRIPT_DIR = path.join(ROOT, 'scripts');
const JST = value => new Date(`${value}+09:00`).getTime();

function serviceTime(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
}

function journey(kind, departureSeconds, arrivalSeconds, destinationId, routeId) {
  const transfer = kind === 'transfer' ? {
    stationId: 'KotakeMukaihara',
    stationName: '小竹向原',
    waitSeconds: 120,
    outgoingRouteId: routeId === '6' ? '9' : '6',
    outgoingRouteName: routeId === '6' ? '副都心線' : '有楽町線',
    outgoingHeadsign: '和光市',
    outgoingTrainType: 'Local',
    outgoingReportedTrainType: 'Local',
    outgoingServiceBrand: null,
    outgoingTypeLabel: '各駅停車',
    outgoingDestinationIds: [],
    outgoingOdptTrainTypeUri: 'synthetic-raw-uri-to-drop',
  } : null;
  return {
    kind,
    departureServiceSeconds: departureSeconds,
    arrivalServiceSeconds: arrivalSeconds,
    departureText: serviceTime(departureSeconds),
    arrivalText: serviceTime(arrivalSeconds),
    arrivalStationId: destinationId,
    transfer,
    platformStatus: 'unknown',
    connectionGuaranteed: false,
    internalDiagnostic: 'synthetic-only-diagnostic-to-drop',
  };
}

function departure({ id, routeId, seconds, arrival, destinationId, kind = 'direct' }) {
  const mainJourney = journey(kind, seconds, arrival, destinationId, routeId);
  const direct = kind === 'direct' ? mainJourney : null;
  const transfer = kind === 'transfer' ? mainJourney : null;
  return {
    id: `synthetic-${id}`,
    originTripId: `synthetic-trip-${id}`,
    routeId,
    routeName: routeId === '6' ? '有楽町線' : '副都心線',
    headsign: '和光市',
    trainType: 'Local',
    reportedTrainType: 'Local',
    serviceBrand: null,
    typeLabel: '各駅停車',
    typeSource: 'odpt_confirmed',
    destination: '和光市',
    destinationSource: 'gtfs_headsign',
    odptDestinationIds: ['synthetic-destination-id'],
    odptMatchStatus: 'unique_match',
    departureServiceSeconds: seconds,
    departureText: serviceTime(seconds),
    primary: mainJourney,
    directAlternative: direct,
    bestTransferAlternative: transfer,
    transferCandidateCount: transfer ? 1 : 0,
    status: 'candidate',
    dataQuality: [],
    odptTrainTypeUri: 'synthetic-raw-uri-to-drop',
    odptMatchReason: 'synthetic-diagnostic-to-drop',
    typeDiagnostic: 'synthetic-diagnostic-to-drop',
  };
}

function serviceDay(serviceDate, departures, destinationId) {
  const routeCounts = Object.fromEntries(['6', '9'].map(routeId => {
    const rows = departures.filter(item => item.routeId === routeId);
    const directCount = rows.filter(item => item.directAlternative !== null).length;
    const transferCount = rows.filter(item => item.bestTransferAlternative !== null).length;
    const transferOnly = rows.filter(item => item.directAlternative === null
      && item.bestTransferAlternative !== null).length;
    return [routeId, {
      scheduledTripCount: rows.length,
      originTripCount: rows.length,
      candidateCount: rows.filter(item => item.primary !== null).length,
      passThroughCount: 0,
      dataInsufficientCount: 0,
      transferDataInsufficientCount: 0,
      directCandidateCount: directCount,
      transferCandidateCount: transferCount,
      transferPairCount: rows.reduce((sum, item) => sum + item.transferCandidateCount, 0),
      transferOnlyCount: transferOnly,
    }];
  }));
  const state = {
    status: departures.length ? 'normal' : 'no_candidates',
    candidateCount: departures.filter(item => item.primary !== null).length,
    passThroughCount: 0,
    dataInsufficientCount: 0,
    routes: routeCounts,
  };
  if (['Heiwadai', 'ChikatetsuAkatsuka', 'ChikatetsuNarimasu', 'Wakoshi'].includes(destinationId)) {
    state.directCandidateCount = departures.filter(item => item.directAlternative !== null).length;
    state.transferCandidateCount = departures.filter(item => item.bestTransferAlternative !== null).length;
    state.transferPairCount = departures.reduce((sum, item) => sum + item.transferCandidateCount, 0);
    state.transferOnlyCount = departures.filter(item => item.directAlternative === null
      && item.bestTransferAlternative !== null).length;
    state.transferPassThroughCount = 0;
    state.transferDataInsufficientCount = 0;
  }
  return {
    serviceDate,
    originStationId: 'Ikebukuro',
    destinationStationId: destinationId,
    departures,
    destinationStatus: state,
  };
}

function syntheticLocalPayload(destinationId = 'Hikawadai') {
  const rows = {
    '2026-10-25': [departure({ id: 'prior-late', routeId: '6', seconds: 93000,
      arrival: 93600, destinationId })],
    '2026-10-26': [
      departure({ id: 'evening-y-early', routeId: '6', seconds: 81000, arrival: 84600, destinationId }),
      departure({ id: 'evening-y-last', routeId: '6', seconds: 82800, arrival: 85200, destinationId }),
      departure({ id: 'evening-f-transfer', routeId: '9', seconds: 83100, arrival: 84000,
        destinationId, kind: 'transfer' }),
    ],
    '2026-10-27': [
      departure({ id: 'morning-y-first', routeId: '6', seconds: 21600, arrival: 22500, destinationId }),
      departure({ id: 'morning-y-next', routeId: '6', seconds: 22800, arrival: 23700, destinationId }),
      departure({ id: 'morning-f-first', routeId: '9', seconds: 23400, arrival: 24300, destinationId }),
      departure({ id: 'morning-f-next', routeId: '9', seconds: 24300, arrival: 25200, destinationId }),
    ],
    '2026-10-28': [
      departure({ id: 'nextday-y', routeId: '6', seconds: 21900, arrival: 22800, destinationId }),
      departure({ id: 'nextday-f', routeId: '9', seconds: 23700, arrival: 24600, destinationId }),
    ],
  };
  return {
    schemaVersion: 1,
    dataScope: LOCAL_DATA_SCOPE,
    generatedAt: '2026-10-24T00:00:00Z',
    timezone: 'Asia/Tokyo',
    feed: { version: 'synthetic-v1', validFrom: '2026-10-25', validThrough: '2026-10-28',
      sourceUpdatedAt: null },
    odpt: { sourceUpdatedAt: null },
    applicationPeriod: { startsAt: '2026-10-25T00:00:00+09:00', endsAt: '2026-10-29T00:00:00+09:00' },
    webApp: { builtAt: null },
    connectionPolicy: { minimumWaitSeconds: 60, maximumWaitSeconds: 600,
      platformStatus: 'unknown', connectionGuaranteed: false },
    serviceDays: Object.entries(rows).map(([date, departures]) => serviceDay(date, departures, destinationId)),
    excludedServiceDates: [],
  };
}

function projectWithPhaseOne(localPayload) {
  const python = [
    'import json, sys',
    'sys.path.insert(0, sys.argv[1])',
    'from public_payload_profile import project_public_payload',
    'print(json.dumps(project_public_payload(json.load(sys.stdin))))',
  ].join('; ');
  return JSON.parse(execFileSync('python3', ['-c', python, SCRIPT_DIR], {
    cwd: ROOT,
    input: JSON.stringify(localPayload),
    encoding: 'utf8',
  }));
}

function decisionSnapshot(board) {
  return {
    validity: board.validity,
    serviceState: board.serviceState,
    destinationStationId: board.destinationStationId,
    bestId: board.bestId,
    routeStates: Object.fromEntries(Object.entries(board.routeStates)
      .map(([routeId, state]) => [routeId, state.state])),
    destinationStates: board.destinationStates.map(state => ({
      serviceDate: state.serviceDate,
      destinationStationId: state.destinationStationId,
      status: state.status,
      candidateCount: state.candidateCount,
      dataInsufficientCount: state.dataInsufficientCount,
    })),
    items: board.items.map(item => ({
      id: item.id,
      serviceDate: item.serviceDate,
      routeId: item.routeId,
      departureAtMs: item.departureAtMs,
      arrivalAtMs: item.arrivalAtMs,
      departureText: item.departureText,
      arrivalText: item.arrivalText,
      journeyKind: item.journeyKind,
      transferWaitSeconds: item.transfer?.waitSeconds ?? null,
      isLastDeparture: item.isLastDeparture,
      terminalBasis: item.terminalBasis,
      isBest: item.isBest,
    })),
  };
}

function compareProfiles(local, publicPayload, nowMs, options = {}) {
  const localBoard = buildBoard(local, { nowMs, ...options, expectedProfile: LOCAL_DATA_SCOPE });
  const publicBoard = buildBoard(publicPayload, { nowMs, ...options, expectedProfile: PUBLIC_DATA_SCOPE });
  assert.deepEqual(decisionSnapshot(publicBoard), decisionSnapshot(localBoard));
  return localBoard;
}

test('profile boundaries require an explicit expected scope and never accept the other profile', () => {
  const local = syntheticLocalPayload();
  const publicPayload = projectWithPhaseOne(local);
  assert.equal(publicPayload.dataScope, PUBLIC_DATA_SCOPE);
  assert.throws(() => prepareTimetablePayload(local, PUBLIC_DATA_SCOPE), /public-display-v1 required/);
  assert.throws(() => prepareTimetablePayload(publicPayload, LOCAL_DATA_SCOPE), /local-preview-only required/);
  assert.throws(() => prepareTimetablePayload(publicPayload, 'unknown'), /unsupported data profile/);
  assert.throws(() => buildBoard(publicPayload, { nowMs: JST('2026-10-26T22:00:00'),
    expectedProfile: LOCAL_DATA_SCOPE }), /local-preview-only required/);
  const preparedPublic = prepareTimetablePayload(publicPayload, PUBLIC_DATA_SCOPE);
  assert.throws(() => buildBoard(preparedPublic, { nowMs: JST('2026-10-26T22:00:00') }),
    /local-preview-only expected for prepared payload/);
  assert.equal(buildBoard(preparedPublic, { nowMs: JST('2026-10-26T22:00:00'),
    expectedProfile: PUBLIC_DATA_SCOPE }).validity, 'valid');
});

test('local and public profiles give the same departure order, line grouping, arrival choice, and transfers', () => {
  const local = syntheticLocalPayload();
  const publicPayload = projectWithPhaseOne(local);
  const board = compareProfiles(local, publicPayload, JST('2026-10-26T22:05:00'));
  assert.deepEqual(board.items.map(item => item.routeId), ['6', '6', '9']);
  assert.equal(board.bestId, board.items[2].id);
  assert.equal(board.items[2].journeyKind, 'transfer');
  assert.equal(board.items[2].transfer.waitSeconds, 120);

  const lineBoard = compareProfiles(local, publicPayload, JST('2026-10-26T22:05:00'), { mode: 'line' });
  assert.deepEqual(lineBoard.groups.map(group => group.routeId), ['6', '9']);
  assert.ok(lineBoard.groups[1].items.every(item => item.routeId === '9'));
});

test('direct-only terminal, all-route transfer terminal, and post-terminal state match', () => {
  const local = syntheticLocalPayload();
  const publicPayload = projectWithPhaseOne(local);
  const allRoutes = compareProfiles(local, publicPayload, JST('2026-10-26T22:50:00'));
  const yLast = allRoutes.items.find(item => item.id.includes('synthetic-trip-evening-y-last'));
  const fLast = allRoutes.items.find(item => item.id.includes('synthetic-trip-evening-f-transfer'));
  assert.equal(yLast.isLastDeparture, true);
  assert.equal(yLast.terminalBasis, 'all_reachable');
  assert.equal(fLast.isLastDeparture, true);
  assert.equal(fLast.journeyKind, 'transfer');

  const direct = compareProfiles(local, publicPayload, JST('2026-10-26T22:50:00'), { directOnly: true });
  assert.ok(direct.items.every(item => item.routeId === '6'));
  assert.equal(direct.items.find(item => item.id.includes('synthetic-trip-evening-y-last')).terminalBasis,
    'direct_only');
  assert.equal(direct.items.find(item => item.id.includes('synthetic-trip-evening-y-last')).isLastDeparture, true);

  const ended = compareProfiles(local, publicPayload, JST('2026-10-26T23:10:00'));
  assert.equal(ended.serviceState, 'ended');
  assert.deepEqual(ended.items, []);
});

test('previous service-date 25:50 tail remains attached to its serviceDate after midnight', () => {
  const local = syntheticLocalPayload();
  const publicPayload = projectWithPhaseOne(local);
  const board = compareProfiles(local, publicPayload, JST('2026-10-26T01:40:00'));
  const priorTail = board.items.find(item => item.id.includes('synthetic-trip-prior-late'));
  assert.ok(priorTail);
  assert.equal(priorTail.serviceDate, '2026-10-25');
  assert.equal(priorTail.departureText, '01:50');
});

test('each route becomes visible at its own 60-minute morning gate in both profiles', () => {
  const local = syntheticLocalPayload();
  const publicPayload = projectWithPhaseOne(local);
  const before = compareProfiles(local, publicPayload, JST('2026-10-27T04:59:00'));
  assert.equal(before.items.length, 0);

  const yurakuchoGate = compareProfiles(local, publicPayload, JST('2026-10-27T05:00:00'));
  assert.ok(yurakuchoGate.items.some(item => item.routeId === '6'));
  assert.ok(yurakuchoGate.items.every(item => item.routeId === '6'));
  assert.equal(yurakuchoGate.items[0].serviceDate, '2026-10-27');

  const fukutoshinBeforeGate = compareProfiles(local, publicPayload, JST('2026-10-27T05:29:00'));
  assert.ok(fukutoshinBeforeGate.items.every(item => item.routeId === '6'));
  const bothGates = compareProfiles(local, publicPayload, JST('2026-10-27T05:30:00'));
  assert.ok(bothGates.items.some(item => item.routeId === '6'));
  assert.ok(bothGates.items.some(item => item.routeId === '9'));
});

test('destination-specific candidate counts and state validation match after projection', () => {
  const local = syntheticLocalPayload('Heiwadai');
  const publicPayload = projectWithPhaseOne(local);
  const board = compareProfiles(local, publicPayload, JST('2026-10-26T22:00:00'));
  assert.equal(board.destinationStationId, 'Heiwadai');
  const current = board.destinationStates.find(state => state.serviceDate === '2026-10-26');
  assert.equal(current.status, 'normal');
  assert.equal(current.candidateCount, 3);
  assert.equal(current.transferCandidateCount, 1);
});
