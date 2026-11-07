import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto, createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { FakeElement, makeDom } from './public_runtime_dom_helper.mjs';
import { buildV2QaBoard } from '../_local_preview/odpt_v2_qa_adapter.mjs';

const root = await mkdtemp('/private/tmp/dotchi-v2-public-runtime-test-');
test.after(() => rm(root, { recursive: true, force: true }));
const fixtures = [];
for (const unknown of [0, 1]) {
  const dir = `${root}/fixture-${unknown}`;
  const validation = JSON.parse(execFileSync('python3', ['-B', 'tests/odpt_public_runtime_fixture.py', dir, String(unknown)], { encoding: 'utf8' }));
  assert.equal(validation.deployable, false);
  const manifest = JSON.parse(await readFile(`${dir}/manifest.json`, 'utf8'));
  const envelopes = Object.fromEntries(await Promise.all(Object.entries(manifest.stations).map(async ([s, r]) =>
    [s, JSON.parse(await readFile(`${dir}${r.url}`, 'utf8'))])));
  fixtures.push({ dir, manifest, envelopes });
}
const base = fixtures[0];
const module = await import(pathToFileURL(`${base.dir}/odpt_public_runtime.mjs`));
const { createV2ReleaseSession, buildV2PublicBoard, canonicalPublicJson: canonical } = module;
const { createPreviewRuntime } = await import(pathToFileURL(`${base.dir}/preview_core.mjs`));
const { startOdptPublicPreview } = await import(pathToFileURL(`${base.dir}/preview_public_v2.js`));
const hash = v => createHash('sha256').update(typeof v === 'string' ? v : canonical(v)).digest('hex');
const instant = value => Date.parse(value);
const response = raw => { const bytes = Buffer.from(raw); return { ok: true,
  arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) }; };
function fetcher(fixture = base, calls = [], modify = null) {
  return async (url, options) => {
    calls.push({ url, options });
    let raw;
    if (url === '/manifest.json') raw = canonical(fixture.manifest);
    else {
      const station = Object.keys(fixture.manifest.stations).find(s => fixture.manifest.stations[s].url === url);
      assert.ok(station, `unexpected request ${url}`);
      raw = canonical(fixture.envelopes[station]);
    }
    return response(modify ? modify(raw, url) : raw);
  };
}
async function session(f = base, calls = [], modify = null) {
  return createV2ReleaseSession({ fetchImpl: fetcher(f, calls, modify), cryptoImpl: webcrypto });
}
function seal(f) {
  const d = f.manifest.releaseDescriptor;
  d.metadataSha256 = hash(f.manifest.metadata);
  for (const row of d.stations) row.payloadSha256 = hash(f.envelopes[row.stationId].payload);
  f.manifest.releaseId = `r1-${hash(d)}`;
  for (const [s, env] of Object.entries(f.envelopes)) {
    env.releaseId = f.manifest.releaseId;
    const raw = canonical(env);
    const old = f.manifest.stations[s];
    f.manifest.stations[s] = { url: `/releases/${f.manifest.releaseId}/${old.url.split('/').at(-1)}`,
      sha256: hash(raw), bytes: Buffer.byteLength(raw) };
  }
  return f;
}
function reference(prepared, nowMs, directOnly = false, mode = 'departure') {
  const stations = { [prepared.payload.stationId]: Object.fromEntries(Object.entries(prepared.audit).map(([d, row]) => [d, {
    infoCount: row.reasonCounts.explicit_pass_info, noValidArrivalCount: row.reasonCounts.no_valid_arrival,
    otherUnknownCount: row.reasonCounts.primary_arrival_missing + row.reasonCounts.unknown,
  }])) };
  return buildV2QaBoard(prepared.payload, { stations }, { nowMs, directOnly, mode });
}
async function waitFor(predicate) {
  for (let i = 0; i < 300; i++) { if (predicate()) return; await new Promise(r => setTimeout(r, 5)); }
  assert.fail('runtime did not settle');
}
function dom() {
  const env = makeDom();
  for (const id of ['publication-information', 'publication-provider', 'publication-source', 'publication-retrieved',
    'publication-period', 'publication-contact', 'publication-contact-unset']) env.elements.set(id, new FakeElement('div', id));
  env.elements.get('publication-contact').hidden = true;
  env.documentRef.querySelector = selector => ({ content: selector.includes('dotchi-data-mode') ? 'release-managed' : 'public-display-v2' });
  return env;
}
async function runtime(f = base, now = { value: instant('2026-10-30T12:00:00+09:00') }) {
  const env = dom(); const intervals = []; const calls = [];
  const windowRef = { fetch: fetcher(f, calls), setInterval(fn) { intervals.push(fn); return intervals.length; } };
  env.runtime = createPreviewRuntime({ expectedProfile: 'public-display-v2', cacheMode: 'default', releaseManaged: true,
    releaseAdapter: { ...module.V2_PUBLIC_ADAPTER,
      createSession: options => createV2ReleaseSession({ ...options, cryptoImpl: webcrypto }) },
    nowProvider: () => now.value, documentRef: env.documentRef, windowRef });
  await waitFor(() => !env.elements.get('timetable-status').textContent.includes('読み込んでいます'));
  return { ...env, intervals, calls, now, windowRef };
}
const cards = env => env.elements.get('board').querySelectorAll('[data-departure-at]');

