const DATA_SCOPE = 'public-display-v2';
const QA_STATE_SCOPE = 'private-local-odpt-v2-qa-state';
const STATIONS = Object.freeze({
  Kanamecho: '要町', Senkawa: '千川', KotakeMukaihara: '小竹向原', Hikawadai: '氷川台',
  Heiwadai: '平和台', ChikatetsuAkatsuka: '地下鉄赤塚',
  ChikatetsuNarimasu: '地下鉄成増', Wakoshi: '和光市',
});
const ROUTES = Object.freeze({
  '6': Object.freeze({ name: '有楽町線', color: '#c1a026', order: 0 }),
  '9': Object.freeze({ name: '副都心線', color: '#9C5E31', order: 1 }),
});
const FILES = Object.freeze(Object.fromEntries(Object.keys(STATIONS).map(id => [id, `timetable-${id}.json`])));
const ID_PATTERN = /^p2-[0-9a-f]{32}$/;
const TIMESTAMP_PATTERN = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/;

export class OdptV2QaError extends TypeError {
  constructor(code) { super(code); this.name = 'OdptV2QaError'; this.code = code; }
}

function fail(code) { throw new OdptV2QaError(code); }
function isObject(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function exact(value, keys, code) {
  if (!isObject(value) || Object.keys(value).sort().join('\0') !== [...keys].sort().join('\0')) fail(code);
  return value;
}
function validDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d\d-\d\d$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(0, 0, 0, 0);
  return date.toISOString().slice(0, 10) === value;
}
function dateMs(value) {
  const [year, month, day] = value.split('-').map(Number);
  return Date.UTC(year, month - 1, day) - 9 * 60 * 60 * 1000;
}
function timestamp(value) {
  return typeof value === 'string' && TIMESTAMP_PATTERN.test(value) && Number.isFinite(Date.parse(value));
}
function integer(value) { return Number.isSafeInteger(value) && value >= 0; }
function canonical(value) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) fail('public_id_number_invalid');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (isObject(value)) return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  fail('public_id_value_invalid');
}
function hex(bytes) { return [...new Uint8Array(bytes)].map(byte => byte.toString(16).padStart(2, '0')).join(''); }

export function serviceSecondsToEpochMs(serviceDate, seconds) {
  if (!validDate(serviceDate) || !integer(seconds)) fail('service_time_invalid');
  return dateMs(serviceDate) + seconds * 1000;
}

export async function verifyCandidateBytes(bytes, integrity, cryptoImpl = globalThis.crypto) {
  if (!(bytes instanceof Uint8Array) || !isObject(integrity)
      || !/^[0-9a-f]{64}$/.test(integrity.sha256) || !integer(integrity.bytes)
      || integrity.bytes === 0 || bytes.byteLength !== integrity.bytes) fail('candidate_bytes_mismatch');
  if (!cryptoImpl?.subtle?.digest) fail('crypto_unavailable');
  const digest = hex(await cryptoImpl.subtle.digest('SHA-256', bytes));
  if (digest !== integrity.sha256) fail('candidate_hash_mismatch');
  return true;
}

export async function computeV2PublicId(stationId, serviceDate, journey, cryptoImpl = globalThis.crypto) {
  if (!cryptoImpl?.subtle?.digest) fail('crypto_unavailable');
  const preimage = { stationId, serviceDate, publicJourney: Object.fromEntries(
    Object.entries(journey).filter(([key]) => key !== 'id')) };
  const bytes = new TextEncoder().encode(canonical(preimage));
  return `p2-${hex(await cryptoImpl.subtle.digest('SHA-256', bytes)).slice(0, 32)}`;
}

