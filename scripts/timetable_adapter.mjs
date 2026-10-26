/** Convert the local-preview timetable payload into UI-facing train cards. */

export const TOKYO_TIME_ZONE = 'Asia/Tokyo';
export const DEFAULT_HORIZON_MS = 24 * 60 * 60 * 1000;
export const LOCAL_DATA_SCOPE = 'local-preview-only';
export const PUBLIC_DATA_SCOPE = 'public-display-v1';
const SUPPORTED_DATA_SCOPES = new Set([LOCAL_DATA_SCOPE, PUBLIC_DATA_SCOPE]);

const TIME_FORMATTER = new Intl.DateTimeFormat('en-GB', {
  timeZone: TOKYO_TIME_ZONE, hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});
const DATE_FORMATTER = new Intl.DateTimeFormat('en-CA', {
  timeZone: TOKYO_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
});
const DATETIME_FORMATTER = new Intl.DateTimeFormat('ja-JP', {
  timeZone: TOKYO_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});
const PREPARED_PAYLOADS = new WeakMap();

const ROUTE_PRESENTATION = Object.freeze({
  '6': Object.freeze({ line: '有楽町線', color: '#c1a026', order: 0 }),
  '9': Object.freeze({ line: '副都心線', color: '#9C5E31', order: 1 }),
});
const DESTINATION_STATION_IDS = new Set([
  'Kanamecho', 'Senkawa', 'KotakeMukaihara', 'Hikawadai', 'Heiwadai',
  'ChikatetsuAkatsuka', 'ChikatetsuNarimasu', 'Wakoshi',
]);
const TRANSFER_DESTINATION_STATION_IDS = new Set([
  'Heiwadai', 'ChikatetsuAkatsuka', 'ChikatetsuNarimasu', 'Wakoshi',
]);
const DEFAULT_DESTINATION_STATION_ID = 'Hikawadai';

const TRAIN_TYPE_LABELS = Object.freeze({
  Local: '各駅停車',
  Express: '急行',
  CommuterExpress: '通勤急行',
  SemiExpress: '準急',
  Rapid: '快速',
  RapidExpress: '快速急行',
  'F-Liner': 'Fライナー',
  'S-TRAIN': 'S-TRAIN',
});
const TYPE_SOURCES = new Set(['odpt_confirmed', 'official_route_rule', 'gtfs_stop_pattern', 'unknown']);
const TYPE_VALIDATIONS = new Set(['consistent', 'unverifiable', 'conflict', 'not_applicable', 'unmatched']);

export class PayloadValidationError extends TypeError {
  constructor(message) {
    super(message);
    this.name = 'PayloadValidationError';
  }
}

function fail(path, message) {
  throw new PayloadValidationError(`${path}: ${message}`);
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function requireObject(value, path) {
  if (!isObject(value)) fail(path, 'object required');
  return value;
}

function requireString(value, path, { nullable = false, nonempty = true } = {}) {
  if (nullable && value === null) return null;
  if (typeof value !== 'string' || (nonempty && value.trim() === '')) {
    fail(path, nullable ? 'string or null required' : 'nonempty string required');
  }
  return value;
}

function requireInteger(value, path, { nullable = false, minimum = 0 } = {}) {
  if (nullable && value === null) return null;
  if (!Number.isSafeInteger(value) || value < minimum) {
    fail(path, nullable ? `integer >= ${minimum} or null required` : `integer >= ${minimum} required`);
  }
  return value;
}

function isIsoDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const calendarDate = new Date(Date.UTC(year, month - 1, day));
  return calendarDate.toISOString().slice(0, 10) === value;
}

function requireDate(value, path) {
  if (!isIsoDate(value)) fail(path, 'valid YYYY-MM-DD date required');
  return value;
}

function requireTimestamp(value, path, { nullable = false } = {}) {
  if (nullable && value === null) return null;
  if (typeof value !== 'string' || !isIsoDate(value.slice(0, 10))
      || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value)
      || !Number.isFinite(Date.parse(value))) fail(path, 'ISO timestamp with timezone required');
  return value;
}

function requireBoolean(value, path) {
  if (typeof value !== 'boolean') fail(path, 'boolean required');
  return value;
}

function serviceDayStartMs(serviceDate) {
  requireDate(serviceDate, 'serviceDate');
  const [year, month, day] = serviceDate.split('-').map(Number);
  return Date.UTC(year, month - 1, day) - 9 * 60 * 60 * 1000;
}

export function serviceSecondsToEpochMs(serviceDate, serviceSeconds) {
  requireInteger(serviceSeconds, 'serviceSeconds');
  return serviceDayStartMs(serviceDate) + serviceSeconds * 1000;
}