test('Phase 1 Python artifact loads in JS; manifest revalidates once per session, station URLs are pinned', async () => {
  const calls = []; const s = await session(base, calls);
  for (const station of Object.keys(base.manifest.stations)) {
    const prepared = await s.loadStation(station);
    assert.equal(prepared.payload.applicationPeriod, null);
    assert.equal(prepared.payload.stationId, station);
    assert.ok(Object.isFrozen(prepared.manifest.metadata));
  }
  assert.equal(calls.filter(x => x.url === '/manifest.json').length, 1);
  assert.equal(calls[0].options.cache, 'no-cache');
  assert.ok(calls.slice(1).every(x => x.options.cache === 'default' && x.options.redirect === 'error'));
  await session(base, calls);
  assert.equal(calls.filter(x => x.url === '/manifest.json').length, 2);
});

test('all eight stations, weekday/Saturday/Sunday and four scenarios match the QA adapter', async () => {
  const s = await session();
  let cells = 0;
  for (const station of Object.keys(base.manifest.stations)) {
    const prepared = await s.loadStation(station);
    for (const d of ['2026-10-30', '2026-10-31', '2026-11-01']) for (const directOnly of [false, true]) for (const mode of ['line', 'departure']) {
      const nowMs = instant(`${d}T12:00:00+09:00`);
      const board = buildV2PublicBoard(prepared, { nowMs, directOnly, mode });
      const qa = reference(prepared, nowMs, directOnly, mode);
      assert.deepEqual(board.items, qa.items); assert.deepEqual(board.groups, qa.groups);
      assert.deepEqual(board.routeStates, qa.routeStates); assert.equal(board.bestId, qa.bestId);
      assert.ok(board.items.length > 0); assert.doesNotMatch(board.statusMessage, /QA|ローカル/);
      assert.ok(board.items.every(x => x.departureAtMs <= nowMs + 3600000));
      assert.ok(board.items.every(x => x.kind !== 'S-TRAIN'));
      cells++;
    }
  }
  assert.equal(cells, 96);
});

