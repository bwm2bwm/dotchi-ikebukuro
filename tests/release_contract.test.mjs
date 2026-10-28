import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  buildReleaseDescriptor, calculateReleaseId, canonicalizeJcs, createEnvelope, createManifest, encodeEnvelope, encodeManifest,
  ReleaseContractError, sha256Hex, STATION_FILES, validateManifest, verifyEnvelopeBytes, verifyStationBytes,
} from '../scripts/release_contract.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const RELEASE = `r1-${'a'.repeat(64)}`;
const DATES = ['2026-10-26', '2026-10-27', '2026-10-28'];
const py = (script, input = '') => execFileSync('python3', ['-c', script], {
  cwd: ROOT, input, encoding: 'utf8', env: { ...process.env, PYTHONPATH: path.join(ROOT, 'scripts') },
});
function makeFixturePayloads() {
  const script = 'import json; from synthetic_public_fixture_factory import STATION_FILES, make_public_fixture; d=["2026-10-26","2026-10-27","2026-10-28"]; print(json.dumps({s:make_public_fixture(s,d) for s in STATION_FILES},ensure_ascii=False,separators=(",",":")))';
  return JSON.parse(py(script));
}
function makeManifest() {
  const payloads = makeFixturePayloads();
  const stationJsonBytes = {};
  for (const stationId of Object.keys(STATION_FILES)) {
    stationJsonBytes[stationId] = Buffer.from(JSON.stringify(createEnvelope({ releaseId: RELEASE, stationId, payload: payloads[stationId] })));
  }
  return { payloads, stationJsonBytes, manifest: createManifest({
    releaseId: RELEASE, publishedAt: '2026-10-28T02:15:00Z', generatedAt: '2026-10-26T00:00:00+09:00',
    serviceDateRange: { from: DATES[0], through: DATES[2] },
    feed: { version: 'synthetic-feed-v1', validFrom: DATES[0], validThrough: DATES[2], sourceUpdatedAt: null },
    applicationPeriod: { startsAt: '2026-10-26T00:00:00+09:00', endsAt: '2026-10-29T00:00:00+09:00' },
    stationJsonBytes,
  }) };
}

test('RFC 8785 numeric, Unicode and UTF-16 key ordering vectors match Python', () => {
  const value = { numbers: [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27],
    string: '€$\u000f\nA\'B"\\', literals: [null, true, false] };
  const expected = Buffer.from('{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"string":"€$\\u000f\\nA\'B\\"\\\\"}');
  assert.deepEqual(canonicalizeJcs(value), expected);
  const scalarVsUtf16 = { '\ue000': 1, '\u{10000}': 2 };
  assert.equal(canonicalizeJcs(scalarVsUtf16).toString(), '{"𐀀":2,"":1}');
  const pythonCanonical = py('import json,sys; from release_contract import canonicalize_jcs; print(canonicalize_jcs(json.load(sys.stdin,parse_int=float)).decode(),end="")', JSON.stringify(value));
  assert.equal(canonicalizeJcs(value).toString(), pythonCanonical);
  const floatCases = [0, -0, 1e-6, 1e-7, 1e20, 1e21, 1.2345678901234567, 9007199254740991];
  for (const number of floatCases) {
    const python = py('import json,sys; from release_contract import canonicalize_jcs; print(canonicalize_jcs(json.load(sys.stdin,parse_int=float)).decode(),end="")', JSON.stringify(number));
    assert.equal(canonicalizeJcs(number).toString(), python, String(number));
  }
  assert.throws(() => canonicalizeJcs(Number.NaN), { code: 'invalid_number' });
});

test('release descriptor and ID are deterministic and content-addressed', () => {
  const payloads = makeFixturePayloads();
  const args = { runtimeContract: 'dotchi-public-runtime-v2', builderContractVersion: 'public-builder-v1', payloads,
    assets: { 'index.html': Buffer.from('<html>'), 'styles.css': Buffer.from('a{}'), 'app.js': Buffer.from('export {};') } };
  const descriptor = buildReleaseDescriptor(args);
  const reordered = buildReleaseDescriptor({ ...args, payloads: Object.fromEntries(Object.entries(payloads).reverse()),
    assets: Object.fromEntries(Object.entries(args.assets).reverse()) });
  assert.deepEqual(descriptor, reordered);
  assert.equal(calculateReleaseId(descriptor), calculateReleaseId(reordered));
  const pythonReleaseId = py('import json,sys; from release_contract import calculate_release_id; print(calculate_release_id(json.load(sys.stdin)),end="")', JSON.stringify(descriptor));
  assert.equal(calculateReleaseId(descriptor), pythonReleaseId);
  const changed = { ...payloads, Hikawadai: structuredClone(payloads.Hikawadai) };
  changed.Hikawadai.webApp.builtAt = '2026-10-28T02:16:00Z';
  assert.notEqual(calculateReleaseId(descriptor), calculateReleaseId(buildReleaseDescriptor({ ...args, payloads: changed })));
  assert.notEqual(calculateReleaseId(descriptor), calculateReleaseId(buildReleaseDescriptor({ ...args, runtimeContract: 'dotchi-public-runtime-v3' })));
  assert.notEqual(calculateReleaseId(descriptor), calculateReleaseId(buildReleaseDescriptor({ ...args, builderContractVersion: 'public-builder-v2' })));
  assert.notEqual(calculateReleaseId(descriptor), calculateReleaseId(buildReleaseDescriptor({ ...args, assets: { ...args.assets, 'app.js': Buffer.from('changed') } })));
  assert.throws(() => buildReleaseDescriptor({ ...args, payloads: { Kanamecho: payloads.Kanamecho } }), { code: 'station_set' });
});

