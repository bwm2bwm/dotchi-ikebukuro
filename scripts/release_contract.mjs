/** Phase 4-8A release contract, independent of the current public runtime. */
import { createHash } from 'node:crypto';
import { validateTimetablePayload, PUBLIC_DATA_SCOPE } from './timetable_adapter.mjs';

export const STATION_FILES = Object.freeze({
  Kanamecho: 'timetable-Kanamecho.json', Senkawa: 'timetable-Senkawa.json',
  KotakeMukaihara: 'timetable-KotakeMukaihara.json', Hikawadai: 'timetable.json',
  Heiwadai: 'timetable-Heiwadai.json', ChikatetsuAkatsuka: 'timetable-ChikatetsuAkatsuka.json',
  ChikatetsuNarimasu: 'timetable-ChikatetsuNarimasu.json', Wakoshi: 'timetable-Wakoshi.json',
});
export const RUNTIME_CONTRACT = 'dotchi-public-runtime-v2';
export const MANIFEST_SCHEMA_VERSION = 1;
export const ENVELOPE_SCHEMA_VERSION = 1;
export const PAYLOAD_SCHEMA_VERSION = 1;
const releasePattern = /^r1-[0-9a-f]{64}$/;
const hashPattern = /^[0-9a-f]{64}$/;

export class ReleaseContractError extends TypeError {
  constructor(code, message) { super(message); this.name = 'ReleaseContractError'; this.code = code; }
}
function fail(code, message) { throw new ReleaseContractError(code, message); }

function validUnicode(value) {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(i + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
      i += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) return false;
  }
  return true;
}