test('public DOM preserves eight destinations, direct toggle, transfer text and train type distinctions', async () => {
  const env = await runtime();
  for (const station of Object.keys(base.manifest.stations)) {
    await env.runtime.loadDestination(station);
    assert.equal(env.elements.get('timetable-status').dataset.state, 'ok');
    assert.equal(cards(env).length, 6);
    if (station === 'Wakoshi') {
      const types = cards(env).map(c => c.querySelector('.type-label').textContent);
      assert.ok(types.includes('急行') && types.includes('通勤急行') && types.includes('Fライナー'));
      assert.ok(cards(env).some(c => c.querySelector('.sub').textContent.includes('小竹向原乗換')));
      env.elements.get('direct-only').checked = true;
      env.elements.get('direct-only').dispatch('change');
      assert.ok(cards(env).every(c => c.querySelector('.sub').textContent === '直通・乗換なし'));
      env.elements.get('direct-only').checked = false;
    }
    env.elements.get('mode-line').dispatch('click');
    assert.equal(env.elements.get('board').querySelectorAll('.line').length, 2);
    env.elements.get('mode-departure').dispatch('click');
  }
  assert.equal(env.calls.filter(c => c.url === '/manifest.json').length, 1);
});

test('publication starts inclusive, ends exclusive, and an open screen removes expired cards', async () => {
  const clock = { value: instant('2026-10-28T23:59:59+09:00') };
  const env = await runtime(base, clock);
  assert.equal(cards(env).length, 0);
  assert.equal(env.elements.get('timetable-status').dataset.state, 'warning');
  clock.value = instant('2026-10-29T00:00:00+09:00'); env.intervals[0]();
  assert.equal(env.elements.get('timetable-status').dataset.state, 'ok');
  clock.value = instant('2026-11-01T23:58:59+09:00'); env.intervals[0]();
  assert.ok(cards(env).length > 0);
  clock.value = instant('2026-11-02T00:00:00+09:00'); env.intervals[0]();
  assert.equal(cards(env).length, 0);
  assert.match(env.elements.get('timetable-status').textContent, /適用期間が終了/);
});

test('first train, terminal and 24-hour service keep the same QA semantics across midnight', async () => {
  const s = await session(); const p = await s.loadStation('Wakoshi');
  for (const text of ['2026-10-30T03:59:59', '2026-10-30T04:00:00', '2026-10-30T05:00:00',
    '2026-10-30T23:59:59', '2026-10-31T00:00:00', '2026-10-31T00:09:59', '2026-10-31T00:10:00']) {
    const nowMs = instant(`${text}+09:00`);
    const board = buildV2PublicBoard(p, { nowMs }); const qa = reference(p, nowMs);
    assert.deepEqual(board.items, qa.items); assert.deepEqual(board.routeStates, qa.routeStates);
  }
  const board = buildV2PublicBoard(p, { nowMs: instant('2026-10-31T00:00:00+09:00') });
  assert.ok(board.items.some(x => x.serviceDate === '2026-10-30' && x.isLastDeparture));
  assert.ok(board.items.some(x => x.bestLabel === '● 最早着'));
});

test('public DOM releases first trains at the one-hour boundary and renders verified 24-hour terminal badges', async () => {
  const clock = { value: instant('2026-10-30T03:59:59+09:00') };
  const env = await runtime(base, clock);
  assert.equal(cards(env).length, 0);
  clock.value = instant('2026-10-30T04:00:00+09:00'); env.intervals[0]();
  assert.equal(cards(env).length, 2);
  clock.value = instant('2026-10-31T00:00:00+09:00'); env.intervals[0]();
  assert.equal(cards(env).length, 2);
  assert.ok(cards(env).every(c => c.querySelector('.terminal-badge').textContent === '終電'));
  env.elements.get('direct-only').checked = true; env.elements.get('direct-only').dispatch('change');
  assert.ok(cards(env).every(c => c.querySelector('.terminal-badge').textContent === '直通終電'));
  clock.value = instant('2026-10-31T00:10:00+09:00'); env.intervals[0]();
  assert.equal(cards(env).length, 0);
  assert.doesNotMatch(env.elements.get('board').textContent, /本日の終電は終了/);
});

