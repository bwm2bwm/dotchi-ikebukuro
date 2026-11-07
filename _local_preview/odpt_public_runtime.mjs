/** Browser-only Phase 1 v2 contract + public projection. No QA controls or network to ODPT. */
import { validateV2Payload, buildV2QaBoard, serviceDateAt } from './odpt_v2_qa_adapter.mjs';

export const V2_PROFILE = 'public-display-v2';
export const GENERATION_CONTRACT = 'dotchi-odpt-generations-v1';
const RUNTIME = 'dotchi-odpt-public-v2';
const FILES = Object.freeze({ Kanamecho: 'timetable-Kanamecho.json', Senkawa: 'timetable-Senkawa.json',
  KotakeMukaihara: 'timetable-KotakeMukaihara.json', Hikawadai: 'timetable.json', Heiwadai: 'timetable-Heiwadai.json',
  ChikatetsuAkatsuka: 'timetable-ChikatetsuAkatsuka.json', ChikatetsuNarimasu: 'timetable-ChikatetsuNarimasu.json',
  Wakoshi: 'timetable-Wakoshi.json' });
const SOURCES = ['Railway_all.json', 'Station_all.json', 'TrainTimetable_Yurakucho.json',
  'TrainTimetable_Fukutoshin.json', 'StationTimetable_Yurakucho.json', 'StationTimetable_Fukutoshin.json', 'TokyoMetro-Train-GTFS.zip'];
const REASONS = { explicit_pass_info: 'INFO', transfer_wait_limit_info: 'INFO', no_valid_arrival: 'UNKNOWN',
  primary_arrival_missing: 'UNKNOWN', quality_warning: 'WARNING', unknown: 'UNKNOWN' };
const MAX_BYTES = 25 * 1024 * 1024;
const SITE_ASSETS = ['index.html', 'styles.css', 'preview.css', 'odpt_public.css', 'preview_public_v2.js',
  'preview_core.mjs', 'odpt_public_runtime.mjs', 'odpt_v2_qa_adapter.mjs', 'selection.mjs', 'terminal_ui.mjs',
  'timetable_adapter.mjs', 'local_preview_payload_loader.mjs'].sort();
const preparedValues = new WeakSet();

