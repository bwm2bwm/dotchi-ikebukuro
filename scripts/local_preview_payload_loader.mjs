import { LOCAL_DATA_SCOPE, PUBLIC_DATA_SCOPE, prepareTimetablePayload } from './timetable_adapter.mjs';

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

// Browser-safe subset of the release contract. This intentionally uses Web Crypto
// over response bytes and never imports the Node-only release_contract.mjs module.
export const RELEASE_RUNTIME_CONTRACT = 'dotchi-public-runtime-v2';
export const RELEASE_STATION_FILES = Object.freeze({ ...DESTINATION_PAYLOADS });
const RELEASE_ID_PATTERN = /^r1-[0-9a-f]{64}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;

export class ReleaseRuntimeError extends Error {
  constructor(code, message) { super(message); this.name = 'ReleaseRuntimeError'; this.code = code; }
}

export function createReleaseReloadGuard(windowRef = globalThis) {
  const key = 'dotchi-ikebukuro.release-reload-attempt.v1';
  const store = windowRef?.sessionStorage;
  let attempted = false;
  try { attempted = store?.getItem(key) === '1'; } catch { attempted = false; }
  return Object.freeze({
    get attempted() { return attempted; },
    mark() { attempted = true; try { store?.setItem(key, '1'); } catch { /* storage is optional */ } },
    clear() { attempted = false; try { store?.removeItem(key); } catch { /* storage is optional */ } },
  });
}

