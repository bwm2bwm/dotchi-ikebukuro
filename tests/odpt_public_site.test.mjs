import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash, webcrypto } from 'node:crypto';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import http from 'node:http';
import { makeDom, FakeElement } from './public_runtime_dom_helper.mjs';

const root = await mkdtemp('/private/tmp/dotchi-v2-site-test-');
test.after(() => rm(root, { recursive: true, force: true }));
const site = `${root}/site`;
const result = JSON.parse(execFileSync('python3', ['-B', 'tests/odpt_public_runtime_fixture.py', site, '0', 'full-site'], { encoding: 'utf8' }));
assert.equal(result.siteComplete, true);
const manifest = JSON.parse(await readFile(`${site}/manifest.json`, 'utf8'));
const runtime = await import(pathToFileURL(`${site}/odpt_public_runtime.mjs`));
const { startOdptPublicPreview } = await import(pathToFileURL(`${site}/preview_public_v2.js`));
const sha = raw => createHash('sha256').update(raw).digest('hex');
const paths = ['/manifest.json', ...manifest.releaseDescriptor.assets.map(a => `/${a.path}`),
  ...Object.values(manifest.stations).map(r => r.url)];
const files = new Map(await Promise.all(paths.map(async p => [p, await readFile(`${site}${p}`)])));
const calls = [];
function fakeFetch(url, options) {
  calls.push({ url, options });
  const raw = files.get(url); assert.ok(raw, `off-artifact request: ${url}`);
  return Promise.resolve(new Response(raw));
}

test('full-site descriptor binds every public asset and rejects asset metadata changes', async () => {
  assert.equal(manifest.artifactKind, 'release-full-site');
  assert.equal(manifest.releaseDescriptor.assets.length, 12);
  assert.equal(files.size, 21);
  assert.equal(files.has('/preview_public.js'), false);
  assert.equal(files.has('/preview_odpt_v2_qa.mjs'), false);
  for (const a of manifest.releaseDescriptor.assets) {
    const raw = files.get(`/${a.path}`);
    assert.equal(a.bytes, raw.length); assert.equal(a.sha256, sha(raw));
  }
  await runtime.validateV2ReleaseManifest(manifest, webcrypto);
  const altered = structuredClone(manifest); altered.releaseDescriptor.assets[0].sha256 = '0'.repeat(64);
  await assert.rejects(runtime.validateV2ReleaseManifest(altered, webcrypto), { code: 'release_id_mismatch' });
  altered.releaseDescriptor.assets[0].path = '../index.html';
  await assert.rejects(runtime.validateV2ReleaseManifest(altered, webcrypto), { code: 'asset_record_invalid' });
  const mixed = structuredClone(manifest); mixed.artifactKind = 'release-data-only';
  await assert.rejects(runtime.validateV2ReleaseManifest(mixed, webcrypto));
});

test('full-site runtime loads all eight public generation paths and renders without QA controls', async () => {
  const session = await runtime.createV2ReleaseSession({ fetchImpl: fakeFetch, cryptoImpl: webcrypto });
  const nowMs = Date.parse('2026-10-31T12:00:00+09:00');
  for (const station of Object.keys(manifest.stations)) {
    const p = await session.loadStation(station);
    const board = runtime.buildV2PublicBoard(p, { nowMs });
    assert.equal(board.validity, 'valid'); assert.ok(board.items.length > 0);
    assert.equal(p.manifest.releaseId, manifest.releaseId);
    assert.equal(p.payload.applicationPeriod, null);
  }
  assert.equal(calls.filter(c => c.url === '/manifest.json').length, 1);
  const env = makeDom();
  for (const id of ['publication-information', 'publication-provider', 'publication-source', 'publication-retrieved',
    'publication-period', 'publication-contact', 'publication-contact-unset']) env.elements.set(id, new FakeElement('div', id));
  env.elements.get('publication-contact').dataset.contactUrl = 'https://example.invalid/contact';
  env.documentRef.querySelector = selector => ({ content: selector.includes('dotchi-data-mode') ? 'release-managed' : 'public-display-v2' });
  const originalNow = Date.now; Date.now = () => nowMs;
  let app;
  try {
    app = startOdptPublicPreview({ documentRef: env.documentRef, windowRef: { fetch: fakeFetch, setInterval() {} } });
    for (let i=0; i<300 && env.elements.get('timetable-status').textContent.includes('読み込んでいます'); i++) {
      await new Promise(r => setTimeout(r, 5));
    }
    assert.equal(app.releaseId, manifest.releaseId);
    assert.equal(env.elements.get('timetable-status').dataset.state, 'ok');
    assert.equal(env.elements.get('board').querySelectorAll('[data-departure-at]').length, 6);
    assert.doesNotMatch(files.get('/index.html').toString(), /qa-clock|qa-datetime|virtual_now/);
    assert.match(files.get('/index.html').toString(), /data-contact-url="https:\/\/example.invalid\/contact"/);
  } finally { Date.now = originalNow; }
});

test('loopback HTTP serves all bound assets and the exact station URLs used by the runtime', async () => {
  // Listen only on loopback and never fetch a host outside this temporary server.
  const requested = [];
  const server = http.createServer((req, res) => {
    requested.push(req.url);
    const raw = files.get(req.url === '/' ? '/index.html' : req.url);
    if (!raw) { res.writeHead(404); res.end(); return; }
    const ext = req.url.split('.').at(-1);
    const type = ext === 'json' ? 'application/json' : ext === 'css' ? 'text/css'
      : ['js', 'mjs'].includes(ext) ? 'text/javascript' : 'text/html';
    res.writeHead(200, { 'Content-Type': type, 'Content-Length': raw.length }); res.end(raw);
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  try {
    const origin = `http://127.0.0.1:${server.address().port}`;
    const fetchImpl = (path, options) => {
      assert.ok(paths.includes(path)); return fetch(origin + path, options);
    };
    for (const a of manifest.releaseDescriptor.assets) {
      const response = await fetchImpl('/' + a.path);
      assert.equal(response.status, 200);
      const raw = Buffer.from(await response.arrayBuffer());
      assert.equal(raw.length, a.bytes); assert.equal(sha(raw), a.sha256);
    }
    const s = await runtime.createV2ReleaseSession({ fetchImpl, cryptoImpl: webcrypto });
    for (const station of Object.keys(manifest.stations)) {
      assert.equal((await s.loadStation(station)).payload.stationId, station);
    }
    assert.equal(requested.length, 21);
  } finally {
    await new Promise(resolve => { server.close(resolve); server.closeAllConnections(); });
  }
});