test('manifest validates exact station set, compatibility, paths, hashes and bytes', () => {
  const { manifest } = makeManifest();
  assert.equal(validateManifest(manifest), manifest);
  const cases = [
    [m => { delete m.stations.Wakoshi; }, 'station_set'],
    [m => { m.stations.Wakoshi.url = m.stations.Kanamecho.url; }, 'invalid_url'],
    [m => { m.stations.Wakoshi.url = 'https://evil.example/x'; }, 'invalid_url'],
    [m => { m.stations.Wakoshi.url = `/releases/${RELEASE}/../x`; }, 'invalid_url'],
    [m => { m.stations.Wakoshi.sha256 = 'bad'; }, 'invalid_hash'],
    [m => { m.stations.Wakoshi.bytes = true; }, 'invalid_byte_count'],
    [m => { m.schemaVersion = 2; }, 'manifest_schema'],
    [m => { m.releaseId = 'r1-bad'; }, 'invalid_release_id'],
    [m => { m.runtimeContract = 'unrecognized'; }, 'compatibility_mismatch'],
    [m => { m.futureField = 1; }, 'manifest_fields'],
  ];
  for (const [mutate, code] of cases) {
    const changed = structuredClone(manifest); mutate(changed);
    assert.throws(() => validateManifest(changed), (error) => error instanceof ReleaseContractError && error.code === code);
  }
});

test('canonical envelope and manifest encoders are stable and common metadata is enforced', () => {
  const { payloads, stationJsonBytes, manifest } = makeManifest();
  const envelopeBytes = encodeEnvelope({ releaseId: RELEASE, stationId: 'Hikawadai', payload: payloads.Hikawadai });
  assert.deepEqual(canonicalizeJcs(JSON.parse(envelopeBytes.toString())), envelopeBytes);
  assert.deepEqual(encodeManifest(manifest), canonicalizeJcs(manifest));
  const alteredPayload = structuredClone(payloads.Hikawadai); alteredPayload.generatedAt = '2026-10-27T00:00:00+09:00';
  const changed = { ...stationJsonBytes, Hikawadai: encodeEnvelope({ releaseId: RELEASE, stationId: 'Hikawadai', payload: alteredPayload }) };
  assert.throws(() => createManifest({ ...manifest, stationJsonBytes: changed }), { code: 'manifest_payload_mismatch' });
});

test('envelope verifies raw bytes before structure and rejects generation or station mismatch', () => {
  const { manifest, stationJsonBytes } = makeManifest();
  const raw = stationJsonBytes.Hikawadai;
  assert.equal(verifyStationBytes(raw, manifest, 'Hikawadai').stationId, 'Hikawadai');
  const record = manifest.stations.Hikawadai;
  assert.throws(() => verifyStationBytes(raw.subarray(0, -1), manifest, 'Hikawadai'), { code: 'byte_count_mismatch' });
  assert.throws(() => verifyStationBytes(Buffer.from(raw), { ...manifest, stations: {
    ...manifest.stations, Hikawadai: { ...record, sha256: '0'.repeat(64) } } }, 'Hikawadai'), { code: 'hash_mismatch' });
  assert.throws(() => verifyEnvelopeBytes(raw, { expectedReleaseId: RELEASE, expectedStationId: 'Senkawa',
    expectedSha256: sha256Hex(raw), expectedBytes: raw.length }), { code: 'station_mismatch' });
  const badJson = Buffer.from('{');
  assert.throws(() => verifyStationBytes(badJson, { ...manifest, stations: {
    ...manifest.stations, Hikawadai: { ...record, bytes: 1, sha256: sha256Hex(badJson) } } }, 'Hikawadai'), { code: 'invalid_json' });
  const duplicate = Buffer.from('{"schemaVersion":1,"schemaVersion":1}');
  assert.throws(() => verifyStationBytes(duplicate, { ...manifest, stations: {
    ...manifest.stations, Hikawadai: { ...record, bytes: duplicate.length, sha256: sha256Hex(duplicate) } } }, 'Hikawadai'), { code: 'invalid_json' });
});

test('envelope rejects invalid inner payload and its actual release or station identity', () => {
  const { payloads, stationJsonBytes } = makeManifest();
  const payload = structuredClone(payloads.Hikawadai); payload.schemaVersion = 2;
  assert.throws(() => createEnvelope({ releaseId: RELEASE, stationId: 'Hikawadai', payload }), { code: 'invalid_payload' });
  const wrongStation = createEnvelope({ releaseId: RELEASE, stationId: 'Hikawadai', payload: payloads.Hikawadai });
  wrongStation.stationId = 'Senkawa';
  const raw = Buffer.from(JSON.stringify(wrongStation));
  assert.throws(() => verifyStationBytes(raw, { ...makeManifest().manifest, stations: {
    ...makeManifest().manifest.stations, Hikawadai: { url: `/releases/${RELEASE}/timetable.json`, sha256: sha256Hex(raw), bytes: raw.length } } }, 'Hikawadai'), { code: 'station_mismatch' });
  assert.ok(stationJsonBytes.Hikawadai.length > 0);
});
