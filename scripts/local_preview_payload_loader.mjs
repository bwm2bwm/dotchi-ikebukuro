import { prepareTimetablePayload } from './timetable_adapter.mjs';

export const DEFAULT_DESTINATION_ID = 'Hikawadai';
export const DESTINATION_STORAGE_KEY = 'dotchi-ikebukuro.destination-id.v1';
export const DEFAULT_DISPLAY_MODE = 'departure';
export const DISPLAY_MODE_STORAGE_KEY = 'dotchi-ikebukuro.display-mode.v1';
export const DESTINATION_PAYLOADS = Object.freeze({
  Kanamecho: './timetable-Kanamecho.json',
  Senkawa: './timetable-Senkawa.json',
  KotakeMukaihara: './timetable-KotakeMukaihara.json',
  Hikawadai: './timetable.json',
  Heiwadai: './timetable-Heiwadai.json',
  ChikatetsuAkatsuka: './timetable-ChikatetsuAkatsuka.json',
  ChikatetsuNarimasu: './timetable-ChikatetsuNarimasu.json',
  Wakoshi: './timetable-Wakoshi.json',
});

export function readSavedDestinationId(getStorage = () => globalThis.localStorage) {
  try {
    const id = getStorage()?.getItem(DESTINATION_STORAGE_KEY);
    return Object.hasOwn(DESTINATION_PAYLOADS, id) ? id : DEFAULT_DESTINATION_ID;
  } catch {
    return DEFAULT_DESTINATION_ID;
  }
}

export function saveDestinationId(id, getStorage = () => globalThis.localStorage) {
  if (!Object.hasOwn(DESTINATION_PAYLOADS, id)) return false;
  try {
    const storage = getStorage();
    if (!storage) return false;
    storage.setItem(DESTINATION_STORAGE_KEY, id);
    return true;
  } catch {
    return false;
  }
}

export function readSavedDisplayMode(getStorage = () => globalThis.localStorage) {
  try {
    const mode = getStorage()?.getItem(DISPLAY_MODE_STORAGE_KEY);
    return mode === 'line' || mode === 'departure' ? mode : DEFAULT_DISPLAY_MODE;
  } catch {
    return DEFAULT_DISPLAY_MODE;
  }
}

export function saveDisplayMode(mode, getStorage = () => globalThis.localStorage) {
  if (mode !== 'line' && mode !== 'departure') return false;
  try {
    const storage = getStorage();
    if (!storage) return false;
    storage.setItem(DISPLAY_MODE_STORAGE_KEY, mode);
    return true;
  } catch {
    return false;
  }
}

export function createPreparedPayloadCache(limit = 2) {
  if (!Number.isInteger(limit) || limit < 1) throw new TypeError('cache limit must be a positive integer');
  const entries = new Map();
  return Object.freeze({
    get(destinationStationId) {
      const value = entries.get(destinationStationId);
      if (value === undefined) return undefined;
      entries.delete(destinationStationId);
      entries.set(destinationStationId, value);
      return value;
    },
    set(destinationStationId, prepared) {
      if (!Object.hasOwn(DESTINATION_PAYLOADS, destinationStationId) || !prepared) return false;
      entries.delete(destinationStationId);
      entries.set(destinationStationId, prepared);
      while (entries.size > limit) entries.delete(entries.keys().next().value);
      return true;
    },
    keys() { return [...entries.keys()]; },
  });
}

export function createLatestDestinationLoader(loadPayload) {
  if (typeof loadPayload !== 'function') throw new TypeError('loadPayload must be a function');
  let latestRequest = 0;
  return async destinationStationId => {
    const requestId = ++latestRequest;
    const result = await loadPayload(destinationStationId);
    return { ...result, destinationStationId, stale: requestId !== latestRequest };
  };
}

export async function loadTimetablePayload(destinationStationId = DEFAULT_DESTINATION_ID, fetchImpl = fetch) {
  const timing = { fetchMs: null, bodyReadMs: null, jsonParseMs: null, adapterMs: null, totalMs: 0,
    payloadBytes: null, cacheHit: false };
  const startedAt = performance.now();
  const finish = result => ({ ...result, timings: { ...timing, totalMs: performance.now() - startedAt } });
  const filename = Object.hasOwn(DESTINATION_PAYLOADS, destinationStationId)
    ? DESTINATION_PAYLOADS[destinationStationId]
    : null;
  if (!filename) {
    return finish({ prepared: null, failure: '選択した目的地IDが不正です。氷川台へ戻ってください。' });
  }

  let raw;
  let response;
  let fetchStarted = performance.now();
  try {
    response = await fetchImpl(filename, { cache: 'no-store' });
    timing.fetchMs = performance.now() - fetchStarted;
    if (!response.ok) throw new Error('payload response is not successful');
  } catch {
    timing.fetchMs = performance.now() - fetchStarted;
    return finish({ prepared: null, failure: '実ダイヤpayloadを読み込めませんでした。ローカルpreviewを再生成してください。' });
  }
  let body;
  const bodyStarted = performance.now();
  try {
    body = await response.text();
    timing.bodyReadMs = performance.now() - bodyStarted;
    const contentLengthHeader = response.headers?.get?.('content-length');
    const contentLength = contentLengthHeader === null || contentLengthHeader === undefined
      ? Number.NaN : Number(contentLengthHeader);
    timing.payloadBytes = Number.isFinite(contentLength) && contentLength >= 0 ? contentLength : null;
  } catch {
    timing.bodyReadMs = performance.now() - bodyStarted;
    return finish({ prepared: null, failure: '実ダイヤpayloadを読み込めませんでした。ローカルpreviewを再生成してください。' });
  }
  const parseStarted = performance.now();
  try {
    raw = JSON.parse(body);
    timing.jsonParseMs = performance.now() - parseStarted;
  } catch {
    timing.jsonParseMs = performance.now() - parseStarted;
    return finish({ prepared: null, failure: 'payloadのJSON形式を確認できません。ローカルpreviewを再生成してください。' });
  }
  const adapterStarted = performance.now();
  try {
    if (!Array.isArray(raw?.serviceDays)
        || raw.serviceDays.length === 0
        || raw.serviceDays.some(day => day.destinationStationId !== destinationStationId)) {
      throw new TypeError('payload destination does not match the requested destination');
    }
    const prepared = prepareTimetablePayload(raw);
    timing.adapterMs = performance.now() - adapterStarted;
    return finish({ prepared, failure: null });
  } catch {
    timing.adapterMs = performance.now() - adapterStarted;
    return finish({ prepared: null, failure: 'payloadの形式または必須メタデータを確認できません。プレビューを再生成してください。' });
  }
}
