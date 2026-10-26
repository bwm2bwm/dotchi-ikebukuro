import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildBoard,
  formatTokyoTime,
  PayloadValidationError,
  prepareTimetablePayload,
  serviceSecondsToEpochMs,
  validateTimetablePayload,
} from '../scripts/timetable_adapter.mjs';
import { parseVirtualNow } from '../_local_preview/virtual_now.mjs';
import { emptyBoardText } from '../_local_preview/terminal_ui.mjs';

const JST = value => new Date(`${value}+09:00`).getTime();

function direct(arrivalSeconds, overrides = {}) {
  return {
    kind: 'direct',
    departureServiceSeconds: 6 * 3600,
    arrivalServiceSeconds: arrivalSeconds,
    departureText: '06:00:00',
    arrivalText: '06:10:00',
    arrivalStationId: 'Hikawadai',
    transfer: null,
    platformStatus: 'unknown',
    connectionGuaranteed: false,
    ...overrides,
  };
}

function transfer(arrivalSeconds, waitSeconds = 120) {
  return {
    kind: 'transfer',
    departureServiceSeconds: 6 * 3600,
    arrivalServiceSeconds: arrivalSeconds,
    departureText: '06:00:00',
    arrivalText: '06:12:00',
    arrivalStationId: 'Hikawadai',
    transfer: {
      stationId: 'KotakeMukaihara',
      stationName: '小竹向原',
      waitSeconds,
      outgoingRouteId: '9',
      outgoingRouteName: '副都心線',
      outgoingHeadsign: '和光市',
      outgoingTrainType: 'Local',
      outgoingDestinationIds: ['Wakoshi'],
    },
    platformStatus: 'unknown',
    connectionGuaranteed: false,
  };
}

function departure({
  id,
  tripId = id,
  routeId = '6',
  serviceSeconds = 6 * 3600,
  primary = direct(6 * 3600 + 600),
  directAlternative = direct(6 * 3600 + 600),
  bestTransferAlternative = null,
  destination = '和光市',
  trainType = 'Local',
  reportedTrainType = trainType,
  serviceBrand = null,
  typeLabel,
  typeSource = trainType ? 'odpt_confirmed' : 'unknown',
  stopPattern = null,
  typeValidation = 'not_applicable',
  typeDiagnostic = null,
  odptMatchStatus = trainType ? 'unique_match' : 'unmatched',
  odptTrainTypeUri = null,
  otherOperatorTrainType = null,
  unscopedTrainType = null,
  odptMatchMethod = null,
  odptMatchReason = null,
  dataQuality = [],
} = {}) {
  return {
    id,
    originTripId: tripId,
    routeId,
    routeName: routeId === '6' ? '有楽町線' : '副都心線',
    headsign: destination,
    trainType,
    reportedTrainType,
    serviceBrand,
    odptTrainTypeUri,
    otherOperatorTrainType,
    unscopedTrainType,
    odptMatchMethod,
    odptMatchReason,
    typeLabel,
    typeSource,
    stopPattern,
    stopPatternStates: {},
    typeValidation,
    typeDiagnostic,
    destination,
    odptDestinationIds: destination ? ['Wakoshi'] : [],
    odptMatchStatus,
    departureServiceSeconds: serviceSeconds,
    departureText: '06:00:00',
    primary,
    directAlternative,
    bestTransferAlternative,
    transferCandidateCount: bestTransferAlternative ? 2 : 0,
    status: primary ? 'ok' : 'no_valid_arrival',
    dataQuality,
  };
}

function serviceDay(serviceDate, departures, destinationStationId = 'Hikawadai') {
  const routeCounts = Object.fromEntries(['6', '9'].map(routeId => {
    const rows = departures.filter(item => item.routeId === routeId);
    const directCandidateCount = rows.filter(item => item.directAlternative !== null).length;
    const transferCandidateCount = rows.filter(item => item.bestTransferAlternative !== null).length;
    return [routeId, {
      scheduledTripCount: rows.length,
      originTripCount: rows.length,
      candidateCount: rows.filter(item => item.primary !== null).length,
      passThroughCount: 0,
      dataInsufficientCount: 0,
      transferDataInsufficientCount: 0,
      directCandidateCount,
      transferCandidateCount,
      transferPairCount: rows.reduce((sum, item) => sum + item.transferCandidateCount, 0),
      transferOnlyCount: rows.filter(item => item.directAlternative === null
        && item.bestTransferAlternative !== null).length,
    }];
  }));
  const candidateCount = departures.filter(item => item.primary !== null).length;
  const directCandidateCount = departures.filter(item => item.directAlternative !== null).length;
  const transferCandidateCount = departures.filter(item => item.bestTransferAlternative !== null).length;
  const transferPairCount = departures.reduce((sum, item) => sum + item.transferCandidateCount, 0);
  return {
    serviceDate,
    originStationId: 'Ikebukuro',
    destinationStationId,
    departures,
    destinationStatus: {
      status: candidateCount ? 'normal' : 'no_candidates',
      candidateCount,
      directCandidateCount,
      transferCandidateCount,
      transferPairCount,
      transferOnlyCount: departures.filter(item => item.directAlternative === null
        && item.bestTransferAlternative !== null).length,
      passThroughCount: 0,
      transferPassThroughCount: 0,
      dataInsufficientCount: 0,
      transferDataInsufficientCount: 0,
      routes: routeCounts,
    },
  };
}

function emptyDestinationStatus() {
  const emptyRoute = () => ({ scheduledTripCount: 0, originTripCount: 0, candidateCount: 0,
    passThroughCount: 0, dataInsufficientCount: 0, transferDataInsufficientCount: 0 });
  return { status: 'no_candidates', candidateCount: 0, passThroughCount: 0,
    dataInsufficientCount: 0, routes: { '6': emptyRoute(), '9': emptyRoute() } };
}

function emptyTransferDestinationStatus() {
  const emptyRoute = () => ({ scheduledTripCount: 0, originTripCount: 0, candidateCount: 0,
    passThroughCount: 0, dataInsufficientCount: 0, transferDataInsufficientCount: 0,
    directCandidateCount: 0, transferCandidateCount: 0, transferPairCount: 0, transferOnlyCount: 0 });
  return { status: 'no_candidates', candidateCount: 0, directCandidateCount: 0,
    transferCandidateCount: 0, transferPairCount: 0, transferOnlyCount: 0,
    passThroughCount: 0, transferPassThroughCount: 0, dataInsufficientCount: 0,
    transferDataInsufficientCount: 0, routes: { '6': emptyRoute(), '9': emptyRoute() } };
}