function releaseFail(code, message) { throw new ReleaseRuntimeError(code, message); }
function exactObjectKeys(value, expected) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join('\0') === [...expected].sort().join('\0');
}
function canonicalJcs(value) {
  if (typeof value === 'string') {
    for (let i = 0; i < value.length; i += 1) {
      const code = value.charCodeAt(i);
      if (code >= 0xd800 && code <= 0xdbff) {
        const next = value.charCodeAt(i + 1);
        if (!(next >= 0xdc00 && next <= 0xdfff)) releaseFail('invalid_descriptor', 'descriptor contains invalid Unicode');
        i += 1;
      } else if (code >= 0xdc00 && code <= 0xdfff) releaseFail('invalid_descriptor', 'descriptor contains invalid Unicode');
    }
    return JSON.stringify(value);
  }
  if (value === null || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) releaseFail('invalid_descriptor', 'non-finite descriptor number');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJcs).join(',')}]`;
  if (value && Object.getPrototypeOf(value) === Object.prototype) {
    return `{${Object.keys(value).sort().map(key => `${canonicalJcs(key)}:${canonicalJcs(value[key])}`).join(',')}}`;
  }
  releaseFail('invalid_descriptor', 'descriptor contains a non-JSON value');
}
function bytesToHex(bytes) { return [...new Uint8Array(bytes)].map(value => value.toString(16).padStart(2, '0')).join(''); }
async function digestSha256(raw, cryptoImpl) {
  if (!cryptoImpl?.subtle?.digest) releaseFail('crypto_unavailable', 'Web Crypto SHA-256 is unavailable');
  return bytesToHex(await cryptoImpl.subtle.digest('SHA-256', raw));
}
function checkReleaseManifest(manifest, cryptoImpl) {
  if (!exactObjectKeys(manifest, ['schemaVersion', 'releaseId', 'releaseDescriptor', 'runtimeContract',
    'jsonEnvelopeSchemaVersion', 'payloadSchemaVersion', 'dataScope', 'publishedAt', 'generatedAt',
    'serviceDateRange', 'feed', 'applicationPeriod', 'stations', 'retainedReleases', 'legacyCompatibilityV1'])) {
    releaseFail('manifest_schema', 'manifest fields are missing or unknown');
  }
  if (manifest.schemaVersion !== 1 || !RELEASE_ID_PATTERN.test(manifest.releaseId)) releaseFail('manifest_schema', 'manifest version or releaseId is unsupported');
  if (manifest.runtimeContract !== RELEASE_RUNTIME_CONTRACT || manifest.jsonEnvelopeSchemaVersion !== 1
      || manifest.payloadSchemaVersion !== 1 || manifest.dataScope !== PUBLIC_DATA_SCOPE) {
    releaseFail('runtime_incompatible', 'manifest compatibility contract differs from this runtime');
  }
  const validDate = value => typeof value === 'string' && /^\d{4}-\d\d-\d\d$/.test(value)
    && !Number.isNaN(Date.parse(`${value}T00:00:00Z`))
    && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
  const validTimestamp = value => typeof value === 'string'
    && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value)
    && !Number.isNaN(Date.parse(value));
  if (!validTimestamp(manifest.generatedAt) || (manifest.publishedAt !== null && !validTimestamp(manifest.publishedAt))
      || !exactObjectKeys(manifest.feed, ['version', 'validFrom', 'validThrough', 'sourceUpdatedAt'])
      || typeof manifest.feed.version !== 'string' || !manifest.feed.version
      || !validDate(manifest.feed.validFrom) || !validDate(manifest.feed.validThrough)
      || manifest.feed.validFrom > manifest.feed.validThrough
      || (manifest.feed.sourceUpdatedAt !== null && !validTimestamp(manifest.feed.sourceUpdatedAt))
      || !exactObjectKeys(manifest.applicationPeriod, ['startsAt', 'endsAt'])
      || !validTimestamp(manifest.applicationPeriod.startsAt) || !validTimestamp(manifest.applicationPeriod.endsAt)
      || Date.parse(manifest.applicationPeriod.endsAt) <= Date.parse(manifest.applicationPeriod.startsAt)
      || !Array.isArray(manifest.retainedReleases) || (manifest.legacyCompatibilityV1 !== null
        && (!manifest.legacyCompatibilityV1 || typeof manifest.legacyCompatibilityV1 !== 'object'))) {
    releaseFail('manifest_schema', 'manifest metadata is invalid');
  }
  if (!manifest.releaseDescriptor || !manifest.stations || typeof manifest.stations !== 'object'
      || Object.keys(manifest.stations).sort().join('\0') !== Object.keys(DESTINATION_PAYLOADS).sort().join('\0')) {
    releaseFail('manifest_schema', 'manifest descriptor or station set is invalid');
  }
  const d = manifest.releaseDescriptor;
  if (!exactObjectKeys(d, ['manifestSchemaVersion', 'jsonEnvelopeSchemaVersion', 'payloadSchemaVersion',
    'runtimeContract', 'publicDataScope', 'builderContractVersion', 'assets', 'stations'])
      || typeof d.builderContractVersion !== 'string' || !d.builderContractVersion
      || !Array.isArray(d.assets) || d.assets.length === 0 || !Array.isArray(d.stations)
      || d.stations.length !== Object.keys(DESTINATION_PAYLOADS).length) {
    releaseFail('manifest_schema', 'release descriptor schema is invalid');
  }
  let previousAsset = '';
  for (const asset of d.assets) {
    if (!exactObjectKeys(asset, ['path', 'sha256']) || typeof asset.path !== 'string'
        || !asset.path || asset.path.startsWith('/') || asset.path.includes('\\')
        || asset.path.split('/').some(part => !part || part === '.' || part === '..')
        || !SHA256_PATTERN.test(asset.sha256) || (previousAsset && previousAsset >= asset.path)) {
      releaseFail('manifest_schema', 'release descriptor asset list is invalid');
    }
    previousAsset = asset.path;
  }
  const sortedStationIds = Object.keys(DESTINATION_PAYLOADS).sort();
  if (d.stations.some((item, index) => !exactObjectKeys(item, ['stationId', 'payloadSha256'])
      || item.stationId !== sortedStationIds[index] || !SHA256_PATTERN.test(item.payloadSha256))) {
    releaseFail('manifest_schema', 'release descriptor station list is invalid');
  }
  if (d.runtimeContract !== manifest.runtimeContract || d.manifestSchemaVersion !== manifest.schemaVersion
      || d.jsonEnvelopeSchemaVersion !== manifest.jsonEnvelopeSchemaVersion
      || d.payloadSchemaVersion !== manifest.payloadSchemaVersion || d.publicDataScope !== manifest.dataScope) {
    releaseFail('runtime_incompatible', 'descriptor compatibility contract differs from manifest');
  }
  const actualDescriptorHash = digestSha256(new TextEncoder().encode(canonicalJcs(d)), cryptoImpl);
  return actualDescriptorHash.then(hash => {
    if (`r1-${hash}` !== manifest.releaseId) releaseFail('release_id_mismatch', 'manifest descriptor does not match releaseId');
    const urls = new Set();
    for (const [stationId, filename] of Object.entries(DESTINATION_PAYLOADS)) {
      const record = manifest.stations[stationId];
      const expectedUrl = `/releases/${manifest.releaseId}/${filename.replace(/^\.\//, '')}`;
      if (!exactObjectKeys(record, ['url', 'sha256', 'bytes']) || record.url !== expectedUrl
          || !SHA256_PATTERN.test(record.sha256) || !Number.isSafeInteger(record.bytes) || record.bytes < 1
          || urls.has(record.url)) releaseFail('manifest_station_record', `manifest record for ${stationId} is invalid`);
      urls.add(record.url);
    }
    if (!exactObjectKeys(manifest.serviceDateRange, ['from', 'through']) || !validDate(manifest.serviceDateRange.from)
        || !validDate(manifest.serviceDateRange.through)
        || manifest.serviceDateRange.from > manifest.serviceDateRange.through) releaseFail('manifest_schema', 'manifest service date range is invalid');
    if (manifest.serviceDateRange.from < manifest.feed.validFrom || manifest.serviceDateRange.through > manifest.feed.validThrough) {
      releaseFail('manifest_schema', 'manifest service dates exceed feed validity');
    }
    const retainedIds = new Set([manifest.releaseId]);
    for (const retained of manifest.retainedReleases) {
      if (!exactObjectKeys(retained, ['releaseId', 'publishedAt', 'retiredAt', 'retainUntil', 'serviceDateRange', 'stations'])
          || !RELEASE_ID_PATTERN.test(retained.releaseId) || retainedIds.has(retained.releaseId)
          || !validTimestamp(retained.publishedAt) || !validTimestamp(retained.retiredAt) || !validTimestamp(retained.retainUntil)
          || !exactObjectKeys(retained.serviceDateRange, ['from', 'through'])
          || !validDate(retained.serviceDateRange.from) || !validDate(retained.serviceDateRange.through)
          || retained.serviceDateRange.from > retained.serviceDateRange.through
          || !retained.stations || Object.keys(retained.stations).sort().join('\0') !== Object.keys(DESTINATION_PAYLOADS).sort().join('\0')) {
        releaseFail('manifest_schema', 'retained release metadata is invalid');
      }
      retainedIds.add(retained.releaseId);
      for (const [stationId, filename] of Object.entries(DESTINATION_PAYLOADS)) {
        const item = retained.stations[stationId];
        const expectedUrl = `/releases/${retained.releaseId}/${filename.replace(/^\.\//, '')}`;
        if (!exactObjectKeys(item, ['url', 'sha256', 'bytes']) || item.url !== expectedUrl
            || !SHA256_PATTERN.test(item.sha256) || !Number.isSafeInteger(item.bytes) || item.bytes < 1) {
          releaseFail('manifest_schema', `retained release station metadata for ${stationId} is invalid`);
        }
      }
    }
    if (manifest.legacyCompatibilityV1 !== null) {
      const legacy = manifest.legacyCompatibilityV1;
      if (!exactObjectKeys(legacy, ['expiresAt', 'sourceLegacyDigest', 'stations']) || !validTimestamp(legacy.expiresAt)
          || !SHA256_PATTERN.test(legacy.sourceLegacyDigest)
          || Object.keys(legacy.stations ?? {}).sort().join('\0') !== Object.keys(DESTINATION_PAYLOADS).sort().join('\0')) {
        releaseFail('manifest_schema', 'legacy compatibility metadata is invalid');
      }
      for (const [stationId, filename] of Object.entries(DESTINATION_PAYLOADS)) {
        const item = legacy.stations[stationId];
        if (!exactObjectKeys(item, ['url', 'sha256', 'bytes']) || item.url !== `/${filename.replace(/^\.\//, '')}`
            || !SHA256_PATTERN.test(item.sha256) || !Number.isSafeInteger(item.bytes) || item.bytes < 1) {
          releaseFail('manifest_schema', `legacy compatibility station metadata for ${stationId} is invalid`);
        }
      }
    }
    return manifest;
  });
}