function validateJourney(value, expectedKind, departureSeconds, routeId, code) {
  if (value === null && expectedKind !== 'primary') return;
  const journey = exact(value, ['kind', 'departureServiceSeconds', 'arrivalServiceSeconds', 'transfer'], `${code}_fields_invalid`);
  if (!['direct', 'transfer'].includes(journey.kind)
      || (expectedKind !== 'primary' && journey.kind !== expectedKind)
      || !integer(journey.departureServiceSeconds) || !integer(journey.arrivalServiceSeconds)
      || journey.arrivalServiceSeconds < journey.departureServiceSeconds
      || journey.departureServiceSeconds !== departureSeconds) fail(`${code}_invalid`);
  if (journey.kind === 'direct') {
    if (journey.transfer !== null) fail(`${code}_transfer_invalid`);
    return;
  }
  const transfer = exact(journey.transfer, ['stationId', 'waitSeconds', 'outgoingRouteId'], `${code}_transfer_fields_invalid`);
  if (transfer.stationId !== 'KotakeMukaihara' || !integer(transfer.waitSeconds)
      || transfer.waitSeconds < 60 || transfer.waitSeconds > 3600
      || !Object.hasOwn(ROUTES, transfer.outgoingRouteId) || transfer.outgoingRouteId === routeId) {
    fail(`${code}_transfer_invalid`);
  }
}

/** Validate one exact public-display-v2 station payload, including every public ID. */
export async function validateV2Payload(payload, { stationId, serviceDates, cryptoImpl = globalThis.crypto } = {}) {
  if (!Array.isArray(serviceDates) || serviceDates.length !== 3 || serviceDates.some(date => !validDate(date))
      || new Set(serviceDates).size !== serviceDates.length) fail('expected_service_dates_invalid');
  if (!Object.hasOwn(STATIONS, stationId)) fail('station_invalid');
  const top = exact(payload, ['schemaVersion', 'dataScope', 'generatedAt', 'timezone', 'applicationPeriod',
    'stationId', 'originStationId', 'serviceDays'], 'payload_fields_invalid');
  if (top.schemaVersion !== 2 || top.dataScope !== DATA_SCOPE) fail('profile_invalid');
  if (!timestamp(top.generatedAt) || top.timezone !== 'Asia/Tokyo' || top.applicationPeriod !== null
      || top.stationId !== stationId || top.originStationId !== 'Ikebukuro') fail('payload_metadata_invalid');
  if (!Array.isArray(top.serviceDays) || top.serviceDays.length !== serviceDates.length) fail('service_days_invalid');
  const seenDates = new Set();
  for (const [dayIndex, day] of top.serviceDays.entries()) {
    exact(day, ['serviceDate', 'routeCoverage', 'departures'], `service_day_${dayIndex}_fields_invalid`);
    if (!validDate(day.serviceDate) || seenDates.has(day.serviceDate)
        || day.serviceDate !== serviceDates[dayIndex]) fail('service_date_set_invalid');
    seenDates.add(day.serviceDate);
    const coverage = exact(day.routeCoverage, Object.keys(ROUTES), `route_coverage_invalid`);
    if (!Array.isArray(day.departures)) fail('departures_invalid');
    const ids = new Set();
    const signatures = new Set();
    for (const departure of day.departures) {
      exact(departure, ['id', 'routeId', 'destination', 'displayType', 'departureServiceSeconds',
        'primary', 'directAlternative', 'bestTransferAlternative'], 'departure_fields_invalid');
      if (typeof departure.id !== 'string' || !ID_PATTERN.test(departure.id) || ids.has(departure.id)
          || !Object.hasOwn(ROUTES, departure.routeId) || typeof departure.destination !== 'string'
          || !departure.destination.trim() || typeof departure.displayType !== 'string'
          || !departure.displayType.trim() || !integer(departure.departureServiceSeconds)) fail('departure_invalid');
      ids.add(departure.id);
      validateJourney(departure.primary, 'primary', departure.departureServiceSeconds, departure.routeId, 'primary');
      validateJourney(departure.directAlternative, 'direct', departure.departureServiceSeconds, departure.routeId, 'direct_alternative');
      validateJourney(departure.bestTransferAlternative, 'transfer', departure.departureServiceSeconds, departure.routeId, 'transfer_alternative');
      if ((departure.primary.kind === 'direct' && canonical(departure.primary) !== canonical(departure.directAlternative))
          || (departure.primary.kind === 'transfer' && canonical(departure.primary) !== canonical(departure.bestTransferAlternative))) {
        fail('primary_alternative_mismatch');
      }
      const expectedId = await computeV2PublicId(stationId, day.serviceDate, departure, cryptoImpl);
      if (departure.id !== expectedId) fail('public_id_mismatch');
      const signature = canonical(Object.fromEntries(Object.entries(departure).filter(([key]) => key !== 'id')));
      if (signatures.has(signature)) fail('duplicate_public_journey');
      signatures.add(signature);
    }
    for (const routeId of Object.keys(ROUTES)) {
      const state = exact(coverage[routeId], ['scheduledTripCount', 'dataState'], 'route_coverage_fields_invalid');
      if (!integer(state.scheduledTripCount) || !['complete', 'insufficient', 'unknown'].includes(state.dataState)
          || (state.scheduledTripCount === 0 && state.dataState === 'complete')) fail('route_coverage_invalid');
    }
  }
  return top;
}

