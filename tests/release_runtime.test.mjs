import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import {
  buildReleaseDescriptor, calculateReleaseId, canonicalizeJcs, createManifest, encodeEnvelope, encodeManifest,
  sha256Hex, STATION_FILES,
} from '../scripts/release_contract.mjs';
import { createReleaseRuntimeSession, createPreparedPayloadCache } from '../scripts/local_preview_payload_loader.mjs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const py = script => JSON.parse(execFileSync('python3', ['-c', script], { cwd: root, encoding: 'utf8',
  env: { ...process.env, PYTHONPATH: path.join(root, 'scripts') } }));
const dates = ['2026-10-26', '2026-10-27', '2026-10-28'];

function releaseFixture(changed = false) {
  const payloads = py('import json; from synthetic_public_fixture_factory import STATION_FILES, make_public_fixture; d=["2026-10-26","2026-10-27","2026-10-28"]; print(json.dumps({s:make_public_fixture(s,d) for s in STATION_FILES},ensure_ascii=False,separators=(",",":")))');
  if (changed) payloads.Hikawadai.webApp.builtAt = '2026-10-28T03:00:00Z';
  const assets = { 'index.html': Buffer.from('<html>'), 'styles.css': Buffer.from('body{}'), 'preview.js': Buffer.from('export {};') };
  const descriptor = buildReleaseDescriptor({ runtimeContract: 'dotchi-public-runtime-v2',
    builderContractVersion: 'dotchi-public-builder-v1', payloads, assets });
  const releaseId = calculateReleaseId(descriptor);
  const stationJsonBytes = Object.fromEntries(Object.keys(STATION_FILES).map(id => [id,
    encodeEnvelope({ releaseId, stationId: id, payload: payloads[id] })]));
  const manifest = createManifest({ releaseId, releaseDescriptor: descriptor, publishedAt: null,
    generatedAt: payloads.Hikawadai.generatedAt,
    serviceDateRange: { from: dates[0], through: dates[2] }, feed: payloads.Hikawadai.feed,
    applicationPeriod: payloads.Hikawadai.applicationPeriod, stationJsonBytes });
  return { manifest, stationJsonBytes, releaseId };
}

function response(bytes, status = 200) {
  const raw = Buffer.from(bytes);
  return { ok: status >= 200 && status < 300, status, arrayBuffer: async () => raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength) };
}

test('release runtime pins a validated manifest and verifies immutable station bytes', async () => {
  const fixture = releaseFixture();
  const calls = [];
  const fetchImpl = async url => {
    calls.push(url);
    if (url === '/manifest.json') return response(encodeManifest(fixture.manifest));
    const station = Object.keys(STATION_FILES).find(id => fixture.manifest.stations[id].url === url);
    return response(fixture.stationJsonBytes[station]);
  };
  const session = await createReleaseRuntimeSession({ fetchImpl, cryptoImpl: webcrypto });
  assert.equal(session.releaseId, fixture.releaseId);
  const prepared = await session.loadStation('Hikawadai');
  assert.equal(prepared.schemaVersion, 1);
  assert.deepEqual(calls, ['/manifest.json', fixture.manifest.stations.Hikawadai.url]);
  assert.equal(calls.filter(url => url === '/manifest.json').length, 1);
});

test('manifest descriptor and releaseId stay pinned across destination requests and each new session fetches current manifest', async () => {
  const first = releaseFixture();
  const second = releaseFixture(true);
  let active = first;
  const fetchImpl = async url => {
    if (url === '/manifest.json') return response(encodeManifest(active.manifest));
    for (const version of [first, second]) {
      const station = Object.keys(STATION_FILES).find(id => version.manifest.stations[id].url === url);
      if (station) return response(version.stationJsonBytes[station]);
    }
    return response('{}', 404);
  };
  const oldSession = await createReleaseRuntimeSession({ fetchImpl, cryptoImpl: webcrypto });
  active = second;
  const newSession = await createReleaseRuntimeSession({ fetchImpl, cryptoImpl: webcrypto });
  assert.notEqual(newSession.releaseId, oldSession.releaseId);
  assert.equal(oldSession.releaseId, first.releaseId);
  assert.equal((await oldSession.loadStation('Hikawadai')).schemaVersion, 1);
  assert.equal((await newSession.loadStation('Hikawadai')).schemaVersion, 1);
});