/** Fetch and pin one immutable release manifest; station loads cannot switch generation. */
export async function createReleaseRuntimeSession({ fetchImpl = fetch, cryptoImpl = globalThis.crypto,
  manifestUrl = '/manifest.json', expectedProfile = PUBLIC_DATA_SCOPE } = {}) {
  if (expectedProfile !== PUBLIC_DATA_SCOPE) throw new TypeError('release-managed runtime requires public profile');
  if (!cryptoImpl?.subtle?.digest) releaseFail('crypto_unavailable', 'Web Crypto SHA-256 is unavailable');
  let response;
  try { response = await fetchImpl(manifestUrl, { cache: 'no-cache' }); }
  catch { releaseFail('manifest_fetch', 'manifest request failed'); }
  if (!response?.ok) releaseFail('manifest_fetch', `manifest HTTP ${response?.status ?? 'error'}`);
  let raw;
  try { raw = new Uint8Array(await response.arrayBuffer()); }
  catch { releaseFail('manifest_body', 'manifest response body is unreadable'); }
  let manifest;
  let manifestText;
  try { manifestText = new TextDecoder('utf-8', { fatal: true }).decode(raw); manifest = JSON.parse(manifestText); }
  catch { releaseFail('manifest_json', 'manifest is not valid UTF-8 JSON'); }
  if (canonicalJcs(manifest) !== manifestText) releaseFail('manifest_json', 'manifest JSON is not canonical or contains duplicate fields');
  await checkReleaseManifest(manifest, cryptoImpl);
  const inFlight = new Map();
  return Object.freeze({
    releaseId: manifest.releaseId,
    manifest,
    async loadStation(stationId) {
      if (!Object.hasOwn(DESTINATION_PAYLOADS, stationId)) releaseFail('station_id', 'unknown station ID');
      const key = `${manifest.releaseId}\0${stationId}`;
      if (inFlight.has(key)) return inFlight.get(key);
      const promise = (async () => {
        const record = manifest.stations[stationId];
        let stationResponse;
        try { stationResponse = await fetchImpl(record.url, { cache: 'default' }); }
        catch { releaseFail('json_fetch', 'station JSON request failed'); }
        if (!stationResponse?.ok) releaseFail('json_fetch', `station JSON HTTP ${stationResponse?.status ?? 'error'}`);
        let bytes;
        try { bytes = new Uint8Array(await stationResponse.arrayBuffer()); }
        catch { releaseFail('json_body', 'station JSON response body is unreadable'); }
        if (bytes.byteLength !== record.bytes) releaseFail('byte_count_mismatch', 'station JSON byte count differs from manifest');
        if (await digestSha256(bytes, cryptoImpl) !== record.sha256) releaseFail('hash_mismatch', 'station JSON SHA-256 differs from manifest');
        let envelope;
        let envelopeText;
        try { envelopeText = new TextDecoder('utf-8', { fatal: true }).decode(bytes); envelope = JSON.parse(envelopeText); }
        catch { releaseFail('envelope_json', 'station JSON is not valid UTF-8 JSON'); }
        if (canonicalJcs(envelope) !== envelopeText) releaseFail('envelope_json', 'station JSON is not canonical or contains duplicate fields');
        if (!exactObjectKeys(envelope, ['schemaVersion', 'releaseId', 'stationId', 'payloadSchemaVersion', 'dataScope', 'payload'])
            || envelope.schemaVersion !== 1 || envelope.payloadSchemaVersion !== 1 || envelope.dataScope !== PUBLIC_DATA_SCOPE) {
          releaseFail('envelope_schema', 'station envelope is incompatible');
        }
        if (envelope.releaseId !== manifest.releaseId) releaseFail('release_id_mismatch', 'station releaseId differs from pinned manifest');
        if (envelope.stationId !== stationId) releaseFail('station_id_mismatch', 'station envelope ID differs from request');
        try {
          const payload = envelope.payload;
          if (!Array.isArray(payload?.serviceDays) || payload.serviceDays.length === 0
              || payload.serviceDays.some(day => day.destinationStationId !== stationId)) {
            releaseFail('station_id_mismatch', 'inner payload station does not match request');
          }
          const dates = payload.serviceDays.map(day => day.serviceDate).sort();
          if (dates[0] !== manifest.serviceDateRange.from || dates.at(-1) !== manifest.serviceDateRange.through
              || canonicalJcs(payload.feed) !== canonicalJcs(manifest.feed)
              || canonicalJcs(payload.applicationPeriod) !== canonicalJcs(manifest.applicationPeriod)
              || payload.generatedAt !== manifest.generatedAt) releaseFail('metadata_mismatch', 'payload metadata differs from manifest');
          return prepareTimetablePayload(payload, PUBLIC_DATA_SCOPE);
        } catch (error) {
          if (error instanceof ReleaseRuntimeError) throw error;
          releaseFail('payload_invalid', 'inner public payload is invalid');
        }
      })();
      inFlight.set(key, promise);
      try { return await promise; } finally { inFlight.delete(key); }
    },
  });
}

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