function payload(serviceDays = []) {
  const dates = new Set(serviceDays.map(day => day.serviceDate));
  for (const serviceDate of ['2026-10-21', '2026-10-22', '2026-10-23']) {
    if (!dates.has(serviceDate)) {
      const day = {
        serviceDate, originStationId: 'Ikebukuro',
        destinationStationId: serviceDays[0]?.destinationStationId ?? 'Hikawadai', departures: [],
      };
      if (day.destinationStationId === 'Heiwadai' || day.destinationStationId === 'ChikatetsuAkatsuka'
          || day.destinationStationId === 'ChikatetsuNarimasu' || day.destinationStationId === 'Wakoshi') {
        day.destinationStatus = emptyTransferDestinationStatus();
      } else day.destinationStatus = emptyDestinationStatus();
      serviceDays = [...serviceDays, day];
    }
  }
  return {
    schemaVersion: 1,
    dataScope: 'local-preview-only',
    generatedAt: '2026-10-21T15:00:00+00:00',
    timezone: 'Asia/Tokyo',
    feed: { version: 'test-feed', validFrom: '2026-10-21', validThrough: '2026-10-23', sourceUpdatedAt: null },
    odpt: { sourceUpdatedAt: null },
    applicationPeriod: { startsAt: '2026-10-21T00:00:00+09:00', endsAt: '2026-10-24T00:00:00+09:00' },
    webApp: { builtAt: null },
    connectionPolicy: {
      minimumWaitSeconds: 60,
      maximumWaitSeconds: 600,
      platformStatus: 'unknown',
      connectionGuaranteed: false,
    },
    serviceDays,
    excludedServiceDates: [],
  };
}

function journeyAt(departureSeconds, arrivalSeconds, kind = 'direct', transferData = null) {
  return {
    kind,
    departureServiceSeconds: departureSeconds,
    arrivalServiceSeconds: arrivalSeconds,
    departureText: '06:00:00',
    arrivalText: '06:10:00',
    arrivalStationId: 'Hikawadai',
    transfer: transferData,
    platformStatus: 'unknown',
    connectionGuaranteed: false,
  };
}

test('converts 24h-plus service seconds using Asia/Tokyo service-day midnight', () => {
  assert.equal(serviceSecondsToEpochMs('2026-10-21', 24 * 3600 + 10 * 60), JST('2026-10-22T00:10:00'));
  assert.equal(formatTokyoTime(serviceSecondsToEpochMs('2026-10-21', 24 * 3600 + 10 * 60)), '00:10');
});

function timedDeparture(id, routeId, serviceSeconds, { direct = true, transferOnly = false } = {}) {
  const directJourney = direct
    ? journeyAt(serviceSeconds, serviceSeconds + 600)
    : null;
  const transferJourney = transferOnly
    ? { ...transfer(serviceSeconds + 900), departureServiceSeconds: serviceSeconds }
    : null;
  return departure({
    id, tripId: id, routeId, serviceSeconds,
    primary: transferOnly ? transferJourney : directJourney,
    directAlternative: directJourney,
    bestTransferAlternative: transferJourney,
  });
}

test('marks the last reachable Ikebukuro departure independently for each route', () => {
  const rows = [
    timedDeparture('y-first', '6', 6 * 3600),
    timedDeparture('y-early', '6', 20 * 3600),
    timedDeparture('y-last', '6', 23 * 3600),
    timedDeparture('f-first', '9', 6 * 3600),
    timedDeparture('f-early', '9', 19 * 3600),
    timedDeparture('f-last', '9', 22 * 3600),
  ];
  const board = buildBoard(payload([serviceDay('2026-10-22', rows)]),
    { nowMs: JST('2026-10-22T18:00:00') });
  assert.deepEqual(board.items.filter(item => item.isLastDeparture).map(item => item.sourceId).sort(),
    ['y-last', 'f-last'].sort());
  assert.equal(board.serviceState, 'running');
  const ended = buildBoard(payload([serviceDay('2026-10-22', rows)]),
    { nowMs: JST('2026-10-22T23:01:00') });
  assert.equal(ended.serviceState, 'ended');
});

test('reports one route ended while the other route has not reached its start gate', () => {
  const rows = [timedDeparture('y-last', '6', 23 * 3600), timedDeparture('f-last', '9', 20 * 3600)];
  const board = buildBoard(payload([serviceDay('2026-10-22', rows)]),
    { nowMs: JST('2026-10-22T20:01:00') });
  assert.equal(board.routeStates['6'].state, 'not_started');
  assert.equal(board.routeStates['9'].state, 'ended');
  assert.equal(board.serviceState, 'partial');
});

test('later transfer departure is the terminal candidate on its Ikebukuro boarding route', () => {
  const rows = [
    timedDeparture('first', '6', 6 * 3600),
    timedDeparture('direct-last', '6', 22 * 3600 + 30 * 60),
    timedDeparture('transfer-last', '6', 23 * 3600, { direct: false, transferOnly: true }),
  ];
  const board = buildBoard(payload([serviceDay('2026-10-22', rows)]),
    { nowMs: JST('2026-10-22T21:00:00') });
  const terminal = board.items.find(item => item.isLastDeparture);
  assert.equal(terminal.sourceId, 'transfer-last');
  assert.equal(terminal.journeyKind, 'transfer');
});

test('direct-only mode recalculates the last departure from direct candidates only', () => {
  const rows = [
    timedDeparture('direct-last', '6', 22 * 3600),
    timedDeparture('transfer-last', '6', 23 *  3600, { direct: false, transferOnly: true }),
  ];
  const source = payload([serviceDay('2026-10-22', rows)]);
  const all = buildBoard(source, { nowMs: JST('2026-10-22T21:00:00') });
  const directOnly = buildBoard(source, { nowMs: JST('2026-10-22T21:00:00'), directOnly: true });
  assert.equal(all.items.find(item => item.isLastDeparture).sourceId, 'transfer-last');
  assert.equal(directOnly.items.find(item => item.isLastDeparture).sourceId, 'direct-last');
  assert.equal(directOnly.items.find(item => item.isLastDeparture).terminalBasis, 'direct_only');
});

test('24:xx and 25:xx candidates stay with the previous service date after midnight', () => {
  const rows = [
    timedDeparture('24-hour', '6', 24 * 3600 + 20 * 60),
    timedDeparture('25-hour', '6', 25 * 3600 + 10 * 60),
  ];
  const board = buildBoard(payload([serviceDay('2026-10-22', rows)]),
    { nowMs: JST('2026-10-23T00:10:00') });
  assert.deepEqual(board.items.map(item => item.sourceId), ['24-hour', '25-hour']);
  assert.equal(board.items[0].departureText, '00:20');
  assert.equal(board.items[1].departureText, '01:10');
  assert.equal(board.items[1].isLastDeparture, true);
});