/** Validate the deliberately small, local-only terminal-confidence summary. */
export function validateQaState(state, stationIds, serviceDates) {
  exact(state, ['schemaVersion', 'dataScope', 'serviceDates', 'stations', 'candidateFiles'], 'qa_state_fields_invalid');
  if (state.schemaVersion !== 1 || state.dataScope !== QA_STATE_SCOPE
      || canonical(state.serviceDates) !== canonical(serviceDates)) fail('qa_state_profile_invalid');
  exact(state.stations, stationIds, 'qa_state_station_set_invalid');
  exact(state.candidateFiles, stationIds, 'qa_state_candidate_set_invalid');
  for (const stationId of stationIds) {
    exact(state.stations[stationId], serviceDates, 'qa_state_date_set_invalid');
    for (const serviceDate of serviceDates) {
      const counts = exact(state.stations[stationId][serviceDate],
        ['infoCount', 'noValidArrivalCount', 'otherUnknownCount'], 'qa_state_counts_invalid');
      if (!integer(counts.infoCount) || !integer(counts.noValidArrivalCount)
          || !integer(counts.otherUnknownCount)) fail('qa_state_counts_invalid');
    }
    const integrity = exact(state.candidateFiles[stationId], ['sha256', 'bytes'], 'qa_state_candidate_invalid');
    if (typeof integrity.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(integrity.sha256)
        || !integer(integrity.bytes) || integrity.bytes === 0) fail('qa_state_candidate_invalid');
  }
  return state;
}

export function serviceDateAt(nowMs) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date(nowMs));
}

/** Parse a datetime-local wall value as JST; seconds are optional and default to zero. */
export function parseJstInput(value) {
  const match = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)(?::(\d\d))?$/.exec(value);
  if (!match) return null;
  const [year, month, day, hour, minute] = match.slice(1, 6).map(Number);
  const second = match[6] === undefined ? 0 : Number(match[6]);
  if (month < 1 || month > 12 || day < 1 || day > 31
      || hour > 23 || minute > 59 || second > 59) return null;
  const wall = new Date(0);
  wall.setUTCFullYear(year, month - 1, day);
  wall.setUTCHours(hour, minute, second, 0);
  if (wall.getUTCFullYear() !== year || wall.getUTCMonth() !== month - 1 || wall.getUTCDate() !== day
      || wall.getUTCHours() !== hour || wall.getUTCMinutes() !== minute || wall.getUTCSeconds() !== second) return null;
  return wall.getTime() - 9 * 60 * 60 * 1000;
}

function plusDays(value, amount) {
  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day + amount);
  date.setUTCHours(0, 0, 0, 0);
  return date.toISOString().slice(0, 10);
}

function formatTime(epochMs) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(new Date(epochMs));
}

function cardFor(day, departure, journey) {
  const route = ROUTES[departure.routeId];
  const departureAtMs = serviceSecondsToEpochMs(day.serviceDate, departure.departureServiceSeconds);
  const arrivalAtMs = serviceSecondsToEpochMs(day.serviceDate, journey.arrivalServiceSeconds);
  const transfer = journey.transfer === null ? null : {
    station: STATIONS[journey.transfer.stationId], waitSeconds: journey.transfer.waitSeconds,
    waitMinutes: journey.transfer.waitSeconds / 60,
    outgoingRoute: ROUTES[journey.transfer.outgoingRouteId].name,
  };
  return {
    id: departure.id, sourceId: departure.id, serviceDate: day.serviceDate,
    routeId: departure.routeId, line: route.name, color: route.color,
    kind: departure.displayType, destination: departure.destination,
    departureAtMs, arrivalAtMs, departureText: formatTime(departureAtMs), arrivalText: formatTime(arrivalAtMs),
    journeyKind: journey.kind, transfer, isBest: false, isLastDeparture: false,
  };
}