export function createPreparedPayloadCache(limit = 2, { namespace = null } = {}) {
  if (!Number.isInteger(limit) || limit < 1) throw new TypeError('cache limit must be a positive integer');
  const entries = new Map();
  const cacheKey = destinationStationId => {
    const prefix = typeof namespace === 'function' ? namespace() : namespace;
    return prefix === null ? destinationStationId : `${prefix}\0${destinationStationId}`;
  };
  return Object.freeze({
    get(destinationStationId) {
      const key = cacheKey(destinationStationId);
      const value = entries.get(key);
      if (value === undefined) return undefined;
      entries.delete(key);
      entries.set(key, value);
      return value;
    },
    set(destinationStationId, prepared) {
      if (!Object.hasOwn(DESTINATION_PAYLOADS, destinationStationId) || !prepared) return false;
      const key = cacheKey(destinationStationId);
      entries.delete(key);
      entries.set(key, prepared);
      while (entries.size > limit) entries.delete(entries.keys().next().value);
      return true;
    },
    keys() { return [...entries.keys()].map(key => key.slice(key.lastIndexOf('\0') + 1)); },
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

export async function loadTimetablePayload(destinationStationId = DEFAULT_DESTINATION_ID, fetchImpl = fetch,
  { expectedProfile, cacheMode } = {}) {
  const timing = { fetchMs: null, bodyReadMs: null, jsonParseMs: null, adapterMs: null, totalMs: 0,
    payloadBytes: null, cacheHit: false };
  const startedAt = performance.now();
  const finish = result => ({ ...result, timings: { ...timing, totalMs: performance.now() - startedAt } });
  if (![LOCAL_DATA_SCOPE, PUBLIC_DATA_SCOPE].includes(expectedProfile)) {
    throw new TypeError('explicit supported expected payload profile required');
  }
  if (expectedProfile === LOCAL_DATA_SCOPE && cacheMode !== 'no-store') {
    throw new TypeError('local profile requires cacheMode no-store');
  }
  if (expectedProfile === PUBLIC_DATA_SCOPE && cacheMode !== 'default') {
    throw new TypeError('public profile requires explicit cacheMode default');
  }
  const fetchCacheMode = expectedProfile === LOCAL_DATA_SCOPE ? 'no-store' : cacheMode;
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
    response = await fetchImpl(filename, { cache: fetchCacheMode });
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
    const prepared = prepareTimetablePayload(raw, expectedProfile);
    timing.adapterMs = performance.now() - adapterStarted;
    return finish({ prepared, failure: null });
  } catch {
    timing.adapterMs = performance.now() - adapterStarted;
    return finish({ prepared: null, failure: 'payloadの形式または必須メタデータを確認できません。プレビューを再生成してください。' });
  }
}