function encode(value) {
  if (value === null) return 'null';
  if (value === true) return 'true';
  if (value === false) return 'false';
  if (typeof value === 'string') {
    if (!validUnicode(value)) fail('invalid_unicode', 'unpaired UTF-16 surrogate is not valid JCS input');
    return JSON.stringify(value);
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) fail('invalid_number', 'JCS does not allow non-finite numbers');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(encode).join(',')}]`;
  if (typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
    const keys = Object.keys(value);
    if (keys.some((key) => !validUnicode(key))) fail('invalid_unicode', 'invalid object key Unicode');
    keys.sort(); // ECMAScript string order is UTF-16 code-unit order required by JCS.
    return `{${keys.map((key) => `${JSON.stringify(key)}:${encode(value[key])}`).join(',')}}`;
  }
  fail('invalid_json_value', 'value is outside the JSON data model');
}

export function canonicalizeJcs(value) {
  return Buffer.from(encode(value), 'utf8');
}
export function encodeManifest(value) {
  validateManifest(value);
  return canonicalizeJcs(value);
}
export function sha256Hex(raw) {
  if (!Buffer.isBuffer(raw) && !(raw instanceof Uint8Array)) fail('invalid_bytes', 'raw bytes required');
  return createHash('sha256').update(raw).digest('hex');
}
const validRelease = (value) => typeof value === 'string' && releasePattern.test(value);
const validHash = (value) => typeof value === 'string' && hashPattern.test(value);

export function buildReleaseDescriptor({ runtimeContract, builderContractVersion, payloads, assets }) {
  if (!payloads || typeof payloads !== 'object' || Array.isArray(payloads)
      || Object.keys(payloads).length !== Object.keys(STATION_FILES).length
      || Object.keys(payloads).some((id) => !Object.hasOwn(STATION_FILES, id))) {
    fail('station_set', 'descriptor requires exactly the eight supported stations');
  }
  if (typeof runtimeContract !== 'string' || !runtimeContract
      || typeof builderContractVersion !== 'string' || !builderContractVersion) {
    fail('invalid_contract', 'runtime and builder contracts must be nonempty strings');
  }
  if (!assets || typeof assets !== 'object' || Array.isArray(assets) || Object.keys(assets).length === 0) {
    fail('invalid_asset', 'at least one asset with a nonempty path is required');
  }
  const assetExtensions = new Set();
  const descriptorAssets = Object.entries(assets).map(([path, raw]) => {
    if (!path || path.startsWith('/') || path.includes('\\') || path.split('/').some((part) => !part || part === '.' || part === '..')) {
      fail('invalid_asset', 'asset path must be a normalized relative path');
    }
    if (!Buffer.isBuffer(raw) && !(raw instanceof Uint8Array)) fail('invalid_asset', 'asset contents must be raw bytes');
    assetExtensions.add(path.includes('.') ? path.split('.').at(-1).toLowerCase() : '');
    return { path, sha256: sha256Hex(raw) };
  }).sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  if (!assetExtensions.has('html') || !assetExtensions.has('css') || (!assetExtensions.has('js') && !assetExtensions.has('mjs'))) {
    fail('invalid_asset', 'descriptor must bind HTML, CSS, and JavaScript asset bytes');
  }
  const stations = Object.keys(payloads).sort().map((stationId) => {
    const payload = payloads[stationId];
    try { validateTimetablePayload(payload, PUBLIC_DATA_SCOPE); }
    catch (error) { fail('invalid_payload', `${stationId}: ${error.message}`); }
    if (payload.serviceDays.some((day) => day.destinationStationId !== stationId)) {
      fail('station_mismatch', `payload does not belong to ${stationId}`);
    }
    return { stationId, payloadSha256: sha256Hex(canonicalizeJcs(payload)) };
  });
  return {
    manifestSchemaVersion: MANIFEST_SCHEMA_VERSION,
    jsonEnvelopeSchemaVersion: ENVELOPE_SCHEMA_VERSION,
    payloadSchemaVersion: PAYLOAD_SCHEMA_VERSION,
    runtimeContract, publicDataScope: PUBLIC_DATA_SCOPE, builderContractVersion,
    assets: descriptorAssets, stations,
  };
}

export function calculateReleaseId(descriptor) {
  const keys = ['manifestSchemaVersion', 'jsonEnvelopeSchemaVersion', 'payloadSchemaVersion',
    'runtimeContract', 'publicDataScope', 'builderContractVersion', 'assets', 'stations'].sort();
  if (!descriptor || typeof descriptor !== 'object' || Array.isArray(descriptor)
      || Object.keys(descriptor).sort().join('\0') !== keys.join('\0')) {
    fail('invalid_descriptor', 'release descriptor has missing or unknown fields');
  }
  if (descriptor.manifestSchemaVersion !== MANIFEST_SCHEMA_VERSION
      || descriptor.jsonEnvelopeSchemaVersion !== ENVELOPE_SCHEMA_VERSION
      || descriptor.payloadSchemaVersion !== PAYLOAD_SCHEMA_VERSION
      || descriptor.publicDataScope !== PUBLIC_DATA_SCOPE) {
    fail('invalid_descriptor', 'release descriptor contract versions are unsupported');
  }
  if (typeof descriptor.runtimeContract !== 'string' || !descriptor.runtimeContract
      || typeof descriptor.builderContractVersion !== 'string' || !descriptor.builderContractVersion
      || !Array.isArray(descriptor.assets) || descriptor.assets.length === 0
      || !Array.isArray(descriptor.stations) || descriptor.stations.length !== Object.keys(STATION_FILES).length) {
    fail('invalid_descriptor', 'release descriptor contents are malformed');
  }
  const paths = descriptor.assets.map((item) => {
    if (!exactKeys(item, ['path', 'sha256']) || typeof item.path !== 'string' || !item.path || !validHash(item.sha256)) {
      fail('invalid_descriptor', 'release descriptor asset record is malformed');
    }
    return item.path;
  });
  if (new Set(paths).size !== paths.length || paths.some((item, index) => index && paths[index - 1] > item)) {
    fail('invalid_descriptor', 'release descriptor asset paths must be sorted and unique');
  }
  const stationIds = descriptor.stations.map((item) => {
    if (!exactKeys(item, ['stationId', 'payloadSha256']) || !Object.hasOwn(STATION_FILES, item.stationId)
        || !validHash(item.payloadSha256)) fail('invalid_descriptor', 'release descriptor station record is malformed');
    return item.stationId;
  });
  if (stationIds.join('\0') !== Object.keys(STATION_FILES).sort().join('\0')) {
    fail('invalid_descriptor', 'release descriptor stations must be complete, unique, and sorted');
  }
  return `r1-${sha256Hex(canonicalizeJcs(descriptor))}`;
}

function validDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value;
}
function validTimestamp(value) {
  if (typeof value !== 'string') return false;
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if (!match || !validDate(match[1])) return false;
  if (Number(match[2]) > 23 || Number(match[3]) > 59 || Number(match[4]) > 59) return false;
  if (match[7] && (Number(match[8]) > 23 || Number(match[9]) > 59)) return false;
  return !Number.isNaN(Date.parse(value));
}
function exactKeys(value, names) { return value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).sort().join('\0') === [...names].sort().join('\0'); }

function validateStationRecords(records, releaseId) {
  if (!exactKeys(records, Object.keys(STATION_FILES))) fail('station_set', 'manifest must contain exactly the eight supported stations');
  const urls = new Set();
  for (const [stationId, filename] of Object.entries(STATION_FILES)) {
    const item = records[stationId];
    if (!exactKeys(item, ['url', 'sha256', 'bytes'])) fail('invalid_station_record', `${stationId} record has missing or unknown fields`);
    const expected = `/releases/${releaseId}/${filename}`;
    if (item.url !== expected || item.url.includes('..') || item.url.includes('\\') || /[?#%]/.test(item.url) || item.url.startsWith('//')) {
      fail('invalid_url', `${stationId} URL must be its exact same-origin release path`);
    }
    if (urls.has(item.url)) fail('duplicate_url', 'manifest station URLs must be unique');
    urls.add(item.url);
    if (!validHash(item.sha256)) fail('invalid_hash', `${stationId} sha256 must be 64 lowercase hex characters`);
    if (!Number.isSafeInteger(item.bytes) || item.bytes <= 0) fail('invalid_byte_count', `${stationId} bytes must be a positive integer`);
  }
}

function validateRange(range) {
  if (!exactKeys(range, ['from', 'through']) || !validDate(range.from) || !validDate(range.through) || range.from > range.through) {
    fail('invalid_date_range', 'serviceDateRange must be an ordered YYYY-MM-DD range');
  }
}

export function validateManifest(value) {
  const fields = ['schemaVersion', 'releaseId', 'releaseDescriptor', 'runtimeContract', 'jsonEnvelopeSchemaVersion',
    'payloadSchemaVersion', 'dataScope', 'publishedAt', 'generatedAt', 'serviceDateRange', 'feed',
    'applicationPeriod', 'stations', 'retainedReleases', 'legacyCompatibilityV1'];
  if (!exactKeys(value, fields)) fail('manifest_fields', 'manifest has missing or unknown fields');
  if (value.schemaVersion !== MANIFEST_SCHEMA_VERSION) fail('manifest_schema', 'unsupported manifest schemaVersion');
  if (!validRelease(value.releaseId)) fail('invalid_release_id', 'releaseId must use r1- followed by 64 lowercase hex characters');
  if (value.runtimeContract !== RUNTIME_CONTRACT || value.jsonEnvelopeSchemaVersion !== ENVELOPE_SCHEMA_VERSION
      || value.payloadSchemaVersion !== PAYLOAD_SCHEMA_VERSION || value.dataScope !== PUBLIC_DATA_SCOPE) {
    fail('compatibility_mismatch', 'manifest compatibility values do not match this contract');
  }
  if ((value.publishedAt !== null && !validTimestamp(value.publishedAt)) || !validTimestamp(value.generatedAt)) fail('invalid_timestamp', 'publishedAt, when set, and generatedAt must include timezone offsets');
  if (value.releaseDescriptor !== null && calculateReleaseId(value.releaseDescriptor) !== value.releaseId) fail('release_id_mismatch', 'manifest releaseDescriptor does not produce releaseId');
  if (value.releaseDescriptor !== null && (value.releaseDescriptor.runtimeContract !== value.runtimeContract
      || value.releaseDescriptor.manifestSchemaVersion !== value.schemaVersion
      || value.releaseDescriptor.jsonEnvelopeSchemaVersion !== value.jsonEnvelopeSchemaVersion
      || value.releaseDescriptor.payloadSchemaVersion !== value.payloadSchemaVersion
      || value.releaseDescriptor.publicDataScope !== value.dataScope)) {
    fail('compatibility_mismatch', 'manifest and release descriptor compatibility values differ');
  }
  validateRange(value.serviceDateRange);
  const feed = value.feed;
  if (!exactKeys(feed, ['version', 'validFrom', 'validThrough', 'sourceUpdatedAt'])
      || typeof feed.version !== 'string' || !feed.version || !validDate(feed.validFrom) || !validDate(feed.validThrough)
      || feed.validFrom > feed.validThrough || (feed.sourceUpdatedAt !== null && !validTimestamp(feed.sourceUpdatedAt))) {
    fail('invalid_feed', 'feed metadata is malformed');
  }
  if (value.serviceDateRange.from < feed.validFrom || value.serviceDateRange.through > feed.validThrough) fail('invalid_date_range', 'serviceDateRange must fit within feed validity');
  const period = value.applicationPeriod;
  if (!exactKeys(period, ['startsAt', 'endsAt']) || !validTimestamp(period.startsAt) || !validTimestamp(period.endsAt)
      || Date.parse(period.endsAt) <= Date.parse(period.startsAt)) fail('invalid_application_period', 'applicationPeriod is malformed');
  validateStationRecords(value.stations, value.releaseId);
  if (!Array.isArray(value.retainedReleases)) fail('invalid_retained_releases', 'retainedReleases must be an array');
  const seen = new Set([value.releaseId]);
  for (const entry of value.retainedReleases) {
    const retainedFields = ['releaseId', 'publishedAt', 'retiredAt', 'retainUntil', 'serviceDateRange', 'stations'];
    if (!exactKeys(entry, retainedFields) || !validRelease(entry.releaseId)) fail('invalid_retained_releases', 'retained release entry is malformed');
    if (seen.has(entry.releaseId)) fail('duplicate_release', 'current and retained release IDs must be unique');
    seen.add(entry.releaseId);
    if (![entry.publishedAt, entry.retiredAt, entry.retainUntil].every(validTimestamp)) fail('invalid_retained_releases', 'retained timestamps are malformed');
    validateRange(entry.serviceDateRange);
    validateStationRecords(entry.stations, entry.releaseId);
  }
  const legacy = value.legacyCompatibilityV1;
  if (legacy !== null) {
    if (!exactKeys(legacy, ['expiresAt', 'sourceLegacyDigest', 'stations']) || !validTimestamp(legacy.expiresAt)
        || !validHash(legacy.sourceLegacyDigest) || !exactKeys(legacy.stations, Object.keys(STATION_FILES))) {
      fail('invalid_legacy_compatibility', 'legacyCompatibilityV1 metadata is malformed');
    }
    const legacyUrls = new Set();
    for (const [stationId, filename] of Object.entries(STATION_FILES)) {
      const record = legacy.stations[stationId];
      if (!exactKeys(record, ['url', 'sha256', 'bytes']) || record.url !== `/${filename}`
          || !validHash(record.sha256) || !Number.isSafeInteger(record.bytes) || record.bytes <= 0
          || legacyUrls.has(record.url)) fail('invalid_legacy_compatibility', `legacy file record for ${stationId} is malformed`);
      legacyUrls.add(record.url);
    }
  }
  return value;
}

export function createManifest({ releaseId, publishedAt, generatedAt, serviceDateRange, feed,
  applicationPeriod, stationJsonBytes, retainedReleases = [], legacyCompatibilityV1 = null, releaseDescriptor = null }) {
  if (!validRelease(releaseId)) fail('invalid_release_id', 'invalid releaseId');
  if (!stationJsonBytes || typeof stationJsonBytes !== 'object' || Array.isArray(stationJsonBytes)
      || Object.keys(stationJsonBytes).length !== Object.keys(STATION_FILES).length
      || Object.keys(stationJsonBytes).some((id) => !Object.hasOwn(STATION_FILES, id))) {
    fail('station_set', 'manifest generation requires exactly eight station JSON byte strings');
  }
  const stations = {};
  for (const [stationId, filename] of Object.entries(STATION_FILES)) {
    const raw = stationJsonBytes[stationId];
    if ((!Buffer.isBuffer(raw) && !(raw instanceof Uint8Array)) || raw.byteLength === 0) fail('invalid_bytes', `${stationId} must be nonempty raw JSON bytes`);
    verifyEnvelopeBytes(raw, { expectedReleaseId: releaseId, expectedStationId: stationId,
      expectedSha256: sha256Hex(raw), expectedBytes: raw.byteLength });
    stations[stationId] = { url: `/releases/${releaseId}/${filename}`, sha256: sha256Hex(raw), bytes: raw.byteLength };
  }
  const manifest = validateManifest({ schemaVersion: MANIFEST_SCHEMA_VERSION, releaseId, releaseDescriptor, runtimeContract: RUNTIME_CONTRACT,
    jsonEnvelopeSchemaVersion: ENVELOPE_SCHEMA_VERSION, payloadSchemaVersion: PAYLOAD_SCHEMA_VERSION,
    dataScope: PUBLIC_DATA_SCOPE, publishedAt, generatedAt, serviceDateRange, feed, applicationPeriod,
    stations, retainedReleases, legacyCompatibilityV1 });
  for (const [stationId, raw] of Object.entries(stationJsonBytes)) verifyStationBytes(raw, manifest, stationId);
  return manifest;
}

export function createEnvelope({ releaseId, stationId, payload }) {
  if (!validRelease(releaseId)) fail('invalid_release_id', 'invalid releaseId');
  if (!Object.hasOwn(STATION_FILES, stationId)) fail('invalid_station', 'unsupported stationId');
  try { validateTimetablePayload(payload, PUBLIC_DATA_SCOPE); }
  catch (error) { fail('invalid_payload', error.message); }
  if (payload.serviceDays.some((day) => day.destinationStationId !== stationId)) fail('station_mismatch', 'inner payload destination does not match stationId');
  return { schemaVersion: ENVELOPE_SCHEMA_VERSION, releaseId, stationId,
    payloadSchemaVersion: PAYLOAD_SCHEMA_VERSION, dataScope: PUBLIC_DATA_SCOPE, payload };
}
export function encodeEnvelope(input) {
  return canonicalizeJcs(createEnvelope(input));
}

function parseJsonRejectDuplicates(source) {
  let index = 0;
  const ws = () => { while (/[ \t\r\n]/.test(source[index] ?? '')) index += 1; };
  const string = () => {
    const start = index;
    index += 1;
    while (index < source.length) {
      if (source[index] === '\\') { index += 2; continue; }
      if (source[index] === '"') { index += 1; return JSON.parse(source.slice(start, index)); }
      index += 1;
    }
    fail('invalid_json', 'unterminated JSON string');
  };
  const value = () => {
    ws();
    if (source[index] === '"') return string();
    if (source[index] === '{') {
      index += 1; ws(); const out = {};
      if (source[index] === '}') { index += 1; return out; }
      while (index < source.length) {
        ws(); if (source[index] !== '"') fail('invalid_json', 'object key must be a string');
        const key = string(); if (Object.hasOwn(out, key)) fail('invalid_json', 'duplicate JSON property');
        ws(); if (source[index++] !== ':') fail('invalid_json', 'expected colon');
        out[key] = value(); ws(); const separator = source[index++];
        if (separator === '}') return out;
        if (separator !== ',') fail('invalid_json', 'expected object separator');
      }
      fail('invalid_json', 'unterminated object');
    }
    if (source[index] === '[') {
      index += 1; ws(); const out = [];
      if (source[index] === ']') { index += 1; return out; }
      while (index < source.length) {
        out.push(value()); ws(); const separator = source[index++];
        if (separator === ']') return out;
        if (separator !== ',') fail('invalid_json', 'expected array separator');
      }
      fail('invalid_json', 'unterminated array');
    }
    const rest = source.slice(index);
    const primitive = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(rest);
    if (!primitive) fail('invalid_json', 'invalid JSON value');
    index += primitive[0].length;
    const parsed = JSON.parse(primitive[0]);
    if (typeof parsed === 'number' && !Number.isFinite(parsed)) fail('invalid_json', 'non-finite JSON number');
    return parsed;
  };
  const parsed = value(); ws();
  if (index !== source.length) fail('invalid_json', 'trailing bytes after JSON');
  return parsed;
}

export function verifyEnvelopeBytes(raw, { expectedReleaseId, expectedStationId, expectedSha256, expectedBytes }) {
  if (!Buffer.isBuffer(raw) && !(raw instanceof Uint8Array)) fail('invalid_bytes', 'raw response bytes required');
  if (!Number.isSafeInteger(expectedBytes) || expectedBytes <= 0) fail('invalid_byte_count', 'expected byte count must be positive');
  if (raw.byteLength !== expectedBytes) fail('byte_count_mismatch', 'response byte count differs from manifest');
  if (!validHash(expectedSha256)) fail('invalid_hash', 'expected SHA-256 is malformed');
  if (sha256Hex(raw) !== expectedSha256) fail('hash_mismatch', 'response SHA-256 differs from manifest');
  let value;
  try { value = parseJsonRejectDuplicates(new TextDecoder('utf-8', { fatal: true }).decode(raw)); }
  catch (error) { if (error instanceof ReleaseContractError) throw error; fail('invalid_json', 'response bytes are not valid UTF-8 JSON'); }
  if (!exactKeys(value, ['schemaVersion', 'releaseId', 'stationId', 'payloadSchemaVersion', 'dataScope', 'payload'])) fail('envelope_fields', 'envelope has missing or unknown fields');
  if (value.schemaVersion !== ENVELOPE_SCHEMA_VERSION || value.payloadSchemaVersion !== PAYLOAD_SCHEMA_VERSION || value.dataScope !== PUBLIC_DATA_SCOPE) fail('compatibility_mismatch', 'envelope compatibility values do not match');
  if (value.releaseId !== expectedReleaseId) fail('release_id_mismatch', 'envelope releaseId differs from pinned manifest');
  if (value.stationId !== expectedStationId || !Object.hasOwn(STATION_FILES, expectedStationId)) fail('station_mismatch', 'envelope stationId differs from requested station');
  try { validateTimetablePayload(value.payload, PUBLIC_DATA_SCOPE); }
  catch (error) { fail('invalid_payload', error.message); }
  if (value.payload.serviceDays.some((day) => day.destinationStationId !== expectedStationId)) fail('station_mismatch', 'inner payload destination does not match requested station');
  return value;
}

export function verifyStationBytes(raw, manifest, stationId) {
  validateManifest(manifest);
  if (!Object.hasOwn(STATION_FILES, stationId)) fail('invalid_station', 'unsupported stationId');
  const record = manifest.stations[stationId];
  const envelope = verifyEnvelopeBytes(raw, { expectedReleaseId: manifest.releaseId, expectedStationId: stationId,
    expectedSha256: record.sha256, expectedBytes: record.bytes });
  const payload = envelope.payload;
  const dates = payload.serviceDays.map((day) => day.serviceDate);
  if (payload.generatedAt !== manifest.generatedAt
      || payload.feed.version !== manifest.feed.version || payload.feed.validFrom !== manifest.feed.validFrom
      || payload.feed.validThrough !== manifest.feed.validThrough || payload.feed.sourceUpdatedAt !== manifest.feed.sourceUpdatedAt
      || payload.applicationPeriod.startsAt !== manifest.applicationPeriod.startsAt
      || payload.applicationPeriod.endsAt !== manifest.applicationPeriod.endsAt
      || dates.reduce((a, b) => (a < b ? a : b)) !== manifest.serviceDateRange.from
      || dates.reduce((a, b) => (a > b ? a : b)) !== manifest.serviceDateRange.through) {
    fail('manifest_payload_mismatch', 'station payload common metadata differs from manifest');
  }
  return envelope;
}