export class V2ReleaseError extends TypeError {
  constructor(code) { super(code); this.code = code; }
}
function check(ok, code) { if (!ok) throw new V2ReleaseError(code); }
function object(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }
function exact(v, keys) {
  check(object(v) && Object.keys(v).sort().join('\0') === [...keys].sort().join('\0'), 'fields_invalid');
  return v;
}
function count(v) { check(Number.isSafeInteger(v) && v >= 0, 'count_invalid'); return v; }
function hash(v) { check(typeof v === 'string' && /^[0-9a-f]{64}$/.test(v), 'hash_invalid'); }
function timestamp(v) {
  check(typeof v === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(v)
    && Number.isFinite(Date.parse(v)), 'timestamp_invalid');
  // Reject calendar rollover accepted by Date.parse (e.g. February 30).
  validDate(v.slice(0, 10));
  return Date.parse(v);
}
function validDate(v) {
  check(typeof v === 'string' && /^\d{4}-\d\d-\d\d$/.test(v), 'date_invalid');
  const ms = Date.parse(`${v}T00:00:00Z`);
  check(Number.isFinite(ms) && new Date(ms).toISOString().slice(0, 10) === v, 'date_invalid');
  return ms;
}
function plusDay(d, n) { return new Date(validDate(d) + n * 86400000).toISOString().slice(0, 10); }
export function canonicalPublicJson(v) {
  if (v === null || typeof v === 'string' || typeof v === 'boolean') return JSON.stringify(v);
  if (typeof v === 'number') { count(v); return JSON.stringify(v); }
  if (Array.isArray(v)) return `[${v.map(canonicalPublicJson).join(',')}]`;
  check(object(v), 'json_value_invalid');
  return `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonicalPublicJson(v[k])}`).join(',')}}`;
}
function same(a, b) { return canonicalPublicJson(a) === canonicalPublicJson(b); }
function freeze(v) { if (v && typeof v === 'object') { Object.values(v).forEach(freeze); Object.freeze(v); } return v; }
async function sha(bytes, cryptoImpl) {
  check(cryptoImpl?.subtle?.digest, 'crypto_unavailable');
  return [...new Uint8Array(await cryptoImpl.subtle.digest('SHA-256', bytes))].map(v => v.toString(16).padStart(2, '0')).join('');
}
async function jsonHash(value, cryptoImpl) { return sha(new TextEncoder().encode(canonicalPublicJson(value)), cryptoImpl); }
function parse(raw) {
  const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
  const value = JSON.parse(text);
  check(canonicalPublicJson(value) === text, 'json_not_canonical');
  return value;
}

function resolution(r) {
  exact(r, ['classes', 'unmatched', 'warningCodes']);
  exact(r.classes, ['A', 'B', 'C', 'D']); Object.values(r.classes).forEach(count);
  for (const key of ['unmatched', 'warningCodes']) {
    exact(r[key], ['original', 'resolved', 'unresolved']); Object.values(r[key]).forEach(count);
    check(r[key].original === r[key].resolved + r[key].unresolved && r[key].unresolved === 0, 'quality_unresolved');
  }
  check(r.classes.C === 0 && r.classes.D === 0 && r.classes.B <= r.unmatched.resolved
    && r.unmatched.resolved <= r.classes.A + r.classes.B && r.warningCodes.resolved === r.classes.A * 2, 'quality_unresolved');
}
function addResolution(total, r) { for (const group of Object.keys(r)) for (const key of Object.keys(r[group])) total[group][key] += r[group][key]; }
function validateQuality(q, dates) {
  exact(q, ['status', 'failGateCount', 'unmatchedOriginal', 'warningOriginal', 'resolution',
    'stationDateResolution', 'exclusionAudit', 'odptMatchStatusCounts']);
  check(['PASS', 'WARNING'].includes(q.status) && q.failGateCount === 0, 'quality_failed');
  count(q.unmatchedOriginal); count(q.warningOriginal); resolution(q.resolution);
  check(q.unmatchedOriginal === q.resolution.unmatched.original && q.warningOriginal === q.resolution.warningCodes.original
    && (q.status !== 'PASS' || q.unmatchedOriginal + q.warningOriginal === 0), 'quality_counts_mismatch');
  const expected = new Set(Object.keys(FILES).flatMap(s => dates.map(d => `${s}|${d}`)));
  const total = { classes: { A: 0, B: 0, C: 0, D: 0 }, unmatched: { original: 0, resolved: 0, unresolved: 0 },
    warningCodes: { original: 0, resolved: 0, unresolved: 0 } };
  check(Array.isArray(q.stationDateResolution) && q.stationDateResolution.length === expected.size, 'quality_scope_invalid');
  for (const row of q.stationDateResolution) {
    exact(row, ['stationId', 'serviceDate', 'resolution']);
    check(expected.delete(`${row.stationId}|${row.serviceDate}`), 'quality_scope_invalid');
    resolution(row.resolution); addResolution(total, row.resolution);
  }
  check(expected.size === 0 && same(total, q.resolution), 'quality_resolution_totals');
  const audit = exact(q.exclusionAudit, ['totalGeneratedCount', 'candidateCount', 'excludedCount',
    'classificationCounts', 'reasonCounts', 'byStationDate']);
  const sums = { totalGeneratedCount: 0, candidateCount: 0, excludedCount: 0,
    classificationCounts: { INFO: 0, WARNING: 0, UNKNOWN: 0 }, reasonCounts: Object.fromEntries(Object.keys(REASONS).map(k => [k, 0])) };
  const pairs = new Set(Object.keys(FILES).flatMap(s => dates.map(d => `${s}|${d}`)));
  const stationAudit = {};
  check(Array.isArray(audit.byStationDate) && audit.byStationDate.length === pairs.size, 'audit_scope_invalid');
  for (const row of audit.byStationDate) {
    exact(row, ['stationId', 'serviceDate', 'generatedCount', 'candidateCount', 'excludedCount', 'classificationCounts', 'reasonCounts']);
    check(pairs.delete(`${row.stationId}|${row.serviceDate}`), 'audit_scope_invalid');
    [row.generatedCount, row.candidateCount, row.excludedCount].forEach(count);
    exact(row.reasonCounts, Object.keys(REASONS)); Object.values(row.reasonCounts).forEach(count);
    exact(row.classificationCounts, ['INFO', 'WARNING', 'UNKNOWN']); Object.values(row.classificationCounts).forEach(count);
    const classified = { INFO: 0, WARNING: 0, UNKNOWN: 0 };
    for (const key of Object.keys(REASONS)) {
      classified[REASONS[key]] += row.reasonCounts[key]; sums.reasonCounts[key] += row.reasonCounts[key];
    }
    check(same(classified, row.classificationCounts) && row.generatedCount === row.candidateCount + row.excludedCount
      && Object.values(classified).reduce((a, b) => a + b, 0) === row.excludedCount, 'audit_counts_mismatch');
    sums.totalGeneratedCount += row.generatedCount; sums.candidateCount += row.candidateCount; sums.excludedCount += row.excludedCount;
    for (const key of Object.keys(classified)) sums.classificationCounts[key] += classified[key];
    (stationAudit[row.stationId] ??= {})[row.serviceDate] = row;
  }
  check(pairs.size === 0 && Object.entries(sums).every(([key, v]) => same(v, audit[key])), 'audit_totals_mismatch');
  check(object(q.odptMatchStatusCounts) && Object.keys(q.odptMatchStatusCounts).every(k => ['matched', 'unique_match', 'unmatched', 'ambiguous'].includes(k)), 'match_counts_invalid');
  Object.values(q.odptMatchStatusCounts).forEach(count);
  check(Object.values(q.odptMatchStatusCounts).reduce((a, b) => a + b, 0) === audit.totalGeneratedCount
    && Object.entries(q.odptMatchStatusCounts).filter(([k]) => !['matched', 'unique_match'].includes(k))
      .reduce((a, [, n]) => a + n, 0) === q.unmatchedOriginal, 'match_counts_mismatch');
  return stationAudit;
}

export async function validateV2ReleaseManifest(m, cryptoImpl = globalThis.crypto) {
  const published = object(m) && Object.hasOwn(m, 'publication');
  exact(m, ['schemaVersion', 'artifactKind', 'releaseId', 'releaseDescriptor', 'runtimeContract',
    'payloadSchemaVersion', 'dataScope', 'serviceDates', 'metadata', 'stations', 'retainedReleases', ...(published ? ['publication'] : [])]);
  const fullSite = m.artifactKind === 'release-full-site';
  check(m.schemaVersion === 2 && m.payloadSchemaVersion === 2 && m.dataScope === V2_PROFILE
    && m.runtimeContract === RUNTIME && (fullSite || m.artifactKind === 'release-data-only')
    && Array.isArray(m.retainedReleases) && (published && fullSite || m.retainedReleases.length === 0), 'runtime_incompatible');
  const dates = m.serviceDates;
  check(Array.isArray(dates) && dates.length >= 3 && dates.length <= 366, 'service_dates_invalid');
  dates.forEach((d, i) => { validDate(d); if (i) check(d === plusDay(dates[i - 1], 1), 'service_dates_invalid'); });
  const meta = exact(m.metadata, ['candidateDigest', 'sourceFingerprint', 'sourceFiles', 'applicationPeriod',
    'approval', 'codeCommit', 'retrievedAt', 'feed', 'attribution', 'evidenceKind', 'quality', 'transferSearchPolicy']);
  hash(meta.candidateDigest); hash(meta.sourceFingerprint);
  check(Array.isArray(meta.sourceFiles) && meta.sourceFiles.length === SOURCES.length, 'source_set_invalid');
  for (const [i, row] of meta.sourceFiles.entries()) {
    exact(row, ['path', 'sizeBytes', 'sha256']); hash(row.sha256);
    check(row.path === SOURCES[i] && count(row.sizeBytes) > 0, 'source_set_invalid');
  }
  check(await jsonHash(meta.sourceFiles, cryptoImpl) === meta.sourceFingerprint, 'source_fingerprint_mismatch');
  check(typeof meta.codeCommit === 'string' && /^[0-9a-f]{40}$/.test(meta.codeCommit), 'commit_invalid');
  exact(meta.approval, ['approved', 'recordId', 'approvedAt']);
  check(meta.approval.approved === true && typeof meta.approval.recordId === 'string'
    && /^[\p{L}\p{N}_ .:/#()、。・〜（）−-]{1,200}$/u.test(meta.approval.recordId)
    && !/[?@]|\/Users\/|\/private\/|consumerkey|api_key/i.test(meta.approval.recordId), 'approval_required');
  check(timestamp(meta.retrievedAt) <= timestamp(meta.approval.approvedAt), 'approval_time_invalid');
  exact(meta.applicationPeriod, ['startsAt', 'endsAt']);
  const start = timestamp(meta.applicationPeriod.startsAt), end = timestamp(meta.applicationPeriod.endsAt);
  const endSubMillisecond = /[1-9]/.test((/\.(\d+)/.exec(meta.applicationPeriod.endsAt)?.[1] ?? '').slice(3));
  check(start < end && dates[0] <= plusDay(serviceDateAt(start), -1)
    && plusDay(serviceDateAt(end - (endSubMillisecond ? 0 : 1)), 1) <= dates.at(-1), 'publication_buffer_dates_missing');
  exact(meta.feed, ['version', 'validFrom', 'validThrough']); validDate(meta.feed.validFrom); validDate(meta.feed.validThrough);
  check(typeof meta.feed.version === 'string' && /^[\p{L}\p{N}_.-]{1,80}$/u.test(meta.feed.version)
    && meta.feed.validFrom <= dates[0] && dates.at(-1) <= meta.feed.validThrough
    && ['synthetic', 'odpt-acquired'].includes(meta.evidenceKind)
    && (meta.evidenceKind === 'synthetic') === meta.feed.version.startsWith('synthetic'), 'feed_invalid');
  exact(meta.attribution, ['provider', 'sourceUrl']);
  check(meta.attribution.provider === '東京メトロ / 公共交通オープンデータセンター'
    && meta.attribution.sourceUrl === 'https://www.odpt.org/', 'attribution_invalid');
  check(same(meta.transferSearchPolicy, { minimumWaitSeconds: 60, maximumWaitSeconds: 3600, crossServiceDateSearch: false }), 'transfer_policy_invalid');
  const d = exact(m.releaseDescriptor, ['manifestSchemaVersion', 'jsonEnvelopeSchemaVersion', 'payloadSchemaVersion',
    'publicDataScope', 'runtimeContract', 'builderContractVersion', 'metadataSha256', 'stations', ...(fullSite ? ['assets'] : [])]);
  check(d.manifestSchemaVersion === 2 && d.jsonEnvelopeSchemaVersion === 1 && d.payloadSchemaVersion === 2
    && d.publicDataScope === V2_PROFILE && d.runtimeContract === RUNTIME
    && d.builderContractVersion === (fullSite ? 'dotchi-odpt-site-assembler-v1' : 'dotchi-odpt-release-builder-v1'), 'descriptor_profile_invalid');
  if (fullSite) {
    check(Array.isArray(d.assets) && d.assets.length === SITE_ASSETS.length, 'asset_set_invalid');
    d.assets.forEach((row, i) => {
      exact(row, ['path', 'bytes', 'sha256']); hash(row.sha256);
      check(row.path === SITE_ASSETS[i] && count(row.bytes) > 0 && row.bytes <= MAX_BYTES, 'asset_record_invalid');
    });
  }
  check(await jsonHash(meta, cryptoImpl) === d.metadataSha256, 'metadata_hash_mismatch');
  check(Array.isArray(d.stations) && d.stations.length === 8, 'station_set_invalid');
  const stationIds = Object.keys(FILES).sort();
  d.stations.forEach((row, i) => { exact(row, ['stationId', 'payloadSha256']); hash(row.payloadSha256); check(row.stationId === stationIds[i], 'station_set_invalid'); });
  check(m.releaseId === `r1-${await jsonHash(d, cryptoImpl)}`, 'release_id_mismatch');
  exact(m.stations, Object.keys(FILES));
  let totalBytes = new TextEncoder().encode(canonicalPublicJson(m)).length;
  if (fullSite) totalBytes += d.assets.reduce((total, row) => total + row.bytes, 0);
  for (const [id, filename] of Object.entries(FILES)) {
    const record = exact(m.stations[id], ['url', 'sha256', 'bytes']); hash(record.sha256);
    check(record.url === `/releases/${m.releaseId}/${filename}` && count(record.bytes) > 0 && record.bytes <= MAX_BYTES, 'station_record_invalid');
    totalBytes += record.bytes;
  }
  if (published) {
    check(fullSite, 'publication_requires_full_site');
    const p = exact(m.publication, ['contract', 'publishedAt', 'assembledAt', 'operation', 'previousReleaseId',
      'previousArtifactDigest', 'prunedReleaseIds']);
    check(p.contract === GENERATION_CONTRACT && ['initial', 'update', 'rollback'].includes(p.operation), 'generation_contract_unknown');
    hash(p.previousArtifactDigest);
    const first = timestamp(p.publishedAt), assembled = timestamp(p.assembledAt);
    check(start <= first && first <= assembled && assembled < end && timestamp(meta.approval.approvedAt) <= first, 'publication_time_invalid');
    check(Array.isArray(p.prunedReleaseIds) && p.prunedReleaseIds.every(r => typeof r === 'string' && /^r1-[0-9a-f]{64}$/.test(r))
      && same(p.prunedReleaseIds, [...new Set(p.prunedReleaseIds)].sort())
      && p.prunedReleaseIds.every(r => r !== m.releaseId && r !== p.previousReleaseId), 'prune_ids_invalid');
    if (p.operation === 'initial') check(p.previousReleaseId === null && !m.retainedReleases.length && !p.prunedReleaseIds.length, 'initial_state_invalid');
    else check(typeof p.previousReleaseId === 'string' && /^r1-[0-9a-f]{64}$/.test(p.previousReleaseId)
      && p.previousReleaseId !== m.releaseId, 'previous_release_invalid');
    const ids = new Set([m.releaseId]); const ordered = [];
    for (const entry of m.retainedReleases) {
      exact(entry, ['releaseId', 'releaseDescriptor', 'metadata', 'serviceDates', 'stations', 'publishedAt', 'retiredAt', 'retainUntil']);
      check(!ids.has(entry.releaseId), 'duplicate_generation'); ids.add(entry.releaseId); ordered.push(entry.releaseId);
      const old = { schemaVersion: 2, artifactKind: 'release-full-site', runtimeContract: RUNTIME, payloadSchemaVersion: 2,
        dataScope: V2_PROFILE, retainedReleases: [], releaseId: entry.releaseId, releaseDescriptor: entry.releaseDescriptor,
        metadata: entry.metadata, serviceDates: entry.serviceDates, stations: entry.stations };
      await validateV2ReleaseManifest(old, cryptoImpl);
      const retired = timestamp(entry.retiredAt), publishedAt = timestamp(entry.publishedAt);
      const oldStart = timestamp(entry.metadata.applicationPeriod.startsAt), oldEnd = timestamp(entry.metadata.applicationPeriod.endsAt);
      check(oldStart <= publishedAt && publishedAt < oldEnd && timestamp(entry.metadata.approval.approvedAt) <= publishedAt
        && publishedAt <= retired && retired <= assembled && entry.metadata.evidenceKind === meta.evidenceKind, 'retained_time_invalid');
      const feedEnd = validDate(entry.metadata.feed.validThrough) + 86400000 - 9 * 3600000;
      const required = Math.max(retired + 7 * 86400000, Math.min(oldEnd, feedEnd) + 48 * 3600000);
      check(timestamp(entry.retainUntil) === required
        && required <= retired + Math.max(7 * 86400000, oldEnd - oldStart + 48 * 3600000), 'retention_deadline_mismatch');
      totalBytes += entry.releaseDescriptor.assets.reduce((n, r) => n + r.bytes, 0)
        + Object.values(entry.stations).reduce((n, r) => n + r.bytes, 0);
    }
    check(same(ordered, [...ordered].sort()) && (p.operation === 'initial' || ids.has(p.previousReleaseId)), 'retained_order_or_previous_invalid');
  }
  check(totalBytes <= 256 * 1024 * 1024, 'release_oversize');
  return validateQuality(meta.quality, dates);
}

async function receive(fetchImpl, url, cache) {
  const response = await fetchImpl(url, { cache, redirect: 'error', credentials: 'same-origin' });
  check(response?.ok, 'json_fetch');
  const length = response.headers?.get?.('content-length');
  if (length !== null && length !== undefined) check(/^\d+$/.test(length) && Number(length) <= MAX_BYTES, 'response_size_invalid');
  let raw;
  if (response.body?.getReader) {
    const reader = response.body.getReader(); const chunks = []; let size = 0;
    try {
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        size += value.byteLength; check(size <= MAX_BYTES, 'response_size_invalid'); chunks.push(value);
      }
    } catch (error) { await reader.cancel().catch(() => {}); throw error; }
    finally { reader.releaseLock(); }
    raw = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { raw.set(chunk, offset); offset += chunk.byteLength; }
  } else raw = new Uint8Array(await response.arrayBuffer());
  check(raw.length > 0 && raw.length <= MAX_BYTES, 'response_size_invalid');
  return raw;
}

export async function createV2ReleaseSession({ fetchImpl = fetch, cryptoImpl = globalThis.crypto } = {}) {
  const manifest = parse(await receive(fetchImpl, '/manifest.json', 'no-cache'));
  const audit = await validateV2ReleaseManifest(manifest, cryptoImpl);
  freeze(manifest); freeze(audit);
  let pinnedGeneratedAt = null;
  return Object.freeze({ releaseId: manifest.releaseId, manifest,
    async loadStation(stationId) {
      check(Object.hasOwn(FILES, stationId), 'station_invalid');
      const record = manifest.stations[stationId];
      const raw = await receive(fetchImpl, record.url, 'default');
      check(raw.length === record.bytes, 'byte_count_mismatch');
      check(await sha(raw, cryptoImpl) === record.sha256, 'hash_mismatch');
      const env = exact(parse(raw), ['schemaVersion', 'releaseId', 'stationId', 'payloadSchemaVersion', 'dataScope', 'payload']);
      check(env.schemaVersion === 1 && env.payloadSchemaVersion === 2 && env.dataScope === V2_PROFILE, 'envelope_schema');
      check(env.releaseId === manifest.releaseId, 'release_id_mismatch');
      check(env.stationId === stationId, 'station_id_mismatch');
      const payload = await validateV2Payload(env.payload, { stationId, serviceDates: manifest.serviceDates.slice(0, 3), cryptoImpl });
      check(same(payload.serviceDays.map(day => day.serviceDate), manifest.serviceDates), 'service_date_set_mismatch');
      const expected = manifest.releaseDescriptor.stations.find(row => row.stationId === stationId).payloadSha256;
      check(await jsonHash(payload, cryptoImpl) === expected, 'payload_hash_mismatch');
      check(timestamp(manifest.metadata.retrievedAt) <= timestamp(payload.generatedAt)
        && timestamp(payload.generatedAt) <= timestamp(manifest.metadata.approval.approvedAt), 'generation_approval_time_mismatch');
      for (const day of payload.serviceDays) {
        check(day.departures.length === audit[stationId][day.serviceDate].candidateCount, 'audit_candidate_mismatch');
        check(Object.values(day.routeCoverage).every(c => c.dataState === 'complete'), 'coverage_incomplete');
      }
      check(pinnedGeneratedAt === null || pinnedGeneratedAt === payload.generatedAt, 'generated_at_mismatch');
      pinnedGeneratedAt = payload.generatedAt;
      const prepared = freeze({ payload, manifest, audit: audit[stationId] });
      preparedValues.add(prepared);
      return prepared;
    },
  });
}

export function buildV2PublicBoard(prepared, { nowMs, directOnly = false, mode = 'departure' } = {}) {
  check(preparedValues.has(prepared) && Number.isFinite(nowMs), 'prepared_invalid');
  const { payload, manifest, audit } = prepared;
  const meta = manifest.metadata;
  const starts = timestamp(meta.applicationPeriod.startsAt), ends = timestamp(meta.applicationPeriod.endsAt);
  const periodText = `${meta.applicationPeriod.startsAt} 〜 ${meta.applicationPeriod.endsAt}（終了日時は含まない）`;
  const validity = nowMs < starts ? 'not_started' : nowMs >= ends ? 'expired'
    : nowMs < timestamp(meta.approval.approvedAt) ? 'unavailable' : 'valid';
  if (validity !== 'valid') return { items: [], groups: [], validity, serviceState: 'unavailable', periodText,
    statusMessage: validity === 'expired' ? '時刻表の適用期間が終了しました。更新してください。'
      : '時刻表は適用前です。適用期間を確認してください。', publication: meta };
  const stations = { [payload.stationId]: Object.fromEntries(Object.entries(audit).map(([d, row]) => [d, {
    infoCount: row.reasonCounts.explicit_pass_info,
    noValidArrivalCount: row.reasonCounts.no_valid_arrival,
    otherUnknownCount: row.reasonCounts.primary_arrival_missing + row.reasonCounts.unknown,
  }])) };
  const board = buildV2QaBoard(payload, { stations }, { nowMs, directOnly, mode });
  const unavailable = board.serviceState === 'unavailable';
  const normal = !board.candidateComparisonPartial && !board.noValidArrivalCount && !board.otherUnknownCount;
  return { ...board, validity: unavailable ? 'unavailable' : 'valid', periodText,
    statusState: unavailable || !normal ? 'warning' : 'ok',
    statusMessage: unavailable ? '必要な運行日データがありません。候補を表示できません。'
      : normal ? '時刻表に基づく案内です。実際の運行状況もご確認ください。' : board.status,
    publication: meta };
}

export const V2_PUBLIC_ADAPTER = Object.freeze({ createSession: createV2ReleaseSession, buildBoard: buildV2PublicBoard });