test('UNKNOWN counts retain conservative best/terminal labels; resolved WARNING and unmatched are preserved', async () => {
  const env = await runtime(fixtures[1]);
  assert.equal(env.elements.get('timetable-status').dataset.state, 'warning');
  assert.ok(cards(env).some(c => c.querySelector('.bestmark').textContent === '● 表示候補内の最早着'));
  assert.ok(cards(env).every(c => c.querySelector('.terminal-badge').textContent === ''));
  const p = await (await session(fixtures[1])).loadStation('Hikawadai');
  const q = p.manifest.metadata.quality;
  assert.equal(q.status, 'WARNING'); assert.equal(q.unmatchedOriginal, 96); assert.equal(q.warningOriginal, 96);
  assert.equal(q.resolution.classes.A, 48); assert.equal(q.resolution.classes.B, 48);
  assert.equal(q.resolution.unmatched.unresolved, 0);
});

test('missing quality, C/D, altered metadata, missing days and unknown schema reject even with recomputed hashes', async () => {
  const mutations = [
    f => { delete f.manifest.metadata.quality; },
    f => { delete f.manifest.metadata.quality.exclusionAudit.byStationDate[0].reasonCounts.no_valid_arrival; },
    f => { f.manifest.metadata.quality.resolution.classes.C = 1; },
    f => { f.manifest.metadata.quality.stationDateResolution.pop(); },
    f => { f.manifest.metadata.sourceFingerprint = '0'.repeat(64); },
    f => { f.manifest.metadata.approval.approved = false; },
    f => { f.manifest.metadata.applicationPeriod.endsAt = '2026-11-03T00:00:00+09:00'; },
    f => { f.manifest.serviceDates.splice(2, 1); },
    f => { f.manifest.schemaVersion = 3; },
  ];
  for (const mutate of mutations) {
    const f = structuredClone(base); mutate(f); seal(f);
    await assert.rejects(session(f));
  }
  const f = structuredClone(base); f.manifest.metadata.retrievedAt = '2026-10-26T00:00:00Z';
  await assert.rejects(session(f), { code: 'metadata_hash_mismatch' });
});

test('corrupt bytes, hash, payload, release ID and missing payload day fail closed', async () => {
  const s = await session(base, [], (raw, url) => url === '/manifest.json' ? raw : raw + ' ');
  await assert.rejects(s.loadStation('Hikawadai'), { code: 'byte_count_mismatch' });
  for (const mutate of [
    f => { f.envelopes.Hikawadai.payload.schemaVersion = 3; },
    f => { f.envelopes.Hikawadai.payload.serviceDays.splice(2, 1); },
    f => { f.envelopes.Hikawadai.payload.serviceDays[0].routeCoverage['9'].dataState = 'unknown'; },
  ]) {
    const f = structuredClone(base); mutate(f); seal(f);
    const sessionValue = await session(f);
    await assert.rejects(sessionValue.loadStation('Hikawadai'));
    const env = await runtime(f);
    assert.equal(cards(env).length, 0); assert.equal(env.elements.get('timetable-status').dataset.state, 'error');
  }
  const f = structuredClone(base); f.envelopes.Hikawadai.releaseId = `r1-${'0'.repeat(64)}`;
  const raw = canonical(f.envelopes.Hikawadai);
  Object.assign(f.manifest.stations.Hikawadai, { bytes: Buffer.byteLength(raw), sha256: hash(raw) });
  await assert.rejects((await session(f)).loadStation('Hikawadai'), { code: 'release_id_mismatch' });
  f.manifest.stations.Hikawadai.sha256 = '0'.repeat(64);
  await assert.rejects((await session(f)).loadStation('Hikawadai'), { code: 'hash_mismatch' });
});