test('service-date candidates are gated until 60 minutes before their first reachable departure', () => {
  const nextDay = serviceDay('2026-10-23', [
    timedDeparture('first', '6', 5 * 3600),
    timedDeparture('later', '6', 6 * 3600),
  ]);
  const source = payload([nextDay]);
  for (const [time, expectedVisible] of [
    ['03:59:00', false], ['04:00:00', true], ['04:01:00', true],
  ]) {
    const board = buildBoard(source, { nowMs: JST(`2026-10-23T${time}`) });
    assert.equal(board.items.some(item => item.sourceId === 'first'), expectedVisible, time);
  }
});

test('legacy coverage cannot claim a terminal or release a future service date early', () => {
  const nextDay = serviceDay('2026-10-23', [timedDeparture('first', '6', 5 * 3600)]);
  delete nextDay.destinationStatus;
  const source = payload([nextDay]);
  const early = buildBoard(source, { nowMs: JST('2026-10-23T03:59:00') });
  assert.equal(early.items.length, 0);
  assert.equal(early.serviceState, 'unknown');
  const inWindow = buildBoard(source, { nowMs: JST('2026-10-23T04:00:00') });
  assert.equal(inWindow.items.length, 1);
  assert.equal(inWindow.items[0].isLastDeparture, false);
  assert.equal(inWindow.serviceState, 'unknown');
});

test('23:50, 00:10, 00:40, 01:30, and 05:00 separate prior tails from the new service date', () => {
  const source = payload([
    serviceDay('2026-10-22', [timedDeparture('prior-last', '6', 24 * 3600 + 30 * 60)]),
    serviceDay('2026-10-23', [timedDeparture('morning-first', '6', 5 * 3600),
      timedDeparture('morning-next', '6', 5 * 3600 + 10 * 60)]),
  ]);
  for (const [time, expectedIds] of [
    ['2026-10-22T23:50:00', ['prior-last']],
    ['2026-10-23T00:10:00', ['prior-last']],
    ['2026-10-23T00:40:00', []],
    ['2026-10-23T01:30:00', []],
    ['2026-10-23T05:00:00', ['morning-next']],
  ]) {
    const board = buildBoard(source, { nowMs: JST(time) });
    assert.deepEqual(board.items.map(item => item.sourceId), expectedIds, time);
  }
});

test('virtual JST times end the prior service and restart each route at its own gate', () => {
  const source = payload([
    serviceDay('2026-10-22', [
      timedDeparture('prior-last-y', '6', 24 * 3600 + 30 * 60),
      timedDeparture('prior-last-f', '9', 24 * 3600 + 20 * 60),
    ]),
    serviceDay('2026-10-23', [
      timedDeparture('morning-first-y', '6', 5 * 3600),
      timedDeparture('morning-next-y', '6', 5 * 3600 + 10 * 60),
      timedDeparture('morning-first-f', '9', 5 * 3600 + 5 * 60),
      timedDeparture('morning-next-f', '9', 5 * 3600 + 15 * 60),
    ]),
  ]);
  for (const [time, expectedIds, expectedState] of [
    ['2026-10-22T23:50:00', ['prior-last-f', 'prior-last-y'], 'running'],
    ['2026-10-23T00:10:00', ['prior-last-f', 'prior-last-y'], 'running'],
    ['2026-10-23T00:40:00', [], 'ended'],
    ['2026-10-23T01:30:00', [], 'ended'],
    ['2026-10-23T04:00:00', ['morning-first-y', 'morning-next-y'], 'partial'],
    ['2026-10-23T04:05:00', ['morning-first-y', 'morning-first-f', 'morning-next-y', 'morning-next-f'], 'running'],
    ['2026-10-23T05:00:00', ['morning-first-f', 'morning-next-y', 'morning-next-f'], 'running'],
  ]) {
    const override = parseVirtualNow(`?debugNow=${time}`);
    assert.ok(override, time);
    const board = buildBoard(source, { nowMs: override.nowMs });
    assert.deepEqual(board.items.map(item => item.sourceId), expectedIds, time);
    assert.equal(board.serviceState, expectedState, time);
    if (time === '2026-10-23T00:40:00' || time === '2026-10-23T01:30:00') {
      assert.equal(emptyBoardText(board.serviceState), '本日の終電は終了しました');
    }
  }
  const terminalBoard = buildBoard(source, {
    nowMs: parseVirtualNow('?debugNow=2026-10-22T23:50:00').nowMs,
  });
  assert.ok(terminalBoard.items.every(item => item.isLastDeparture));

  const directOnlyEnded = buildBoard(source, {
    nowMs: parseVirtualNow('?debugNow=2026-10-23T00:40:00').nowMs,
    directOnly: true,
  });
  const directOnlyPartial = buildBoard(source, {
    nowMs: parseVirtualNow('?debugNow=2026-10-23T04:00:00').nowMs,
    directOnly: true,
  });
  assert.equal(directOnlyEnded.serviceState, 'ended');
  assert.equal(directOnlyPartial.routeStates['6'].state, 'running');
  assert.equal(directOnlyPartial.routeStates['9'].state, 'ended');
  assert.equal(directOnlyPartial.serviceState, 'partial');

  const outsidePayload = payload([serviceDay('2026-10-27', [timedDeparture('outside', '6', 6 * 3600)])]);
  const outsideBoard = buildBoard(outsidePayload, {
    nowMs: parseVirtualNow('?debugNow=2026-10-27T06:00:00').nowMs,
  });
  assert.notEqual(outsideBoard.validity, 'valid');
  assert.equal(outsideBoard.serviceState, 'unavailable');

  const insufficientPreviousDay = serviceDay('2026-10-22', [
    timedDeparture('unknown-prior-last-y', '6', 24 * 3600 + 30 * 60),
    timedDeparture('unknown-prior-last-f', '9', 24 * 3600 + 20 * 60),
  ]);
  delete insufficientPreviousDay.destinationStatus;
  const insufficientBoard = buildBoard(payload([
    insufficientPreviousDay,
    serviceDay('2026-10-23', [
      timedDeparture('morning-y', '6', 5 * 3600),
      timedDeparture('morning-f', '9', 5 * 3600 + 5 * 60),
    ]),
  ]), { nowMs: parseVirtualNow('?debugNow=2026-10-23T00:40:00').nowMs });
  assert.equal(insufficientBoard.serviceState, 'unknown');

  const destinationChanged = buildBoard(payload([
    serviceDay('2026-10-22', [], 'Wakoshi'),
  ]), { nowMs: parseVirtualNow('?debugNow=2026-10-23T00:40:00').nowMs });
  assert.equal(destinationChanged.destinationStationId, 'Wakoshi');
  assert.equal(destinationChanged.serviceState, 'no_service');
});