export function formatTokyoTime(epochMs) {
  if (!Number.isFinite(epochMs)) throw new TypeError('epochMs must be finite');
  const parts = TIME_FORMATTER.formatToParts(new Date(epochMs));
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${values.hour}:${values.minute}`;
}

function formatTokyoDateTime(epochMs) {
  return DATETIME_FORMATTER.format(new Date(epochMs));
}

function validityPresentation(validity, startsAtMs, endsAtMs) {
  const periodText = `${formatTokyoDateTime(startsAtMs)}〜${formatTokyoDateTime(endsAtMs)}（終了時刻を含まない）`;
  const messages = {
    valid: `ダイヤ適用期限 ${formatTokyoDateTime(endsAtMs - 60_000)}まで`,
    not_started: `この時刻表はまだ適用前です（${periodText}）。更新が必要です。`,
    expired: `この時刻表の適用期間は終了しました（${periodText}）。更新が必要です。`,
    missing_service_days: '現在必要な運行日の時刻表データがありません。previewを再生成してください。',
    destination_data_insufficient: '目的地までの停車・乗降・時刻データが不足しています。previewを再生成してください。',
    destination_unsupported: 'この目的地はまだ検証されていません。対応済みの目的地を選んでください。',
    destination_invalid: '目的地IDが不正です。previewデータを確認してください。',
    invalid: '時刻表の生成日時が現在より未来です。安全のため列車を表示しません。更新が必要です。',
  };
  return { validityLabel: validity === 'valid' ? '実ダイヤ' : '要更新', statusMessage: messages[validity], periodText };
}

function tokyoCalendarDate(epochMs) {
  const parts = DATE_FORMATTER.formatToParts(new Date(epochMs));
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

/** Validate once and precompute immutable display cards for fast local UI toggles. */
export function prepareTimetablePayload(payload, expectedProfile = LOCAL_DATA_SCOPE) {
  validateTimetablePayload(payload, expectedProfile);
  const entries = [];
  for (const day of payload.serviceDays) {
    for (const departure of day.departures) {
      entries.push({
        day,
        departure,
        primary: departure.primary ? makeCard(day, departure, departure.primary) : null,
        direct: departure.directAlternative ? makeCard(day, departure, departure.directAlternative) : null,
      });
    }
  }
  const prepared = Object.freeze({ schemaVersion: payload.schemaVersion });
  PREPARED_PAYLOADS.set(prepared, { payload, entries, expectedProfile });
  return prepared;
}

function addCalendarDays(isoDate, days) {
  const [year, month, day] = isoDate.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

function validateJourney(value, path, expectedKind = null) {
  if (value === null) return null;
  const journey = requireObject(value, path);
  if (!['direct', 'transfer'].includes(journey.kind)) fail(`${path}.kind`, 'direct or transfer required');
  if (expectedKind && journey.kind !== expectedKind) fail(`${path}.kind`, `expected ${expectedKind}`);
  requireInteger(journey.departureServiceSeconds, `${path}.departureServiceSeconds`);
  requireInteger(journey.arrivalServiceSeconds, `${path}.arrivalServiceSeconds`, { nullable: true });
  requireString(journey.departureText, `${path}.departureText`, { nullable: true });
  requireString(journey.arrivalText, `${path}.arrivalText`, { nullable: true });
  requireString(journey.arrivalStationId, `${path}.arrivalStationId`, { nullable: true });
  requireString(journey.platformStatus, `${path}.platformStatus`);
  requireBoolean(journey.connectionGuaranteed, `${path}.connectionGuaranteed`);
  if (journey.kind === 'direct') {
    if (journey.transfer !== null) fail(`${path}.transfer`, 'must be null for direct journey');
  } else {
    const transfer = requireObject(journey.transfer, `${path}.transfer`);
    requireString(transfer.stationId, `${path}.transfer.stationId`);
    requireString(transfer.stationName, `${path}.transfer.stationName`, { nullable: true });
    requireInteger(transfer.waitSeconds, `${path}.transfer.waitSeconds`);
    requireString(transfer.outgoingRouteId, `${path}.transfer.outgoingRouteId`);
    requireString(transfer.outgoingRouteName, `${path}.transfer.outgoingRouteName`);
    requireString(transfer.outgoingHeadsign, `${path}.transfer.outgoingHeadsign`, { nullable: true });
    requireString(transfer.outgoingTrainType, `${path}.transfer.outgoingTrainType`, { nullable: true });
    if (transfer.outgoingReportedTrainType !== undefined) {
      requireString(transfer.outgoingReportedTrainType, `${path}.transfer.outgoingReportedTrainType`, { nullable: true });
    }
    if (transfer.outgoingServiceBrand !== undefined) {
      requireString(transfer.outgoingServiceBrand, `${path}.transfer.outgoingServiceBrand`, { nullable: true });
    }
    for (const key of ['outgoingOdptTrainTypeUri', 'outgoingOtherOperatorType', 'outgoingUnscopedTrainType',
      'outgoingMatchMethod', 'outgoingMatchReason']) {
      if (transfer[key] !== undefined) requireString(transfer[key], `${path}.transfer.${key}`, { nullable: true });
    }
    if (transfer.outgoingTypeLabel !== undefined) requireString(transfer.outgoingTypeLabel, `${path}.transfer.outgoingTypeLabel`);
    if (transfer.outgoingTypeSource !== undefined && !TYPE_SOURCES.has(transfer.outgoingTypeSource)) {
      fail(`${path}.transfer.outgoingTypeSource`, 'unsupported type source');
    }
    if (transfer.outgoingStopPattern !== undefined) requireString(transfer.outgoingStopPattern, `${path}.transfer.outgoingStopPattern`, { nullable: true });
    if (transfer.outgoingTypeValidation !== undefined && !TYPE_VALIDATIONS.has(transfer.outgoingTypeValidation)) {
      fail(`${path}.transfer.outgoingTypeValidation`, 'unsupported validation state');
    }
    if (!Array.isArray(transfer.outgoingDestinationIds)
        || transfer.outgoingDestinationIds.some(item => typeof item !== 'string')) {
      fail(`${path}.transfer.outgoingDestinationIds`, 'array of strings required');
    }
  }
  return journey;
}

/** Validate the versioned payload against the caller's expected data profile. */
export function validateTimetablePayload(payload, expectedProfile = LOCAL_DATA_SCOPE) {
  requireObject(payload, 'payload');
  if (!SUPPORTED_DATA_SCOPES.has(expectedProfile)) {
    fail('expectedProfile', 'unsupported data profile');
  }
  if (payload.schemaVersion !== 1) fail('payload.schemaVersion', 'unsupported schema version');
  if (payload.dataScope !== expectedProfile) {
    fail('payload.dataScope', `${expectedProfile} required; received ${String(payload.dataScope)}`);
  }
  if (payload.timezone !== TOKYO_TIME_ZONE) fail('payload.timezone', `must be ${TOKYO_TIME_ZONE}`);
  if (typeof payload.generatedAt !== 'string' || !Number.isFinite(Date.parse(payload.generatedAt))) {
    fail('payload.generatedAt', 'valid timestamp required');
  }

  const feed = requireObject(payload.feed, 'payload.feed');
  requireString(feed.version, 'payload.feed.version');
  requireDate(feed.validFrom, 'payload.feed.validFrom');
  requireDate(feed.validThrough, 'payload.feed.validThrough');
  if (feed.validFrom > feed.validThrough) fail('payload.feed', 'validFrom must not follow validThrough');
  requireTimestamp(feed.sourceUpdatedAt, 'payload.feed.sourceUpdatedAt', { nullable: true });
  const odpt = requireObject(payload.odpt, 'payload.odpt');
  requireTimestamp(odpt.sourceUpdatedAt, 'payload.odpt.sourceUpdatedAt', { nullable: true });
  const applicationPeriod = requireObject(payload.applicationPeriod, 'payload.applicationPeriod');
  requireTimestamp(applicationPeriod.startsAt, 'payload.applicationPeriod.startsAt');
  requireTimestamp(applicationPeriod.endsAt, 'payload.applicationPeriod.endsAt');
  if (Date.parse(applicationPeriod.endsAt) <= Date.parse(applicationPeriod.startsAt)) {
    fail('payload.applicationPeriod', 'endsAt must follow startsAt');
  }
  const webApp = requireObject(payload.webApp, 'payload.webApp');
  requireTimestamp(webApp.builtAt, 'payload.webApp.builtAt', { nullable: true });

  const policy = requireObject(payload.connectionPolicy, 'payload.connectionPolicy');
  requireInteger(policy.minimumWaitSeconds, 'payload.connectionPolicy.minimumWaitSeconds');
  requireInteger(policy.maximumWaitSeconds, 'payload.connectionPolicy.maximumWaitSeconds');
  if (policy.maximumWaitSeconds < policy.minimumWaitSeconds) {
    fail('payload.connectionPolicy', 'maximum wait must be >= minimum wait');
  }
  requireString(policy.platformStatus, 'payload.connectionPolicy.platformStatus');
  requireBoolean(policy.connectionGuaranteed, 'payload.connectionPolicy.connectionGuaranteed');

  if (!Array.isArray(payload.serviceDays)) fail('payload.serviceDays', 'array required');
  if (!Array.isArray(payload.excludedServiceDates)
      || payload.excludedServiceDates.some((value, index) => !isIsoDate(value))) {
    fail('payload.excludedServiceDates', 'array of YYYY-MM-DD dates required');
  }
  const seenDays = new Set();
  const destinationIds = new Set();
  payload.serviceDays.forEach((rawDay, dayIndex) => {
    const path = `payload.serviceDays[${dayIndex}]`;
    const day = requireObject(rawDay, path);
    requireDate(day.serviceDate, `${path}.serviceDate`);
    if (seenDays.has(day.serviceDate)) fail(`${path}.serviceDate`, 'duplicate service day');
    seenDays.add(day.serviceDate);
    requireString(day.originStationId, `${path}.originStationId`);
    requireString(day.destinationStationId, `${path}.destinationStationId`);
    if (!DESTINATION_STATION_IDS.has(day.destinationStationId)) {
      fail(`${path}.destinationStationId`, 'unsupported destination station ID');
    }
    destinationIds.add(day.destinationStationId);
    if (!Array.isArray(day.departures)) fail(`${path}.departures`, 'array required');
    day.departures.forEach((rawDeparture, departureIndex) => {
      const itemPath = `${path}.departures[${departureIndex}]`;
      const item = requireObject(rawDeparture, itemPath);
      requireString(item.id, `${itemPath}.id`);
      requireString(item.originTripId, `${itemPath}.originTripId`);
      requireString(item.routeId, `${itemPath}.routeId`);
      if (!ROUTE_PRESENTATION[item.routeId]) fail(`${itemPath}.routeId`, 'unsupported route');
      requireString(item.routeName, `${itemPath}.routeName`);
      requireString(item.headsign, `${itemPath}.headsign`, { nullable: true });
      requireString(item.trainType, `${itemPath}.trainType`, { nullable: true });
      if (item.reportedTrainType !== undefined) {
        requireString(item.reportedTrainType, `${itemPath}.reportedTrainType`, { nullable: true });
      }
      if (item.serviceBrand !== undefined) {
        requireString(item.serviceBrand, `${itemPath}.serviceBrand`, { nullable: true });
      }
      for (const key of ['odptTrainTypeUri', 'otherOperatorTrainType', 'unscopedTrainType', 'odptMatchMethod', 'odptMatchReason']) {
        if (item[key] !== undefined) requireString(item[key], `${itemPath}.${key}`, { nullable: true });
      }
      if (item.typeLabel !== undefined) requireString(item.typeLabel, `${itemPath}.typeLabel`);
      if (item.typeSource !== undefined && !TYPE_SOURCES.has(item.typeSource)) {
        fail(`${itemPath}.typeSource`, 'unsupported type source');
      }
      if (item.stopPattern !== undefined) requireString(item.stopPattern, `${itemPath}.stopPattern`, { nullable: true });
      if (item.stopPatternStates !== undefined) {
        const states = requireObject(item.stopPatternStates, `${itemPath}.stopPatternStates`);
        for (const [key, value] of Object.entries(states)) requireString(value, `${itemPath}.stopPatternStates.${key}`);
      }
      if (item.typeValidation !== undefined && !TYPE_VALIDATIONS.has(item.typeValidation)) {
        fail(`${itemPath}.typeValidation`, 'unsupported validation state');
      }
      if (item.typeDiagnostic !== undefined) requireString(item.typeDiagnostic, `${itemPath}.typeDiagnostic`, { nullable: true });
      requireString(item.destination, `${itemPath}.destination`, { nullable: true });
      if (item.destinationSource !== undefined) {
        requireString(item.destinationSource, `${itemPath}.destinationSource`, { nullable: true });
      }
      if (!Array.isArray(item.odptDestinationIds)
          || item.odptDestinationIds.some(value => typeof value !== 'string')) {
        fail(`${itemPath}.odptDestinationIds`, 'array of strings required');
      }
      requireString(item.odptMatchStatus, `${itemPath}.odptMatchStatus`);
      requireInteger(item.departureServiceSeconds, `${itemPath}.departureServiceSeconds`);
      requireString(item.departureText, `${itemPath}.departureText`);
      const journeys = [
        validateJourney(item.primary, `${itemPath}.primary`),
        validateJourney(item.directAlternative, `${itemPath}.directAlternative`, 'direct'),
        validateJourney(item.bestTransferAlternative, `${itemPath}.bestTransferAlternative`, 'transfer'),
      ].filter(Boolean);
      for (const journey of journeys) {
        if (journey.arrivalStationId !== day.destinationStationId) {
          fail(itemPath, 'journey arrival station must match selected destination');
        }
        if (journey.departureServiceSeconds !== item.departureServiceSeconds) {
          fail(itemPath, 'journey departure must match origin departure');
        }
        if (journey.arrivalServiceSeconds !== null
            && journey.arrivalServiceSeconds < journey.departureServiceSeconds) {
          fail(itemPath, 'journey arrival must not precede origin departure');
        }
        if (journey.kind === 'transfer') {
          if (journey.transfer.waitSeconds < policy.minimumWaitSeconds
              || journey.transfer.waitSeconds > policy.maximumWaitSeconds) {
            fail(itemPath, 'transfer wait does not satisfy payload policy');
          }
          if (journey.transfer.outgoingRouteId === item.routeId) {
            fail(itemPath, 'transfer must use the opposite route');
          }
        }
      }
      requireInteger(item.transferCandidateCount, `${itemPath}.transferCandidateCount`);
      requireString(item.status, `${itemPath}.status`);
      if (!Array.isArray(item.dataQuality)
          || item.dataQuality.some(value => typeof value !== 'string')) {
        fail(`${itemPath}.dataQuality`, 'array of strings required');
      }
    });
    if (day.destinationStationId !== DEFAULT_DESTINATION_STATION_ID && day.destinationStatus === undefined) {
      fail(`${path}.destinationStatus`, 'required for non-default destinations');
    }
    if (day.destinationStatus !== undefined) {
      const state = requireObject(day.destinationStatus, `${path}.destinationStatus`);
      const transferMetricsRequired = TRANSFER_DESTINATION_STATION_IDS.has(day.destinationStationId);
      if (transferMetricsRequired) {
        for (const key of ['directCandidateCount', 'transferCandidateCount', 'transferPairCount',
          'transferOnlyCount', 'transferPassThroughCount', 'transferDataInsufficientCount']) {
          requireInteger(state[key], `${path}.destinationStatus.${key}`);
        }
      }
      if (!['normal', 'no_candidates', 'data_insufficient', 'unsupported', 'invalid'].includes(state.status)) {
        fail(`${path}.destinationStatus.status`, 'unsupported destination status');
      }
      for (const key of ['candidateCount', 'passThroughCount', 'dataInsufficientCount']) {
        requireInteger(state[key], `${path}.destinationStatus.${key}`);
      }
      if (state.transferDataInsufficientCount !== undefined) {
        requireInteger(state.transferDataInsufficientCount,
          `${path}.destinationStatus.transferDataInsufficientCount`);
      }
      const routes = requireObject(state.routes, `${path}.destinationStatus.routes`);
      for (const routeId of Object.keys(ROUTE_PRESENTATION)) {
        const counts = requireObject(routes[routeId], `${path}.destinationStatus.routes.${routeId}`);
        for (const key of ['originTripCount', 'candidateCount', 'passThroughCount', 'dataInsufficientCount']) {
          requireInteger(counts[key], `${path}.destinationStatus.routes.${routeId}.${key}`);
        }
        for (const key of ['scheduledTripCount', 'transferDataInsufficientCount']) {
          if (counts[key] !== undefined) {
            requireInteger(counts[key], `${path}.destinationStatus.routes.${routeId}.${key}`);
          }
        }
        if (counts.scheduledTripCount !== undefined
            && counts.scheduledTripCount < counts.originTripCount) {
          fail(`${path}.destinationStatus.routes.${routeId}.scheduledTripCount`,
            'must cover origin trip count');
        }
        if (transferMetricsRequired) {
          for (const key of ['directCandidateCount', 'transferCandidateCount', 'transferPairCount',
            'transferOnlyCount']) {
            requireInteger(counts[key], `${path}.destinationStatus.routes.${routeId}.${key}`);
          }
        }
      }
      const routeTotals = Object.values(routes).reduce((totals, counts) => {
        for (const key of ['originTripCount', 'candidateCount', 'passThroughCount', 'dataInsufficientCount']) {
          totals[key] += counts[key];
        }
        if (transferMetricsRequired) {
          for (const key of ['directCandidateCount', 'transferCandidateCount', 'transferPairCount',
            'transferOnlyCount']) totals[key] += counts[key];
        }
        return totals;
      }, { originTripCount: 0, candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 0,
        directCandidateCount: 0, transferCandidateCount: 0, transferPairCount: 0, transferOnlyCount: 0 });
      for (const key of ['candidateCount', 'passThroughCount']) {
        if (state[key] !== routeTotals[key]) fail(`${path}.destinationStatus.${key}`, 'must match route totals');
      }
      if (!transferMetricsRequired
          && state.dataInsufficientCount !== routeTotals.dataInsufficientCount) {
        fail(`${path}.destinationStatus.dataInsufficientCount`, 'must match route totals');
      }
      if (transferMetricsRequired) {
        if (state.directCandidateCount !== routeTotals.directCandidateCount
            || state.transferCandidateCount !== routeTotals.transferCandidateCount
            || state.transferPairCount !== routeTotals.transferPairCount
            || state.transferOnlyCount !== routeTotals.transferOnlyCount) {
          fail(`${path}.destinationStatus`, 'transfer metrics must match route totals');
        }
        if (state.directCandidateCount !== day.departures.filter(item => item.directAlternative !== null).length
            || state.transferCandidateCount !== day.departures.filter(item => item.bestTransferAlternative !== null).length
            || state.transferPairCount !== day.departures.reduce((sum, item) => sum + item.transferCandidateCount, 0)
            || state.transferOnlyCount !== day.departures.filter(item => item.directAlternative === null
              && item.bestTransferAlternative !== null).length) {
          fail(`${path}.destinationStatus`, 'transfer metrics must match departures');
        }
        if (state.dataInsufficientCount !== routeTotals.dataInsufficientCount
            + state.transferDataInsufficientCount) {
          fail(`${path}.destinationStatus.dataInsufficientCount`, 'must include transfer data insufficiency');
        }
        const routeTransferIssues = Object.values(routes).reduce((sum, counts) =>
          sum + (counts.transferDataInsufficientCount ?? 0), 0);
        if (routeTransferIssues !== 0
            && routeTransferIssues !== state.transferDataInsufficientCount) {
          fail(`${path}.destinationStatus.transferDataInsufficientCount`,
            'must match route transfer data insufficiency');
        }
      }
      if (state.candidateCount !== day.departures.filter(item => item.primary !== null).length) {
        fail(`${path}.destinationStatus.candidateCount`, 'must match journeys with a primary itinerary');
      }
      if (state.status === 'normal' && state.candidateCount === 0) {
        fail(`${path}.destinationStatus.status`, 'normal requires at least one candidate');
      }
      if (state.status === 'no_candidates'
          && (state.candidateCount !== 0 || state.dataInsufficientCount !== 0)) {
        fail(`${path}.destinationStatus.status`, 'no_candidates requires zero candidates and no incomplete data');
      }
      if (state.status === 'data_insufficient'
          && (state.candidateCount !== 0 || state.dataInsufficientCount === 0)) {
        fail(`${path}.destinationStatus.status`, 'data_insufficient requires no candidates and incomplete data');
      }
    }
  });
  if (destinationIds.size > 1) fail('payload.serviceDays', 'destination must be consistent across service days');
  return payload;
}

function makeCard(day, departure, journey) {
  const route = ROUTE_PRESENTATION[departure.routeId];
  const departureAtMs = serviceSecondsToEpochMs(day.serviceDate, departure.departureServiceSeconds);
  const arrivalAtMs = journey.arrivalServiceSeconds === null
    ? null
    : serviceSecondsToEpochMs(day.serviceDate, journey.arrivalServiceSeconds);
  if (arrivalAtMs !== null && arrivalAtMs < departureAtMs) {
    throw new PayloadValidationError(`${departure.id}: arrival precedes departure`);
  }

  const transfer = journey.transfer === null ? null : {
    stationId: journey.transfer.stationId,
    station: journey.transfer.stationName,
    waitSeconds: journey.transfer.waitSeconds,
    wait: journey.transfer.waitSeconds / 60,
    waitMinutes: journey.transfer.waitSeconds / 60,
    outgoingRouteId: journey.transfer.outgoingRouteId,
    outgoingRoute: journey.transfer.outgoingRouteName,
    outgoingHeadsign: journey.transfer.outgoingHeadsign,
    outgoingKind: journey.transfer.outgoingTypeLabel
      ?? TRAIN_TYPE_LABELS[journey.transfer.outgoingTrainType]
      ?? '種別不明',
    outgoingReportedTrainType: journey.transfer.outgoingReportedTrainType
      ?? journey.transfer.outgoingTrainType,
    outgoingServiceBrand: journey.transfer.outgoingServiceBrand ?? null,
    outgoingOdptTrainTypeUri: journey.transfer.outgoingOdptTrainTypeUri ?? null,
    outgoingOtherOperatorType: journey.transfer.outgoingOtherOperatorType ?? null,
    outgoingUnscopedTrainType: journey.transfer.outgoingUnscopedTrainType ?? null,
    outgoingMatchMethod: journey.transfer.outgoingMatchMethod ?? null,
    outgoingMatchReason: journey.transfer.outgoingMatchReason ?? null,
    outgoingDestinationIds: [...journey.transfer.outgoingDestinationIds],
  };
  const reportedTrainType = departure.reportedTrainType ?? departure.trainType;
  const effectiveTrainType = departure.trainType;
  const trainType = TRAIN_TYPE_LABELS[effectiveTrainType ?? reportedTrainType] ?? null;
  const destination = departure.destination?.trim() || null;

  return {
    id: `${departure.routeId}:${departure.originTripId}:${departureAtMs}`,
    sourceId: departure.id,
    serviceDate: day.serviceDate,
    originStationId: day.originStationId,
    destinationStationId: day.destinationStationId,
    arrivalStationId: journey.arrivalStationId,
    originTripId: departure.originTripId,
    routeId: departure.routeId,
    line: route.line,
    color: route.color,
    kind: departure.typeLabel ?? trainType ?? '種別不明',
    kindCode: effectiveTrainType,
    reportedTrainType,
    serviceBrand: departure.serviceBrand ?? null,
    odptTrainTypeUri: departure.odptTrainTypeUri ?? null,
    otherOperatorTrainType: departure.otherOperatorTrainType ?? null,
    unscopedTrainType: departure.unscopedTrainType ?? null,
    odptMatchMethod: departure.odptMatchMethod ?? null,
    odptMatchReason: departure.odptMatchReason ?? null,
    typeSource: departure.typeSource ?? (reportedTrainType ? 'odpt_confirmed' : 'unknown'),
    stopPattern: departure.stopPattern ?? null,
    stopPatternStates: departure.stopPatternStates ? { ...departure.stopPatternStates } : null,
    typeValidation: departure.typeValidation ?? 'not_applicable',
    typeDiagnostic: departure.typeDiagnostic ?? null,
    destination: destination ?? '行き先不明',
    destinationLabel: destination ?? '行き先不明',
    destinationIsKnown: destination !== null,
    destinationSource: departure.destinationSource ?? (departure.headsign ? 'gtfs_headsign' : null),
    headsign: departure.headsign,
    departureAtMs,
    arrivalAtMs,
    departureText: formatTokyoTime(departureAtMs),
    arrivalText: arrivalAtMs === null ? null : formatTokyoTime(arrivalAtMs),
    journeyKind: journey.kind,
    journeyLabel: journey.kind === 'direct' ? '直通・乗換なし' : '小竹向原乗換',
    transfer,
    platformStatus: journey.platformStatus,
    connectionGuaranteed: journey.connectionGuaranteed,
    odptMatchStatus: departure.odptMatchStatus,
    dataQuality: [...departure.dataQuality],
  };
}

function compareDeparture(a, b) {
  return a.departureAtMs - b.departureAtMs
    || ROUTE_PRESENTATION[a.routeId].order - ROUTE_PRESENTATION[b.routeId].order
    || a.serviceDate.localeCompare(b.serviceDate)
    || a.originTripId.localeCompare(b.originTripId);
}

function compareIdentity(a, b) {
  return a.serviceDate.localeCompare(b.serviceDate)
    || a.sourceId.localeCompare(b.sourceId);
}

const ROUTE_IDS = Object.freeze(['6', '9']);
const SERVICE_START_LEAD_MS = 60 * 60 * 1000;

function routeDayKey(routeId, serviceDate) {
  return `${routeId}|${serviceDate}`;
}

function routeDayCoverage(day, routeId, directOnly) {
  // Terminal claims require feed-generated counts. Legacy/malformed coverage is
  // unknown, and zero destination candidates can never prove an ended service.
  const route = day.destinationStatus?.routes?.[routeId];
  if (!route || !Number.isSafeInteger(route.scheduledTripCount)
      || !Number.isSafeInteger(route.originTripCount)
      || !Number.isSafeInteger(route.candidateCount)
      || !Number.isSafeInteger(route.dataInsufficientCount)) {
    return { state: 'unknown', candidates: 0 };
  }
  const candidates = directOnly
    ? (Number.isSafeInteger(route.directCandidateCount) ? route.directCandidateCount : route.candidateCount)
    : route.candidateCount;
  const transferIssues = Number.isSafeInteger(route.transferDataInsufficientCount)
    ? route.transferDataInsufficientCount : null;
  if (route.scheduledTripCount === 0) return { state: 'no_service', candidates };
  if (route.dataInsufficientCount > 0
      || (!directOnly && (transferIssues === null || transferIssues > 0))) {
    return { state: 'data_insufficient', candidates };
  }
  if (candidates === 0) return { state: 'no_candidates', candidates };
  return { state: 'scheduled', candidates };
}

function summarizeRouteStates(routeDayStates, todayTokyo) {
  // routeStates exposes one current state per boarding route plus each
  // serviceDate's state; serviceState is 'ended' only when both routes ended.
  const routeStates = {};
  for (const routeId of ROUTE_IDS) {
    const days = [...routeDayStates.values()]
      .filter(day => day.routeId === routeId)
      .sort((a, b) => a.serviceDate.localeCompare(b.serviceDate));
    const today = days.find(day => day.serviceDate === todayTokyo);
    const previous = days.find(day => day.serviceDate === addCalendarDays(todayTokyo, -1));
    const upcoming = days.find(day => day.serviceDate === addCalendarDays(todayTokyo, 1));
    let state = 'unknown';

    if (upcoming?.state === 'data_insufficient' || upcoming?.state === 'unknown') {
      state = 'unknown';
    } else if (today?.state === 'data_insufficient' || today?.state === 'unknown') {
      state = today.state;
    } else if (today?.state === 'running') {
      state = 'running';
    } else if (today?.state === 'ended') {
      state = 'ended';
    } else if (today?.state === 'not_started') {
      // The next service date's future departures do not mean trains are
      // currently running. Keep the prior day's ended state until this route's
      // own 60-minute gate changes today's state to running.
      if (previous?.state === 'running') state = 'running';
      else if (previous?.state === 'ended') state = 'ended';
      else if (previous?.state === 'data_insufficient' || previous?.state === 'unknown') state = 'unknown';
      else state = 'not_started';
    } else if (today?.state === 'no_service' || today?.state === 'no_candidates') {
      // A previous 24:xx/25:xx service can still be active after midnight.
      // Preserve that only while its own final departure is still ahead.
      state = previous?.state === 'running' ? 'running' : today.state;
    } else if (upcoming?.state === 'not_started') {
      state = 'not_started';
    }

    routeStates[routeId] = {
      state,
      serviceDates: days.map(day => ({
        serviceDate: day.serviceDate,
        state: day.state,
        firstDepartureAtMs: day.firstDepartureAtMs,
        lastDepartureAtMs: day.lastDepartureAtMs,
        terminalCandidateId: day.terminalCandidateId,
      })),
    };
  }
  const states = Object.values(routeStates).map(value => value.state);
  let serviceState = 'unknown';
  if (states.every(state => state === 'ended')) serviceState = 'ended';
  else if (states.includes('data_insufficient') || states.includes('unknown')) serviceState = 'unknown';
  else if (states.every(state => state === 'no_service')) serviceState = 'no_service';
  else if (states.every(state => state === 'no_candidates')) serviceState = 'no_candidates';
  else if (states.includes('running')) serviceState = states.includes('ended') ? 'partial' : 'running';
  else if (states.includes('ended')) serviceState = 'partial';
  else if (states.includes('not_started')) serviceState = 'not_started';
  else if (states.includes('no_service') || states.includes('no_candidates')) serviceState = 'partial';
  return { routeStates, serviceState };
}

/**
 * Make presentable candidates from one or more service days.
 * Options: nowMs, horizonMs (default 24h), directOnly, mode ('line'|'departure').
 */
export function buildBoard(payload, {
  nowMs = Date.now(),
  horizonMs = DEFAULT_HORIZON_MS,
  directOnly = false,
  mode = 'departure',
  expectedProfile = LOCAL_DATA_SCOPE,
  onTiming = null,
} = {}) {
  const prepared = PREPARED_PAYLOADS.get(payload);
  if (!SUPPORTED_DATA_SCOPES.has(expectedProfile)) fail('expectedProfile', 'unsupported data profile');
  if (prepared && prepared.expectedProfile !== expectedProfile) {
    fail('payload.dataScope', `${expectedProfile} expected for prepared payload`);
  }
  if (!prepared) validateTimetablePayload(payload, expectedProfile);
  if (!Number.isFinite(nowMs)) throw new TypeError('nowMs must be finite');
  if (!Number.isFinite(horizonMs) || horizonMs <= 0) throw new TypeError('horizonMs must be positive');
  if (typeof directOnly !== 'boolean') throw new TypeError('directOnly must be boolean');
  if (!['line', 'departure'].includes(mode)) throw new TypeError("mode must be 'line' or 'departure'");
  if (onTiming !== null && typeof onTiming !== 'function') throw new TypeError('onTiming must be a function or null');

  const endMs = nowMs + horizonMs;
  const todayTokyo = tokyoCalendarDate(nowMs);
  const allowedServiceDates = new Set([
    addCalendarDays(todayTokyo, -1),
    todayTokyo,
    addCalendarDays(todayTokyo, 1),
  ]);
  const excluded = [];
  const deduplicated = new Map();
  const routeDayCandidates = new Map();
  let duplicateCount = 0;

  const sourceEntries = prepared?.entries ?? payload.serviceDays.flatMap(day =>
    day.departures.map(departure => ({ day, departure, primary: null, direct: null })));
  const sourcePayload = prepared?.payload ?? payload;
  const startsAtMs = Date.parse(sourcePayload.applicationPeriod.startsAt);
  const endsAtMs = Date.parse(sourcePayload.applicationPeriod.endsAt);
  const generatedAtMs = Date.parse(sourcePayload.generatedAt);
  let validity = generatedAtMs > nowMs ? 'invalid'
    : nowMs < startsAtMs ? 'not_started'
      : nowMs >= endsAtMs ? 'expired' : 'valid';
  const requiredServiceDates = [
    addCalendarDays(todayTokyo, -1), todayTokyo, addCalendarDays(todayTokyo, 1),
  ].filter(serviceDate => serviceDate >= sourcePayload.feed.validFrom
    && serviceDate <= sourcePayload.feed.validThrough);
  const availableServiceDates = new Set(sourcePayload.serviceDays.map(day => day.serviceDate));
  const missingServiceDates = requiredServiceDates.filter(serviceDate => !availableServiceDates.has(serviceDate));
  if (validity === 'valid' && missingServiceDates.length) validity = 'missing_service_days';
  const destinationStates = sourcePayload.serviceDays
    .filter(day => requiredServiceDates.includes(day.serviceDate) && day.destinationStatus)
    .map(day => ({
      serviceDate: day.serviceDate,
      destinationStationId: day.destinationStationId,
      ...day.destinationStatus,
    }));
  const blockedDestinationState = destinationStates.find(state =>
    ['data_insufficient', 'unsupported', 'invalid'].includes(state.status));
  if (validity === 'valid' && blockedDestinationState) {
    validity = blockedDestinationState.status === 'data_insufficient'
      ? 'destination_data_insufficient'
      : blockedDestinationState.status === 'unsupported' ? 'destination_unsupported' : 'destination_invalid';
  }
  const presentation = validityPresentation(validity, startsAtMs, endsAtMs);
  if (validity !== 'valid') {
    return {
      mode, nowMs, windowEndMs: nowMs + horizonMs, items: [], groups: [], bestId: null, excluded: [],
      serviceState: 'unavailable',
      routeStates: Object.fromEntries(ROUTE_IDS.map(routeId => [routeId, { state: 'unavailable', serviceDates: [] }])),
      destinationStationId: sourcePayload.serviceDays[0]?.destinationStationId ?? null, destinationStates,
      validity, ...presentation,
      diagnostics: {
        feedVersion: sourcePayload.feed.version, feedValidFrom: sourcePayload.feed.validFrom,
        feedValidThrough: sourcePayload.feed.validThrough, generatedAt: sourcePayload.generatedAt,
        applicationStartsAt: sourcePayload.applicationPeriod.startsAt,
        applicationEndsAt: sourcePayload.applicationPeriod.endsAt,
        requiredServiceDates,
        missingServiceDates,
        destinationStates,
        gtfsUpdatedAt: sourcePayload.feed.sourceUpdatedAt, odptUpdatedAt: sourcePayload.odpt.sourceUpdatedAt,
        webAppBuiltAt: sourcePayload.webApp.builtAt,
        dataScope: sourcePayload.dataScope, connectionPolicy: { ...sourcePayload.connectionPolicy },
      },
    };
  }
  const candidateStarted = onTiming ? performance.now() : 0;
  for (const entry of sourceEntries) {
    const { day, departure } = entry;
    const inFeed = day.serviceDate >= sourcePayload.feed.validFrom && day.serviceDate <= sourcePayload.feed.validThrough;
      if (!inFeed) {
        excluded.push({ id: departure.id, reason: 'outside_feed_validity' });
        continue;
      }
      if (!allowedServiceDates.has(day.serviceDate)) {
        excluded.push({ id: departure.id, reason: 'outside_service_date_window' });
        continue;
      }
      const journey = directOnly ? departure.directAlternative : departure.primary;
      if (journey === null) {
        excluded.push({ id: departure.id, reason: directOnly ? 'direct_unavailable' : 'no_valid_arrival',
          dataQuality: [...departure.dataQuality] });
        continue;
      }
      if (journey.arrivalServiceSeconds === null) {
        excluded.push({ id: departure.id, reason: 'arrival_time_missing', dataQuality: [...departure.dataQuality] });
        continue;
      }
      if (journey.departureServiceSeconds !== departure.departureServiceSeconds) {
        fail(`departure ${departure.id}`, 'journey departure does not match origin departure');
      }
      const card = prepared
        ? (directOnly ? entry.direct : entry.primary)
        : makeCard(day, departure, journey);
      const identity = `${card.routeId}|${card.originTripId}|${card.departureAtMs}`;
      const previous = deduplicated.get(identity);
      if (previous) {
        duplicateCount += 1;
        if (compareIdentity(card, previous) < 0) deduplicated.set(identity, card);
      } else {
        deduplicated.set(identity, card);
      }
  }

  const routeDayMeta = new Map();
  for (const serviceDate of requiredServiceDates.filter(value => allowedServiceDates.has(value))) {
    const day = sourcePayload.serviceDays.find(item => item.serviceDate === serviceDate);
    for (const routeId of ROUTE_IDS) {
      const coverage = routeDayCoverage(day, routeId, directOnly);
      routeDayMeta.set(routeDayKey(routeId, serviceDate), {
        routeId, serviceDate, nowMs, ...coverage,
      });
      routeDayCandidates.set(routeDayKey(routeId, serviceDate), []);
    }
  }
  for (const card of deduplicated.values()) {
    const key = routeDayKey(card.routeId, card.serviceDate);
    routeDayCandidates.get(key)?.push(card);
  }
  for (const [key, meta] of routeDayMeta) {
    const cards = routeDayCandidates.get(key) ?? [];
    cards.sort(compareDeparture);
    const coverage = meta.state;
    if (cards.length > 0) meta.firstDepartureAtMs = cards[0].departureAtMs;
    if (['scheduled', 'no_service', 'no_candidates'].includes(coverage)
        && cards.length !== meta.candidates) {
      meta.state = 'unknown';
    } else if (coverage === 'scheduled' && cards.length > 0) {
      const last = cards[cards.length - 1];
      meta.lastDepartureAtMs = last.departureAtMs;
      meta.terminalCandidateId = last.id;
      meta.state = nowMs < meta.firstDepartureAtMs - SERVICE_START_LEAD_MS
        ? 'not_started'
        : nowMs < meta.lastDepartureAtMs ? 'running' : 'ended';
    }
  }
  const { routeStates, serviceState } = summarizeRouteStates(routeDayMeta, todayTokyo);

  const candidates = [];
  for (const card of deduplicated.values()) {
    const meta = routeDayMeta.get(routeDayKey(card.routeId, card.serviceDate));
    const showStartWindow = meta?.firstDepartureAtMs !== undefined
      && nowMs >= meta.firstDepartureAtMs - SERVICE_START_LEAD_MS;
    if (!showStartWindow) {
      excluded.push({ id: card.sourceId, reason: 'before_service_start_window' });
      continue;
    }
    if (card.departureAtMs <= nowMs) {
      excluded.push({ id: card.sourceId, reason: 'already_departed' });
      continue;
    }
    if (card.departureAtMs > endMs) {
      excluded.push({ id: card.sourceId, reason: 'outside_display_window' });
      continue;
    }
    candidates.push({
      ...card,
      isLastDeparture: meta?.state !== 'unknown' && meta?.terminalCandidateId === card.id,
      terminalBasis: directOnly ? 'direct_only' : 'all_reachable',
    });
  }

  const candidateMs = onTiming ? performance.now() - candidateStarted : null;
  const sortStarted = onTiming ? performance.now() : 0;
  candidates.sort(compareDeparture);
  const earliest = candidates.reduce((best, card) => !best
    || card.arrivalAtMs < best.arrivalAtMs
    || (card.arrivalAtMs === best.arrivalAtMs && compareDeparture(card, best) < 0)
    ? card : best, null);
  const sortMs = onTiming ? performance.now() - sortStarted : null;
  const items = candidates.map(card => ({ ...card, isBest: earliest?.id === card.id }));
  let groups;
  if (mode === 'line') {
    groups = ['6', '9'].map(routeId => ({
      routeId,
      line: ROUTE_PRESENTATION[routeId].line,
      items: items.filter(item => item.routeId === routeId),
    })).filter(group => group.items.length > 0);
  } else {
    groups = [{ line: null, items }];
  }
  if (onTiming) onTiming({ candidateMs, sortMs });

  return {
    mode,
    nowMs,
    windowEndMs: endMs,
    items,
    groups,
    bestId: earliest?.id ?? null,
    serviceState,
    routeStates,
    destinationStationId: sourcePayload.serviceDays[0]?.destinationStationId ?? null,
    destinationStates,
    validity,
    ...presentation,
    excluded,
    diagnostics: {
      duplicateCount,
      excludedCount: excluded.length,
      feedVersion: sourcePayload.feed.version,
      feedValidFrom: sourcePayload.feed.validFrom,
      feedValidThrough: sourcePayload.feed.validThrough,
      generatedAt: sourcePayload.generatedAt,
      applicationStartsAt: sourcePayload.applicationPeriod.startsAt,
      applicationEndsAt: sourcePayload.applicationPeriod.endsAt,
      requiredServiceDates,
      missingServiceDates,
      gtfsUpdatedAt: sourcePayload.feed.sourceUpdatedAt,
      odptUpdatedAt: sourcePayload.odpt.sourceUpdatedAt,
      webAppBuiltAt: sourcePayload.webApp.builtAt,
      dataScope: sourcePayload.dataScope,
      connectionPolicy: { ...sourcePayload.connectionPolicy },
    },
  };
}