test('public information uses actual retrieval metadata, provides contact configuration and has no QA controls', async () => {
  const env = await runtime();
  assert.match(env.elements.get('publication-provider').textContent, /東京メトロ/);
  const format = new Intl.DateTimeFormat('ja-JP', { timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
  assert.equal(env.elements.get('publication-retrieved').textContent, format.format(new Date(base.manifest.metadata.retrievedAt)));
  assert.notEqual(env.elements.get('publication-retrieved').textContent, format.format(new Date(base.envelopes.Hikawadai.payload.generatedAt)));
  assert.notEqual(base.manifest.metadata.retrievedAt, base.envelopes.Hikawadai.payload.generatedAt);
  const shell = await readFile(`${base.dir}/index.html`, 'utf8');
  assert.match(shell, /リアルタイム運行情報は反映しません/);
  assert.match(shell, /正確性・完全性/);
  assert.match(shell, /name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/);
  assert.match(shell, /name="dotchi-payload-profile" content="public-display-v2"/);
  assert.doesNotMatch(shell, /qa-clock|qa-datetime|preview_odpt_v2_qa\.mjs/);
  assert.equal(env.elements.get('publication-contact').hidden, true);
  const original = Date.now;
  Date.now = () => env.now.value;
  try {
    const d = dom(); d.elements.get('publication-contact').dataset.contactUrl = 'https://example.invalid/contact';
    startOdptPublicPreview({ documentRef: d.documentRef, windowRef: env.windowRef });
    await waitFor(() => d.elements.get('publication-information').hidden === false);
    assert.equal(d.elements.get('publication-contact').attributes.get('href'), 'https://example.invalid/contact');
    d.elements.get('publication-contact').dataset.contactUrl = 'javascript:alert(1)';
    assert.throws(() => startOdptPublicPreview({ documentRef: d.documentRef, windowRef: env.windowRef }));
  } finally { Date.now = original; }
});

test('v2 old session keeps its generation while a new session revalidates the new manifest', async () => {
  const next = structuredClone(base);
  next.manifest.metadata.approval.recordId = 'synthetic-next-generation'; seal(next);
  let active = base;
  const fetchImpl = async (url, options) => {
    if (url === '/manifest.json') { assert.equal(options.cache, 'no-cache'); return response(canonical(active.manifest)); }
    const f = [base, next].find(f => Object.values(f.manifest.stations).some(r => r.url === url));
    return fetcher(f)(url, options);
  };
  const first = await createV2ReleaseSession({ fetchImpl, cryptoImpl: webcrypto });
  active = next;
  const second = await createV2ReleaseSession({ fetchImpl, cryptoImpl: webcrypto });
  assert.notEqual(first.releaseId, second.releaseId);
  assert.equal((await first.loadStation('Hikawadai')).manifest.releaseId, base.manifest.releaseId);
  assert.equal((await second.loadStation('Hikawadai')).manifest.releaseId, next.manifest.releaseId);
});

test('quality counts must agree with selected payload, and loaded stations must share generatedAt', async () => {
  const f = structuredClone(base);
  const q = f.manifest.metadata.quality;
  const row = q.exclusionAudit.byStationDate.find(r => r.stationId === 'Hikawadai');
  row.generatedCount++; row.candidateCount++;
  q.exclusionAudit.totalGeneratedCount++; q.exclusionAudit.candidateCount++; q.odptMatchStatusCounts.unique_match++;
  seal(f);
  await assert.rejects((await session(f)).loadStation('Hikawadai'), { code: 'audit_candidate_mismatch' });
  const other = structuredClone(base);
  other.envelopes.Wakoshi.payload.generatedAt = '2026-10-28T00:30:00Z'; seal(other);
  const s = await session(other); await s.loadStation('Hikawadai');
  await assert.rejects(s.loadStation('Wakoshi'), { code: 'generated_at_mismatch' });
});

test('unavailable crypto, noncanonical duplicate JSON and excessive bodies are rejected', async () => {
  await assert.rejects(createV2ReleaseSession({ fetchImpl: fetcher(), cryptoImpl: {} }), { code: 'crypto_unavailable' });
  await assert.rejects(session(base, [], (raw, url) => url === '/manifest.json'
    ? raw.replace('"schemaVersion":2', '"schemaVersion":2,"schemaVersion":2') : raw), { code: 'json_not_canonical' });
  await assert.rejects(createV2ReleaseSession({ cryptoImpl: webcrypto, fetchImpl: async () => ({ ok: true,
    headers: { get: () => String(25 * 1024 * 1024 + 1) }, arrayBuffer() { assert.fail('oversize body must not be read'); } }) }),
  { code: 'response_size_invalid' });
});