test('terminal state changes immediately before, at, and after the last departure', () => {
  const source = payload([serviceDay('2026-10-22', [timedDeparture('last', '6', 23 * 3600)])]);
  assert.equal(buildBoard(source, { nowMs: JST('2026-10-22T22:59:59') }).items[0].isLastDeparture, true);
  const atDeparture = buildBoard(source, { nowMs: JST('2026-10-22T23:00:00') });
  assert.equal(atDeparture.items.length, 0);
  assert.equal(atDeparture.routeStates['6'].state, 'ended');
  assert.equal(buildBoard(source, { nowMs: JST('2026-10-22T23:00:01') }).routeStates['6'].state, 'ended');
});

test('zero reachable candidates, no service, and incomplete route data are not treated as terminal', () => {
  const empty = serviceDay('2026-10-22', []);
  const noCandidates = buildBoard(payload([empty]), { nowMs: JST('2026-10-22T23:00:00') });
  assert.equal(noCandidates.routeStates['6'].state, 'no_service');
  assert.notEqual(noCandidates.serviceState, 'ended');

  const insufficient = serviceDay('2026-10-22', [timedDeparture('unknown', '6', 23 * 3600)]);
  insufficient.destinationStatus.routes['6'].dataInsufficientCount = 1;
  insufficient.destinationStatus.dataInsufficientCount = 1;
  const blockedEnd = buildBoard(payload([insufficient]), { nowMs: JST('2026-10-22T23:00:00') });
  assert.equal(blockedEnd.routeStates['6'].state, 'data_insufficient');
  assert.equal(blockedEnd.serviceState, 'unknown');
  const blockedDirectOnly = buildBoard(payload([insufficient]), {
    nowMs: JST('2026-10-22T23:00:00'), directOnly: true,
  });
  assert.equal(blockedDirectOnly.routeStates['6'].state, 'data_insufficient');
  assert.equal(blockedDirectOnly.serviceState, 'unknown');

  const unreachable = serviceDay('2026-10-22', []);
  unreachable.destinationStatus.routes['6'].scheduledTripCount = 1;
  unreachable.destinationStatus.routes['6'].originTripCount = 1;
  const noReachableArrival = buildBoard(payload([unreachable]),
    { nowMs: JST('2026-10-22T23:00:00') });
  assert.equal(noReachableArrival.routeStates['6'].state, 'no_candidates');
  assert.notEqual(noReachableArrival.serviceState, 'ended');
});

test('all eight supported destinations accept the extended service coverage payload shape', () => {
  for (const stationId of ['Kanamecho', 'Senkawa', 'KotakeMukaihara', 'Hikawadai', 'Heiwadai',
    'ChikatetsuAkatsuka', 'ChikatetsuNarimasu', 'Wakoshi']) {
    const source = payload([serviceDay('2026-10-22', [], stationId)]);
    assert.doesNotThrow(() => validateTimetablePayload(source), stationId);
    const board = buildBoard(source, { nowMs: JST('2026-10-22T05:00:00') });
    assert.equal(board.destinationStationId, stationId);
  }
});

test('terminal candidates are recalculated from the selected destination payload', () => {
  const rows = [timedDeparture('early', '6', 20 * 3600), timedDeparture('late', '6', 23 * 3600)];
  const hikawadaiDay = serviceDay('2026-10-22', rows, 'Hikawadai');
  const kanamechoRows = structuredClone(rows);
  for (const row of kanamechoRows) {
    for (const journey of [row.primary, row.directAlternative, row.bestTransferAlternative]) {
      if (journey) journey.arrivalStationId = 'Kanamecho';
    }
  }
  const kanamechoDay = serviceDay('2026-10-22', kanamechoRows, 'Kanamecho');
  const nowMs = JST('2026-10-22T19:00:00');
  const hikawadai = buildBoard(payload([hikawadaiDay]), { nowMs });
  const kanamecho = buildBoard(payload([kanamechoDay]), { nowMs });
  assert.equal(hikawadai.items.find(item => item.isLastDeparture).sourceId, 'late');
  assert.equal(kanamecho.items.find(item => item.isLastDeparture).sourceId, 'late');

  kanamechoDay.departures = kanamechoDay.departures.filter(row => row.id !== 'late');
  kanamechoDay.destinationStatus = serviceDay('2026-10-22', kanamechoDay.departures,
    'Kanamecho').destinationStatus;
  const changedDestination = buildBoard(payload([kanamechoDay]), { nowMs });
  assert.equal(changedDestination.items.find(item => item.isLastDeparture).sourceId, 'early');
  assert.equal(changedDestination.destinationStationId, 'Kanamecho');
});

test('uses current, previous, and next service days without showing the same trip twice', () => {
  const previousDayLate = departure({
    id: '2026-10-21:6T1', tripId: '6T1', serviceSeconds: 24 * 3600 + 600,
    primary: journeyAt(24 * 3600 + 600, 24 * 3600 + 1200),
    directAlternative: journeyAt(24 * 3600 + 600, 24 * 3600 + 1200),
  });
  const todayDuplicate = departure({
    id: '2026-10-22:6T1', tripId: '6T1', serviceSeconds: 600,
    primary: journeyAt(600, 1200), directAlternative: journeyAt(600, 1200),
  });
  const nextDay = departure({
    id: '2026-10-23:6T2', tripId: '6T2', serviceSeconds: 0,
    primary: journeyAt(0, 600),
    directAlternative: journeyAt(0, 600),
  });
  const board = buildBoard(payload([
    serviceDay('2026-10-21', [previousDayLate]),
    serviceDay('2026-10-22', [todayDuplicate]),
    serviceDay('2026-10-23', [nextDay]),
  ]), { nowMs: JST('2026-10-22T00:00:00'), mode: 'departure' });

  assert.equal(board.items.length, 1);
  assert.equal(board.diagnostics.duplicateCount, 1);
  assert.equal(board.items[0].serviceDate, '2026-10-21');
  assert.equal(board.items[0].departureText, '00:10');
  assert.ok(board.excluded.some(item => item.reason === 'before_service_start_window'));
});

