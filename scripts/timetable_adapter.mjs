/** Convert the local-preview timetable payload into UI-facing train cards. */

export const TOKYO_TIME_ZONE = 'Asia/Tokyo';
export const DEFAULT_HORIZON_MS = 24 * 60 * 60 * 1000;

const ROUTE_PRESENTATION = Object.freeze({
  '6': Object.freeze({ line: '有楽町線', color: '#c1a026', order: 0 }),
  '9': Object.freeze({ line: '副都心線', color: '#9C5E31', order: 1 }),
});

const TRAIN_TYPE_LABELS = Object.freeze({
  Local: '各駅停車',
  CommuterExpress: '通勤急行',
});

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
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: TOKYO_TIME_ZONE,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(epochMs));
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${values.hour}:${values.minute}`;
}

function tokyoCalendarDate(epochMs) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TOKYO_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date(epochMs));
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
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
    if (!Array.isArray(transfer.outgoingDestinationIds)
        || transfer.outgoingDestinationIds.some(item => typeof item !== 'string')) {
      fail(`${path}.transfer.outgoingDestinationIds`, 'array of strings required');
    }
  }
  return journey;
}

/** Validate the versioned local payload before adapting any records. */
export function validateTimetablePayload(payload) {
  requireObject(payload, 'payload');
  if (payload.schemaVersion !== 1) fail('payload.schemaVersion', 'unsupported schema version');
  if (payload.dataScope !== 'local-preview-only') fail('payload.dataScope', 'local-preview-only required');
  if (payload.timezone !== TOKYO_TIME_ZONE) fail('payload.timezone', `must be ${TOKYO_TIME_ZONE}`);
  if (typeof payload.generatedAt !== 'string' || !Number.isFinite(Date.parse(payload.generatedAt))) {
    fail('payload.generatedAt', 'valid timestamp required');
  }

  const feed = requireObject(payload.feed, 'payload.feed');
  requireString(feed.version, 'payload.feed.version');
  requireDate(feed.validFrom, 'payload.feed.validFrom');
  requireDate(feed.validThrough, 'payload.feed.validThrough');
  if (feed.validFrom > feed.validThrough) fail('payload.feed', 'validFrom must not follow validThrough');

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
  payload.serviceDays.forEach((rawDay, dayIndex) => {
    const path = `payload.serviceDays[${dayIndex}]`;
    const day = requireObject(rawDay, path);
    requireDate(day.serviceDate, `${path}.serviceDate`);
    if (seenDays.has(day.serviceDate)) fail(`${path}.serviceDate`, 'duplicate service day');
    seenDays.add(day.serviceDate);
    requireString(day.originStationId, `${path}.originStationId`);
    requireString(day.destinationStationId, `${path}.destinationStationId`);
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
      requireString(item.destination, `${itemPath}.destination`, { nullable: true });
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
  });
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
    outgoingKind: TRAIN_TYPE_LABELS[journey.transfer.outgoingTrainType] ?? null,
    outgoingDestinationIds: [...journey.transfer.outgoingDestinationIds],
  };
  const trainType = TRAIN_TYPE_LABELS[departure.trainType] ?? null;
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
    kind: trainType ?? '種別不明',
    kindCode: departure.trainType,
    destination: destination ?? '行き先不明',
    destinationLabel: destination ?? '行き先不明',
    destinationIsKnown: destination !== null,
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

/**
 * Make presentable candidates from one or more service days.
 * Options: nowMs, horizonMs (default 24h), directOnly, mode ('line'|'departure').
 */
export function buildBoard(payload, {
  nowMs = Date.now(),
  horizonMs = DEFAULT_HORIZON_MS,
  directOnly = false,
  mode = 'departure',
} = {}) {
  validateTimetablePayload(payload);
  if (!Number.isFinite(nowMs)) throw new TypeError('nowMs must be finite');
  if (!Number.isFinite(horizonMs) || horizonMs <= 0) throw new TypeError('horizonMs must be positive');
  if (typeof directOnly !== 'boolean') throw new TypeError('directOnly must be boolean');
  if (!['line', 'departure'].includes(mode)) throw new TypeError("mode must be 'line' or 'departure'");

  const endMs = nowMs + horizonMs;
  const todayTokyo = tokyoCalendarDate(nowMs);
  const allowedServiceDates = new Set([
    addCalendarDays(todayTokyo, -1),
    todayTokyo,
    addCalendarDays(todayTokyo, 1),
  ]);
  const excluded = [];
  const deduplicated = new Map();
  let duplicateCount = 0;

  for (const day of payload.serviceDays) {
    const inFeed = day.serviceDate >= payload.feed.validFrom && day.serviceDate <= payload.feed.validThrough;
    for (const departure of day.departures) {
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
      const card = makeCard(day, departure, journey);
      if (card.departureAtMs <= nowMs) {
        excluded.push({ id: departure.id, reason: 'already_departed' });
        continue;
      }
      if (card.departureAtMs > endMs) {
        excluded.push({ id: departure.id, reason: 'outside_display_window' });
        continue;
      }

      const identity = `${card.routeId}|${card.originTripId}|${card.departureAtMs}`;
      const previous = deduplicated.get(identity);
      if (previous) {
        duplicateCount += 1;
        if (compareIdentity(card, previous) < 0) deduplicated.set(identity, card);
      } else {
        deduplicated.set(identity, card);
      }
    }
  }

  const candidates = [...deduplicated.values()].sort(compareDeparture);
  const earliest = [...candidates].sort((a, b) => a.arrivalAtMs - b.arrivalAtMs || compareDeparture(a, b))[0] ?? null;
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

  return {
    mode,
    nowMs,
    windowEndMs: endMs,
    items,
    groups,
    bestId: earliest?.id ?? null,
    excluded,
    diagnostics: {
      duplicateCount,
      excludedCount: excluded.length,
      feedVersion: payload.feed.version,
      feedValidFrom: payload.feed.validFrom,
      feedValidThrough: payload.feed.validThrough,
      generatedAt: payload.generatedAt,
      dataScope: payload.dataScope,
      connectionPolicy: { ...payload.connectionPolicy },
    },
  };
}