/** Build the UI model without applying or fabricating a publication period. */
export function buildV2QaBoard(payload, qaState, { nowMs, horizonMs = 24 * 60 * 60 * 1000,
  directOnly = false, mode = 'departure' } = {}) {
  if (!Number.isFinite(nowMs) || !Number.isFinite(horizonMs) || horizonMs <= 0
      || typeof directOnly !== 'boolean' || !['line', 'departure'].includes(mode)) fail('board_options_invalid');
  const today = serviceDateAt(nowMs);
  const required = [plusDays(today, -1), today, plusDays(today, 1)];
  const dayMap = new Map(payload.serviceDays.map(day => [day.serviceDate, day]));
  const missing = required.filter(day => !dayMap.has(day));
  const stationState = qaState.stations[payload.stationId];
  if (missing.length) {
    return { items: [], groups: [], routeStates: {}, serviceState: 'unavailable',
      status: `必要な運行日データがありません: ${missing.join(', ')}`, missingServiceDates: missing,
      applicationPeriod: null, generatedAt: payload.generatedAt };
  }

  const routeStates = {};
  const eligibleByRouteDate = new Map();
  const unknownExcludedDates = new Set(required.filter(day =>
    stationState[day].noValidArrivalCount + stationState[day].otherUnknownCount > 0));
  for (const serviceDate of required) {
    const day = dayMap.get(serviceDate);
    for (const routeId of Object.keys(ROUTES)) {
      const coverage = day.routeCoverage[routeId];
      const allRows = day.departures.filter(row => row.routeId === routeId);
      const selected = allRows.map(row => ({ row, journey: directOnly ? row.directAlternative : row.primary }))
        .filter(item => item.journey !== null)
        .map(item => cardFor(day, item.row, item.journey)).sort((a, b) => a.departureAtMs - b.departureAtMs || a.id.localeCompare(b.id));
      const key = `${serviceDate}|${routeId}`;
      eligibleByRouteDate.set(key, selected);
      const candidateEligible = coverage.dataState === 'complete' && coverage.scheduledTripCount > 0;
      let state;
      if (coverage.dataState === 'insufficient') state = 'data_insufficient';
      else if (coverage.dataState === 'unknown' || coverage.scheduledTripCount === 0) state = 'unknown';
      else if (!selected.length) state = unknownExcludedDates.has(serviceDate) ? 'unknown' : 'no_candidates';
      else if (unknownExcludedDates.has(serviceDate)
          && nowMs < selected[0].departureAtMs - 60 * 60 * 1000) state = 'start_unconfirmed';
      else if (unknownExcludedDates.has(serviceDate) && nowMs >= selected.at(-1).departureAtMs) state = 'terminal_unconfirmed';
      else if (nowMs < selected[0].departureAtMs - 60 * 60 * 1000) state = 'not_started';
      else if (nowMs >= selected.at(-1).departureAtMs) state = 'ended';
      else state = 'running';
      routeStates[key] = { serviceDate, routeId, state, candidateEligible,
        candidateCount: selected.length,
        scheduledTripCount: coverage.scheduledTripCount,
        noValidArrivalCount: stationState[serviceDate].noValidArrivalCount,
        otherUnknownCount: stationState[serviceDate].otherUnknownCount,
        terminalKnown: candidateEligible && selected.length > 0
          && !unknownExcludedDates.has(serviceDate) };
    }
  }

  const items = [];
  for (const serviceDate of required) {
    for (const routeId of Object.keys(ROUTES)) {
      const routeState = routeStates[`${serviceDate}|${routeId}`];
      if (!routeState.candidateEligible) continue;
      for (const card of eligibleByRouteDate.get(`${serviceDate}|${routeId}`) ?? []) {
        if (nowMs < card.departureAtMs - 60 * 60 * 1000 || card.departureAtMs <= nowMs
            || card.departureAtMs > nowMs + horizonMs) continue;
        card.isLastDeparture = routeState.terminalKnown
          && card.id === eligibleByRouteDate.get(`${serviceDate}|${routeId}`)?.at(-1)?.id;
        card.terminalBasis = directOnly ? 'direct_only' : 'all_reachable';
        items.push(card);
      }
    }
  }
  items.sort((a, b) => a.departureAtMs - b.departureAtMs
    || ROUTES[a.routeId].order - ROUTES[b.routeId].order || a.serviceDate.localeCompare(b.serviceDate));
  const best = items.reduce((winner, item) => !winner || item.arrivalAtMs < winner.arrivalAtMs
    || (item.arrivalAtMs === winner.arrivalAtMs && item.departureAtMs < winner.departureAtMs) ? item : winner, null);
  const visibleDates = new Set(items.map(item => item.serviceDate));
  const candidateComparisonPartial = [...visibleDates].some(serviceDate => unknownExcludedDates.has(serviceDate)
    || Object.keys(ROUTES).some(routeId => {
      const state = routeStates[`${serviceDate}|${routeId}`];
      return !state.candidateEligible;
    }));
  if (best) {
    best.isBest = true;
    best.bestLabel = candidateComparisonPartial ? '● 表示候補内の最早着' : '● 最早着';
  }
  let serviceState = 'running';
  if (items.length === 0) {
    const todayStates = Object.values(routeStates).filter(item => item.serviceDate === today).map(item => item.state);
    serviceState = todayStates.includes('unknown') || todayStates.includes('data_insufficient') ? 'unknown'
      : todayStates.includes('terminal_unconfirmed') ? 'terminal_unconfirmed'
        : todayStates.includes('start_unconfirmed') ? 'start_unconfirmed'
          : todayStates.length === 2 && todayStates.every(state => state === 'ended') ? 'ended'
        : todayStates.every(state => state === 'no_candidates') ? 'no_candidates' : 'not_started';
  }
  const groups = mode === 'line'
    ? Object.keys(ROUTES).map(routeId => ({ routeId, line: ROUTES[routeId].name,
      items: items.filter(item => item.routeId === routeId).slice(0, 3) })).filter(group => group.items.length)
    : [{ line: null, items: items.slice(0, 6) }].filter(group => group.items.length);
  const todayUnknown = unknownExcludedDates.has(today);
  const todayAudit = stationState[today];
  let status = todayUnknown ? todayAudit.noValidArrivalCount > 0
    ? `no_valid_arrival UNKNOWN ${todayAudit.noValidArrivalCount}件を監査中です。検証済み候補だけを表示対象としますが、両路線の終電は未確認です。最早着は表示候補内の比較です。`
    : `UNKNOWN除外 ${todayAudit.otherUnknownCount}件を監査中です。検証済み候補だけを表示対象としますが、両路線の終電は未確認です。最早着は表示候補内の比較です。`
    : Object.values(routeStates).some(item => item.state === 'data_insufficient')
      ? 'データ不足があります。該当路線の終電を判定しません。'
      : Object.values(routeStates).some(item => item.state === 'unknown')
        ? '運行状態を確認できない路線があります。'
        : 'v2候補をローカルQA表示中です。公開承認・適用期間はありません。';
  return { items, groups, routeStates, serviceState, bestId: best?.id ?? null, status,
    missingServiceDates: [], applicationPeriod: null, generatedAt: payload.generatedAt,
    serviceDate: today, noValidArrival: todayAudit.noValidArrivalCount > 0,
    noValidArrivalCount: todayAudit.noValidArrivalCount, otherUnknownCount: todayAudit.otherUnknownCount,
    infoCount: todayAudit.infoCount, candidateComparisonPartial };
}

export const ODPT_V2_QA_STATIONS = STATIONS;
export const ODPT_V2_QA_ROUTES = ROUTES;
export const ODPT_V2_QA_FILES = FILES;
export const ODPT_V2_QA_STATE_SCOPE = QA_STATE_SCOPE;