test('filters past departures and applies the inclusive 24-hour window', () => {
  const now = JST('2026-10-22T06:00:00');
  const past = departure({ id: 'past', serviceSeconds: 6 * 3600,
    primary: journeyAt(6 * 3600, 6 * 3600 + 600), directAlternative: journeyAt(6 * 3600, 6 * 3600 + 600) });
  const exactlyNow = departure({ id: 'now', tripId: 'now', serviceSeconds: 6 * 3600,
    primary: journeyAt(6 * 3600, 6 * 3600 + 600), directAlternative: journeyAt(6 * 3600, 6 * 3600 + 600) });
  const inWindow = departure({ id: 'in', tripId: 'in', serviceSeconds: 6 * 3600 + 60,
    primary: journeyAt(6 * 3600 + 60, 6 * 3600 + 600), directAlternative: journeyAt(6 * 3600 + 60, 6 * 3600 + 600) });
  const atBoundary = departure({ id: 'boundary', tripId: 'boundary', serviceSeconds: 6 * 3600 + 86400,
    primary: journeyAt(6 * 3600 + 86400, 6 * 3600 + 87000),
    directAlternative: journeyAt(6 * 3600 + 86400, 6 * 3600 + 87000) });
  const afterBoundary = departure({ id: 'after', tripId: 'after', serviceSeconds: 6 * 3600 + 86401,
    primary: journeyAt(6 * 3600 + 86401, 6 * 3600 + 87001),
    directAlternative: journeyAt(6 * 3600 + 86401, 6 * 3600 + 87001) });
  const board = buildBoard(payload([serviceDay('2026-10-22', [past, exactlyNow, inWindow, atBoundary, afterBoundary])]),
    { nowMs: now });

  assert.deepEqual(board.items.map(item => item.sourceId), ['in', 'boundary']);
  assert.equal(board.excluded.filter(item => item.reason === 'already_departed').length, 2);
  assert.equal(board.excluded.filter(item => item.reason === 'outside_display_window').length, 1);
});

test('feed validity is inclusive and out-of-period service days are excluded', () => {
  const boundaryStart = departure({ id: 'start' });
  const outside = departure({ id: 'outside', tripId: 'outside' });
  const boundaryEnd = departure({ id: 'end', tripId: 'end' });
  const source = payload([
    serviceDay('2026-10-21', [boundaryStart]),
    serviceDay('2026-10-20', [outside]),
    serviceDay('2026-10-23', [boundaryEnd]),
  ]);
  source.generatedAt = '2026-10-20T15:00:00+00:00';
  const board = buildBoard(source, { nowMs: JST('2026-10-21T05:00:00') });
  assert.deepEqual(board.items.map(item => item.sourceId), ['start']);
  assert.ok(board.excluded.some(item => item.id === 'outside' && item.reason === 'outside_feed_validity'));
});

test('service dates outside Tokyo yesterday/today/tomorrow are ignored even if epoch falls in the window', () => {
  const oldDepartureSeconds = 48 * 3600 + 600;
  const old = departure({ id: 'too-old-service-date', serviceSeconds: oldDepartureSeconds,
    primary: journeyAt(oldDepartureSeconds, oldDepartureSeconds + 600),
    directAlternative: journeyAt(oldDepartureSeconds, oldDepartureSeconds + 600) });
  const source = payload([serviceDay('2026-10-20', [old])]);
  source.feed.validFrom = '2026-10-20';
  const board = buildBoard(source, { nowMs: JST('2026-10-22T00:00:00') });
  assert.equal(board.items.length, 0);
  assert.equal(board.excluded[0].reason, 'outside_service_date_window');
});

test('direct and transfer cards retain connection and platform certainty state', () => {
  const transferJourney = transfer(6 * 3600 + 12 * 60, 60);
  const item = departure({
    id: 'transfer', primary: transferJourney, directAlternative: direct(6 * 3600 + 15 * 60),
    bestTransferAlternative: transferJourney,
  });
  const board = buildBoard(payload([serviceDay('2026-10-22', [item])]),
    { nowMs: JST('2026-10-22T05:00:00') });
  const card = board.items[0];
  assert.equal(card.journeyKind, 'transfer');
  assert.equal(card.transfer.station, '小竹向原');
  assert.equal(card.transfer.waitSeconds, 60);
  assert.equal(card.transfer.wait, 1);
  assert.equal(card.transfer.waitMinutes, 1);
  assert.equal(card.platformStatus, 'unknown');
  assert.equal(card.connectionGuaranteed, false);
});

test('direct-only filter switches to direct alternative and excludes transfer-only trains', () => {
  const transferPrimary = transfer(6 * 3600 + 12 * 60);
  const hasDirect = departure({ id: 'both', primary: transferPrimary,
    directAlternative: direct(6 * 3600 + 15 * 60), bestTransferAlternative: transferPrimary });
  const transferOnly = departure({ id: 'transfer-only', tripId: 'transfer-only', primary: transferPrimary,
    directAlternative: null, bestTransferAlternative: transferPrimary });
  const board = buildBoard(payload([serviceDay('2026-10-22', [hasDirect, transferOnly])]),
    { nowMs: JST('2026-10-22T05:00:00'), directOnly: true });
  assert.equal(board.items.length, 1);
  assert.equal(board.items[0].sourceId, 'both');
  assert.equal(board.items[0].journeyKind, 'direct');
  assert.equal(board.excluded[0].reason, 'direct_unavailable');
});

test('explicit pass-through with a valid transfer does not block terminal proof in either filter mode', () => {
  const passThrough = timedDeparture('pass-through-transfer', '9', 22 * 3600,
    { direct: false, transferOnly: true });
  passThrough.primary.transfer.outgoingRouteId = '6';
  passThrough.primary.transfer.outgoingRouteName = '有楽町線';
  passThrough.bestTransferAlternative.transfer.outgoingRouteId = '6';
  passThrough.bestTransferAlternative.transfer.outgoingRouteName = '有楽町線';
  passThrough.dataQuality = [
    'destination_explicit_pass', 'destination_arrival_missing', 'destination_alighting_prohibited',
  ];
  const prior = serviceDay('2026-10-21', [
    timedDeparture('first-y', '6', 21 * 3600),
    timedDeparture('last-y', '6', 23 * 3600),
    timedDeparture('first-f', '9', 21 * 3600),
    passThrough,
    timedDeparture('last-f', '9', 23 * 3600),
  ]);
  prior.destinationStatus.passThroughCount = 1;
  prior.destinationStatus.routes['9'].passThroughCount = 1;
  const current = serviceDay('2026-10-22', [
    timedDeparture('morning-y', '6', 5 * 3600),
    timedDeparture('morning-f', '9', 5 * 3600 + 5 * 60),
  ]);
  const source = payload([prior, current]);
  source.generatedAt = '2026-10-21T00:00:00+09:00';
  const allReachable = buildBoard(source, { nowMs: JST('2026-10-21T22:30:00') });
  const directOnly = buildBoard(source, { nowMs: JST('2026-10-21T22:30:00'), directOnly: true });
  const allReachableTerminal = allReachable.items.find(item => item.sourceId === 'last-f');
  const directTerminal = directOnly.items.find(item => item.sourceId === 'last-f');
  assert.equal(allReachableTerminal.isLastDeparture, true);
  assert.equal(allReachableTerminal.terminalBasis, 'all_reachable');
  assert.equal(directTerminal.isLastDeparture, true);
  assert.equal(directTerminal.terminalBasis, 'direct_only');
  assert.ok(directOnly.excluded.some(item => item.id === 'pass-through-transfer'
    && item.reason === 'direct_unavailable'));

  const afterLastDeparture = buildBoard(source, {
    nowMs: JST('2026-10-22T00:40:00'), directOnly: true,
  });
  assert.equal(afterLastDeparture.validity, 'valid');
  assert.equal(afterLastDeparture.routeStates['6'].state, 'ended');
  assert.equal(afterLastDeparture.routeStates['9'].state, 'ended');
  assert.equal(afterLastDeparture.serviceState, 'ended');
});

