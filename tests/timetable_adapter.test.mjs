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

function serviceDay(serviceDate, departures) {
  return {
    serviceDate,
    originStationId: 'Ikebukuro',
    destinationStationId: 'Hikawadai',
    departures,
  };
}

function payload(serviceDays = []) {
  return {
    schemaVersion: 1,
    dataScope: 'local-preview-only',
    generatedAt: '2026-10-22T00:00:00+00:00',
    timezone: 'Asia/Tokyo',
    feed: { version: 'test-feed', validFrom: '2026-10-21', validThrough: '2026-10-23' },
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

  assert.equal(board.items.length, 2);
  assert.equal(board.diagnostics.duplicateCount, 1);
  assert.equal(board.items[0].serviceDate, '2026-10-21');
  assert.equal(board.items[0].departureText, '00:10');
  assert.equal(board.items[1].serviceDate, '2026-10-23');
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

test('line mode groups by route while departure mode sorts all lines by time', () => {
  const firstF = departure({ id: 'F-early', routeId: '9', serviceSeconds: 6 * 3600,
    primary: journeyAt(6 * 3600, 6 * 3600 + 600), directAlternative: journeyAt(6 * 3600, 6 * 3600 + 600) });
  const laterY = departure({ id: 'Y-late', tripId: 'Y-late', routeId: '6', serviceSeconds: 6 * 3600 + 120,
    primary: journeyAt(6 * 3600 + 120, 6 * 3600 + 600), directAlternative: journeyAt(6 * 3600 + 120, 6 * 3600 + 600) });
  const earlierY = departure({ id: 'Y-early', tripId: 'Y-early', routeId: '6', serviceSeconds: 6 * 3600 + 60,
    primary: journeyAt(6 * 3600 + 60, 6 * 3600 + 600), directAlternative: journeyAt(6 * 3600 + 60, 6 * 3600 + 600) });
  const source = payload([serviceDay('2026-10-22', [firstF, laterY, earlierY])]);
  const now = JST('2026-10-22T05:00:00');
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
    { nowMs: JST('2026-10-22T05:00:00') });
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

test('invalid options and service dates fail clearly', () => {
  assert.throws(() => serviceSecondsToEpochMs('2026-02-30', 1), PayloadValidationError);
  assert.throws(() => buildBoard(payload([]), { nowMs: Number.NaN }), /nowMs/);
  assert.throws(() => buildBoard(payload([]), { mode: 'unknown' }), /mode/);
});