test('release runtime accepts retained release descriptors and rejects a descriptor ID mismatch', async () => {
  const current = releaseFixture();
  const previous = releaseFixture(true);
  current.manifest.retainedReleases = [{ releaseId: previous.releaseId,
    releaseDescriptor: previous.manifest.releaseDescriptor,
    publishedAt: '2026-10-27T00:00:00Z', retiredAt: '2026-10-28T00:00:00Z',
    retainUntil: '2026-11-04T00:00:00Z', serviceDateRange: previous.manifest.serviceDateRange,
    stations: previous.manifest.stations }];
  const valid = encodeManifest(current.manifest);
  const session = await createReleaseRuntimeSession({
    fetchImpl: async url => url === '/manifest.json' ? response(valid) : response(current.stationJsonBytes.Hikawadai),
    cryptoImpl: webcrypto,
  });
  assert.equal(session.releaseId, current.releaseId);
  const malformed = structuredClone(current.manifest);
  malformed.retainedReleases[0].releaseDescriptor.builderContractVersion = 'altered';
  await assert.rejects(createReleaseRuntimeSession({
    fetchImpl: async () => response(Buffer.from(canonicalizeJcs(malformed))), cryptoImpl: webcrypto,
  }), { code: 'release_id_mismatch' });
});

test('release runtime rejects hash/length changes, unavailable Web Crypto and missing manifest', async () => {
  const fixture = releaseFixture();
  const fetchImpl = async url => url === '/manifest.json' ? response(encodeManifest(fixture.manifest))
    : response(fixture.stationJsonBytes.Hikawadai.subarray(0, -1));
  const session = await createReleaseRuntimeSession({ fetchImpl, cryptoImpl: webcrypto });
  await assert.rejects(session.loadStation('Hikawadai'), { code: 'byte_count_mismatch' });
  const wrongHashManifest = structuredClone(fixture.manifest);
  wrongHashManifest.stations.Hikawadai.sha256 = '0'.repeat(64);
  const hashSession = await createReleaseRuntimeSession({
    fetchImpl: async url => url === '/manifest.json' ? response(encodeManifest(wrongHashManifest))
      : response(fixture.stationJsonBytes.Hikawadai), cryptoImpl: webcrypto,
  });
  await assert.rejects(hashSession.loadStation('Hikawadai'), { code: 'hash_mismatch' });
  await assert.rejects(createReleaseRuntimeSession({ fetchImpl: async () => response('{}'), cryptoImpl: {} }), { code: 'crypto_unavailable' });
  await assert.rejects(createReleaseRuntimeSession({ fetchImpl: async () => response('{}', 404), cryptoImpl: webcrypto }), { code: 'manifest_fetch' });
});

test('release runtime rejects an envelope from another generation and malformed inner payload', async () => {
  const fixture = releaseFixture();
  const envelope = JSON.parse(fixture.stationJsonBytes.Hikawadai.toString());
  const otherGeneration = structuredClone(envelope);
  otherGeneration.releaseId = `r1-${'b'.repeat(64)}`;
  const badInner = structuredClone(envelope);
  badInner.payload.schemaVersion = 2;
  for (const [modified, code] of [[otherGeneration, 'release_id_mismatch'], [badInner, 'payload_invalid']]) {
    const raw = canonicalizeJcs(modified);
    const manifest = structuredClone(fixture.manifest);
    manifest.stations.Hikawadai = { ...manifest.stations.Hikawadai, bytes: raw.length, sha256: sha256Hex(raw) };
    const session = await createReleaseRuntimeSession({
      fetchImpl: async url => url === '/manifest.json' ? response(encodeManifest(manifest)) : response(raw),
      cryptoImpl: webcrypto,
    });
    await assert.rejects(session.loadStation('Hikawadai'), { code });
  }
});

test('release runtime refuses an off-release station URL in the pinned manifest', async () => {
  const fixture = releaseFixture();
  const manifest = structuredClone(fixture.manifest);
  manifest.stations.Hikawadai.url = 'https://example.invalid/timetable.json';
  const rawManifest = canonicalizeJcs(manifest);
  await assert.rejects(createReleaseRuntimeSession({
    fetchImpl: async () => response(rawManifest), cryptoImpl: webcrypto,
  }), { code: 'manifest_station_record' });
});

test('release runtime rejects station identity and payload metadata mismatch after byte verification', async () => {
  const fixture = releaseFixture();
  const wrong = Buffer.from(JSON.stringify({ ...JSON.parse(fixture.stationJsonBytes.Hikawadai), stationId: 'Senkawa' }));
  const manifest = structuredClone(fixture.manifest);
  manifest.stations.Hikawadai = { ...manifest.stations.Hikawadai, bytes: wrong.length, sha256: sha256Hex(wrong) };
  const fetchImpl = async url => url === '/manifest.json' ? response(encodeManifest(manifest)) : response(wrong);
  const session = await createReleaseRuntimeSession({ fetchImpl, cryptoImpl: webcrypto });
  await assert.rejects(session.loadStation('Hikawadai'), { code: 'station_id_mismatch' });
});

test('release prepared cache is two-station LRU scoped by releaseId', () => {
  const cache = createPreparedPayloadCache(2, { namespace: () => 'r1-a' });
  const a = {}, b = {}, c = {};
  cache.set('Hikawadai', a); cache.set('Senkawa', b);
  assert.equal(cache.get('Hikawadai'), a);
  cache.set('Kanamecho', c);
  assert.deepEqual(cache.keys(), ['Hikawadai', 'Kanamecho']);
  assert.equal(cache.get('Senkawa'), undefined);
});