test('line mode groups by route while departure mode sorts all lines by time', () => {
  const firstF = departure({ id: 'F-early', routeId: '9', serviceSeconds: 6 * 3600,
    primary: journeyAt(6 * 3600, 6 * 3600 + 600), directAlternative: journeyAt(6 * 3600, 6 * 3600 + 600) });
  const laterY = departure({ id: 'Y-late', tripId: 'Y-late', routeId: '6', serviceSeconds: 6 * 3600 + 120,
    primary: journeyAt(6 * 3600 + 120, 6 * 3600 + 600), directAlternative: journeyAt(6 * 3600 + 120, 6 * 3600 + 600) });
  const earlierY = departure({ id: 'Y-early', tripId: 'Y-early', routeId: '6', serviceSeconds: 6 * 3600 + 60,
    primary: journeyAt(6 * 3600 + 60, 6 * 3600 + 600), directAlternative: journeyAt(6 * 3600 + 60, 6 * 3600 + 600) });
  const source = payload([serviceDay('2026-10-22', [firstF, laterY, earlierY])]);
  const now = JST('2026-10-22T05:01:00');
  const lineBoard = buildBoard(source, { nowMs: now, mode: 'line' });
  assert.deepEqual(lineBoard.groups.map(group => group.line), ['有楽町線', '副都心線']);
  assert.deepEqual(lineBoard.groups[0].items.map(item => item.sourceId), ['Y-early', 'Y-late']);
  const departureBoard = buildBoard(source, { nowMs: now, mode: 'departure' });
  assert.deepEqual(departureBoard.items.map(item => item.sourceId), ['F-early', 'Y-early', 'Y-late']);
});

test('earliest arrival marks one card and ties prefer earlier departure', () => {
  const laterDeparture = departure({ id: 'later', serviceSeconds: 6 * 3600 + 120,
    primary: journeyAt(6 * 3600 + 120, 6 * 3600 + 900),
    directAlternative: journeyAt(6 * 3600 + 120, 6 * 3600 + 900) });
  const earlierDeparture = departure({ id: 'earlier', tripId: 'earlier', serviceSeconds: 6 * 3600 + 60,
    primary: journeyAt(6 * 3600 + 60, 6 * 3600 + 900),
    directAlternative: journeyAt(6 * 3600 + 60, 6 * 3600 + 900) });
  const board = buildBoard(payload([serviceDay('2026-10-22', [laterDeparture, earlierDeparture])]),
    { nowMs: JST('2026-10-22T05:01:00') });
  assert.equal(board.items.filter(item => item.isBest).length, 1);
  assert.equal(board.bestId, board.items.find(item => item.sourceId === 'earlier').id);
});

test('prepared payload uses cached cards and matches raw adapter output', () => {
  const source = payload([serviceDay('2026-10-22', [
    departure({ id: 'cached-a', routeId: '6', serviceSeconds: 7 * 3600,
      primary: journeyAt(7 * 3600, 7 * 3600 + 600), directAlternative: journeyAt(7 * 3600, 7 * 3600 + 600) }),
    departure({ id: 'cached-b', routeId: '9', tripId: 'cached-b', serviceSeconds: 7 * 3600 + 120,
      primary: journeyAt(7 * 3600 + 120, 7 * 3600 + 900), directAlternative: journeyAt(7 * 3600 + 120, 7 * 3600 + 900) }),
  ])]);
  const prepared = prepareTimetablePayload(source);
  for (const mode of ['line', 'departure']) {
    for (const directOnly of [false, true]) {
      const options = { nowMs: JST('2026-10-22T06:50:00'), mode, directOnly };
      assert.deepEqual(buildBoard(prepared, options), buildBoard(source, options));
    }
  }
});

test('missing arrival and unknown labels are preserved without fabricated values', () => {
  const missing = departure({ id: 'missing', primary: null, directAlternative: null,
    dataQuality: ['destination_arrival_missing', 'destination_alighting_prohibited'] });
  const unknown = departure({ id: 'unknown', tripId: 'unknown', trainType: null, destination: null,
    primary: direct(6 * 3600 + 600), directAlternative: direct(6 * 3600 + 600) });
  const board = buildBoard(payload([serviceDay('2026-10-22', [missing, unknown])]),
    { nowMs: JST('2026-10-22T05:00:00') });
  assert.equal(board.items.length, 1);
  assert.equal(board.items[0].kind, '種別不明');
  assert.equal(board.items[0].destination, '行き先不明');
  assert.equal(board.items[0].destinationLabel, '行き先不明');
  assert.equal(board.items[0].destinationIsKnown, false);
  assert.ok(board.excluded.some(item => item.id === 'missing' && item.reason === 'no_valid_arrival'));
  assert.deepEqual(board.excluded.find(item => item.id === 'missing').dataQuality,
    ['destination_arrival_missing', 'destination_alighting_prohibited']);
});

test('ODPT raw train type maps to Japanese display while F-Liner stays separate from brand', () => {
  const fLiner = departure({ id: 'f-liner', routeId: '9', trainType: 'F-Liner',
    reportedTrainType: 'F-Liner', serviceBrand: null });
  const express = departure({ id: 'express', routeId: '9', trainType: 'Express' });
  const board = buildBoard(payload([serviceDay('2026-10-22', [fLiner, express])]),
    { nowMs: JST('2026-10-22T05:00:00') });
  const fCard = board.items.find(item => item.sourceId === 'f-liner');
  const eCard = board.items.find(item => item.sourceId === 'express');
  assert.equal(fCard.kind, 'Fライナー');
  assert.equal(fCard.kindCode, 'F-Liner');
  assert.equal(fCard.reportedTrainType, 'F-Liner');
  assert.equal(fCard.serviceBrand, null);
  assert.equal(eCard.kind, '急行');
});

test('confirmed ODPT type provenance and matcher diagnostics survive card conversion', () => {
  const fLiner = departure({ id: 'scoped-f-liner', routeId: '9', trainType: null,
    reportedTrainType: 'F-Liner', serviceBrand: 'F-Liner', typeLabel: 'Fライナー',
    odptTrainTypeUri: 'odpt.TrainType:TokyoMetro.F-Liner',
    otherOperatorTrainType: null, unscopedTrainType: null,
    odptMatchMethod: 'normalized_number+exact_time+destination+stop_order',
    odptMatchReason: 'route_calendar_number_exact_time_destination_and_stop_order_match' });
  const board = buildBoard(payload([serviceDay('2026-10-22', [fLiner])]),
    { nowMs: JST('2026-10-22T05:00:00') });
  assert.equal(board.items[0].kind, 'Fライナー');
  assert.equal(board.items[0].serviceBrand, 'F-Liner');
  assert.equal(board.items[0].odptTrainTypeUri, 'odpt.TrainType:TokyoMetro.F-Liner');
  assert.equal(board.items[0].odptMatchMethod, 'normalized_number+exact_time+destination+stop_order');
});

test('official route-rule label preserves the ODPT reported type and match provenance', () => {
  const row = departure({ id: 'route-rule', routeId: '6', trainType: 'Local',
    reportedTrainType: 'SemiExpress', typeLabel: '各駅停車', typeSource: 'official_route_rule',
    stopPattern: 'all_stops_to_kotake_segment', typeValidation: 'consistent',
    typeDiagnostic: 'yurakucho_all_stops_official_route_rule',
    odptMatchStatus: 'unique_match', unscopedTrainType: 'SemiExpress' });
  const board = buildBoard(payload([serviceDay('2026-10-22', [row])]),
    { nowMs: JST('2026-10-22T05:00:00') });
  assert.equal(board.items[0].kind, '各駅停車');
  assert.equal(board.items[0].kindCode, 'Local');
  assert.equal(board.items[0].reportedTrainType, 'SemiExpress');
  assert.equal(board.items[0].unscopedTrainType, 'SemiExpress');
  assert.equal(board.items[0].typeSource, 'official_route_rule');
  assert.equal(board.items[0].odptMatchStatus, 'unique_match');
});

test('stop-pattern labels retain source, avoid assigning F-Liner, and hold conflicts', () => {
  const inferred = departure({ id: 'pattern-commuter', routeId: '9', trainType: 'CommuterExpress',
    reportedTrainType: null, typeLabel: '通勤急行', typeSource: 'gtfs_stop_pattern',
    stopPattern: 'commuter_express', typeValidation: 'consistent' });
  const expressPattern = departure({ id: 'pattern-express', tripId: 'pattern-express', routeId: '9',
    trainType: null, reportedTrainType: null, serviceBrand: null, typeLabel: '急行型',
    typeSource: 'gtfs_stop_pattern', stopPattern: 'express_pattern',
    typeValidation: 'not_applicable', typeDiagnostic: 'brand_unresolved' });
  const conflict = departure({ id: 'conflict', tripId: 'conflict', routeId: '9', trainType: null,
    reportedTrainType: 'F-Liner', typeLabel: '種別不明', typeSource: 'unknown',
    stopPattern: 'local', typeValidation: 'conflict', typeDiagnostic: 'odpt_stop_pattern_conflict',
    odptMatchStatus: 'unique_match' });
  const board = buildBoard(payload([serviceDay('2026-10-22', [inferred, expressPattern, conflict])]),
    { nowMs: JST('2026-10-22T05:00:00') });
  const commuterCard = board.items.find(item => item.sourceId === 'pattern-commuter');
  const expressCard = board.items.find(item => item.sourceId === 'pattern-express');
  const conflictCard = board.items.find(item => item.sourceId === 'conflict');
  assert.equal(commuterCard.kind, '通勤急行');
  assert.equal(commuterCard.typeSource, 'gtfs_stop_pattern');
  assert.equal(expressCard.kind, '急行型');
  assert.equal(expressCard.kindCode, null);
  assert.equal(expressCard.serviceBrand, null);
  assert.notEqual(expressCard.kind, 'Fライナー');
  assert.equal(conflictCard.kind, '種別不明');
  assert.equal(conflictCard.reportedTrainType, 'F-Liner');
  assert.equal(conflictCard.typeValidation, 'conflict');
});

test('invalid payloads are rejected with a validation error', () => {
  const invalidSchema = payload([]);
  invalidSchema.schemaVersion = 2;
  assert.throws(() => validateTimetablePayload(invalidSchema), PayloadValidationError);

  const invalidTime = departure({ id: 'bad-time' });
  invalidTime.departureServiceSeconds = -1;
  assert.throws(() => buildBoard(payload([serviceDay('2026-10-22', [invalidTime])]),
    { nowMs: JST('2026-10-22T05:00:00') }), /departureServiceSeconds/);

  const invalidTransfer = transfer(6 * 3600 + 12 * 60);
  invalidTransfer.transfer = null;
  const badJourney = departure({ id: 'bad-transfer', primary: invalidTransfer,
    directAlternative: direct(6 * 3600 + 15 * 60), bestTransferAlternative: invalidTransfer });
  assert.throws(() => buildBoard(payload([serviceDay('2026-10-22', [badJourney])]),
    { nowMs: JST('2026-10-22T05:00:00') }), PayloadValidationError);
});

test('application period is start-inclusive and end-exclusive, with safe states', () => {
  const source = payload([]);
  source.generatedAt = '2026-10-20T14:00:00+00:00';
  assert.equal(buildBoard(source, { nowMs: JST('2026-10-20T23:59:59') }).validity, 'not_started');
  assert.equal(buildBoard(source, { nowMs: JST('2026-10-21T00:00:00') }).validity, 'valid');
  source.generatedAt = '2026-10-23T02:00:00+00:00';
  assert.equal(buildBoard(source, { nowMs: JST('2026-10-23T23:59:59') }).validity, 'valid');
  assert.equal(buildBoard(source, { nowMs: JST('2026-10-23T23:59:59') }).serviceState, 'no_service');
  const expired = buildBoard(source, { nowMs: JST('2026-10-24T00:00:00') });
  assert.equal(expired.validity, 'expired');
  assert.equal(expired.serviceState, 'unavailable');
  source.generatedAt = '2026-10-24T00:00:00+09:00';
  assert.equal(buildBoard(source, { nowMs: JST('2026-10-23T12:00:00') }).validity, 'invalid');
  source.applicationPeriod = undefined;
  assert.throws(() => buildBoard(source), /applicationPeriod/);
});

test('payload remains valid after 24 hours when needed service dates are present', () => {
  const source = payload([]);
  assert.equal(buildBoard(source, { nowMs: JST('2026-10-23T00:00:01') }).validity, 'valid');
});

test('missing a required service date fails closed and reports the missing date', () => {
  const source = payload([]);
  source.serviceDays = source.serviceDays.filter(day => day.serviceDate !== '2026-10-23');
  const board = buildBoard(source, { nowMs: JST('2026-10-22T05:00:00') });
  assert.equal(board.validity, 'missing_service_days');
  assert.equal(board.serviceState, 'unavailable');
  assert.deepEqual(board.diagnostics.missingServiceDates, ['2026-10-23']);
  assert.equal(board.items.length, 0);
});

test('destination payload keeps selected target separate from train headsign', () => {
  const row = departure({ id: 'kanamecho', destination: '和光市', primary: direct(6 * 3600 + 480,
    { arrivalStationId: 'Kanamecho' }), directAlternative: direct(6 * 3600 + 480,
    { arrivalStationId: 'Kanamecho' }) });
  const state = {
    status: 'normal', candidateCount: 1, passThroughCount: 0, dataInsufficientCount: 0,
    routes: {
      '6': { originTripCount: 1, candidateCount: 1, passThroughCount: 0, dataInsufficientCount: 0 },
      '9': { originTripCount: 0, candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 0 },
    },
  };
  const day = serviceDay('2026-10-22', [row], 'Kanamecho');
  day.destinationStatus = state;
  const board = buildBoard(payload([day]), { nowMs: JST('2026-10-22T05:00:00') });
  assert.equal(board.destinationStationId, 'Kanamecho');
  assert.equal(board.items[0].destinationStationId, 'Kanamecho');
  assert.equal(board.items[0].arrivalStationId, 'Kanamecho');
  assert.equal(board.items[0].headsign, '和光市');
  assert.equal(board.destinationStates[0].status, 'normal');
});

test('transfer-capable destination validates direct and transfer counts separately', () => {
  const target = 'Heiwadai';
  const row = departure({
    id: 'heiwadai-transfer',
    destination: '和光市',
    primary: Object.assign(transfer(6 * 3600 + 720, 120), { arrivalStationId: target }),
    directAlternative: direct(6 * 3600 + 1400, { arrivalStationId: target }),
    bestTransferAlternative: Object.assign(transfer(6 * 3600 + 720, 120), { arrivalStationId: target }),
  });
  const state = {
    status: 'normal', candidateCount: 1, directCandidateCount: 1,
    transferCandidateCount: 1, transferPairCount: 2, transferOnlyCount: 0,
    passThroughCount: 0, transferPassThroughCount: 1,
    dataInsufficientCount: 0, transferDataInsufficientCount: 0,
    routes: {
      '6': { originTripCount: 1, candidateCount: 1, passThroughCount: 0, dataInsufficientCount: 0,
        directCandidateCount: 1, transferCandidateCount: 1, transferPairCount: 2, transferOnlyCount: 0 },
      '9': { originTripCount: 0, candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 0,
        directCandidateCount: 0, transferCandidateCount: 0, transferPairCount: 0, transferOnlyCount: 0 },
    },
  };
  const day = serviceDay('2026-10-22', [row], target);
  day.destinationStatus = state;
  const board = buildBoard(payload([day]), { nowMs: JST('2026-10-22T05:00:00') });
  assert.equal(board.validity, 'valid');
  assert.equal(board.items[0].arrivalStationId, target);
  assert.equal(board.items[0].headsign, '和光市');
  assert.equal(board.items[0].transfer.wait, 2);

  const badMetrics = structuredClone(payload([day]));
  badMetrics.serviceDays.find(item => item.serviceDate === '2026-10-22')
    .destinationStatus.transferPairCount = 1;
  assert.throws(() => validateTimetablePayload(badMetrics), /transfer metrics must match/);
});

test('destination insufficient data fails closed while a verified empty day stays distinct', () => {
  const insufficient = serviceDay('2026-10-22', [], 'Senkawa');
  insufficient.destinationStatus = {
    status: 'data_insufficient', candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 1,
    routes: {
      '6': { originTripCount: 0, candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 1 },
      '9': { originTripCount: 0, candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 0 },
    },
  };
  const blocked = buildBoard(payload([insufficient]), { nowMs: JST('2026-10-22T05:00:00') });
  assert.equal(blocked.validity, 'destination_data_insufficient');
  assert.equal(blocked.items.length, 0);

  const empty = serviceDay('2026-10-22', [], 'Senkawa');
  empty.destinationStatus = {
    status: 'no_candidates', candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 0,
    routes: {
      '6': { originTripCount: 0, candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 0 },
      '9': { originTripCount: 0, candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 0 },
    },
  };
  const noCandidates = buildBoard(payload([empty]), { nowMs: JST('2026-10-22T05:00:00') });
  assert.equal(noCandidates.validity, 'valid');
  assert.equal(noCandidates.items.length, 0);

  for (const [stateName, expectedValidity] of [['unsupported', 'destination_unsupported'],
    ['invalid', 'destination_invalid']]) {
    const blockedDay = serviceDay('2026-10-22', [], 'Senkawa');
    blockedDay.destinationStatus = {
      status: stateName, candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 0,
      routes: {
        '6': { originTripCount: 0, candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 0 },
        '9': { originTripCount: 0, candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 0 },
      },
    };
    const result = buildBoard(payload([blockedDay]), { nowMs: JST('2026-10-22T05:00:00') });
    assert.equal(result.validity, expectedValidity);
    assert.equal(result.items.length, 0);
  }
});

test('invalid destination ID and conflicting service-day targets are rejected', () => {
  const unknown = serviceDay('2026-10-22', [], 'UnknownStation');
  assert.throws(() => validateTimetablePayload(payload([unknown])), PayloadValidationError);
  const missingState = serviceDay('2026-10-22', [], 'Kanamecho');
  delete missingState.destinationStatus;
  assert.throws(() => validateTimetablePayload(payload([missingState])), /required for non-default destinations/);
  const conflicting = payload([
    Object.assign(serviceDay('2026-10-21', [], 'Kanamecho'), { destinationStatus: emptyDestinationStatus() }),
    Object.assign(serviceDay('2026-10-22', [], 'Senkawa'), { destinationStatus: emptyDestinationStatus() }),
  ]);
  assert.throws(() => validateTimetablePayload(conflicting), /destination must be consistent/);
});

test('invalid options and service dates fail clearly', () => {
  assert.throws(() => serviceSecondsToEpochMs('2026-02-30', 1), PayloadValidationError);
  assert.throws(() => buildBoard(payload([]), { nowMs: Number.NaN }), /nowMs/);
  assert.throws(() => buildBoard(payload([]), { mode: 'unknown' }), /mode/);
});
