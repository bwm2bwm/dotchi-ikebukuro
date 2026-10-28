import test from 'node:test';
import assert from 'node:assert/strict';
import { cp, mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { webcrypto } from 'node:crypto';
import { LOCAL_DATA_SCOPE, PUBLIC_DATA_SCOPE } from '../scripts/timetable_adapter.mjs';
import { buildReleaseDescriptor, calculateReleaseId, createManifest, encodeEnvelope, encodeManifest,
  STATION_FILES } from '../scripts/release_contract.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const runtimeDirectory = await mkdtemp(path.join(os.tmpdir(), 'preview-runtime-test-'));
for (const filename of ['preview_core.mjs']) {
  await cp(path.join(root, '_local_preview', filename), path.join(runtimeDirectory, filename));
}
for (const filename of ['timetable_adapter.mjs', 'local_preview_payload_loader.mjs']) {
  await cp(path.join(root, 'scripts', filename), path.join(runtimeDirectory, filename));
}
for (const filename of ['selection.mjs', 'terminal_ui.mjs']) {
  await cp(path.join(root, '_local_preview', filename), path.join(runtimeDirectory, filename));
}
const [{ createPreviewRuntime }, core, localEntry, publicEntry] = await Promise.all([
  import(pathToFileURL(path.join(runtimeDirectory, 'preview_core.mjs')).href),
  readFile(new URL('../_local_preview/preview_core.mjs', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview.js', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview_public.js', import.meta.url), 'utf8'),
]);
test.after(() => rm(runtimeDirectory, { recursive: true, force: true }));

test('shared runtime validates profile-specific cache policy before touching the DOM', () => {
  const documentRef = { getElementById: () => null };
  const windowRef = {};
  assert.throws(() => createPreviewRuntime({ expectedProfile: LOCAL_DATA_SCOPE, cacheMode: 'default', documentRef, windowRef }),
    /local-preview-only requires cacheMode no-store/);
  assert.throws(() => createPreviewRuntime({ expectedProfile: PUBLIC_DATA_SCOPE, cacheMode: 'no-store', documentRef, windowRef }),
    /public-display-v1 requires cacheMode default/);
  assert.throws(() => createPreviewRuntime({ expectedProfile: 'unknown', cacheMode: 'default', documentRef, windowRef }),
    /explicit supported expected payload profile required/);
  assert.throws(() => createPreviewRuntime({ expectedProfile: PUBLIC_DATA_SCOPE, cacheMode: 'default', documentRef, windowRef }),
    /preview DOM is missing required elements/);
});

test('shared runtime accepts a public DOM without diagnostic nodes and rejects partial metadata DOM', () => {
  const normalIds = ['clock', 'timetable-status', 'board', 'destination-trigger', 'route-display',
    'destination-dialog', 'destination-close', 'destination-list', 'direct-only', 'mode-line', 'mode-departure'];
  const elements = new Map(normalIds.map(id => [id, new FakeElement()]));
  elements.set('payload-metadata', new FakeElement());
  const documentRef = { getElementById: id => elements.get(id) ?? null };
  assert.throws(() => createPreviewRuntime({ expectedProfile: PUBLIC_DATA_SCOPE, cacheMode: 'default', documentRef,
    windowRef: {} }), /incomplete optional metadata elements: meta-application-period/);
});

test('local bootstrap owns virtual-time and performance diagnostics; the core imports neither', () => {
  assert.match(localEntry, /LOCAL_DATA_SCOPE/);
  assert.match(localEntry, /cacheMode: 'no-store'/);
  assert.match(localEntry, /parseVirtualNow/);
  assert.match(localEntry, /isPerformanceMode/);
  assert.match(localEntry, /performance_metrics\.mjs/);
  assert.match(localEntry, /finishAfterRender: finishMeasurementAfterRender/);
  assert.doesNotMatch(core, /virtual_now\.mjs|performance_metrics\.mjs|debugNow|perf=1/);
});

test('public bootstrap fixes public profile and default cache and imports no local diagnostics', () => {
  assert.match(publicEntry, /expectedProfile: PUBLIC_DATA_SCOPE/);
  assert.match(publicEntry, /cacheMode: 'default'/);
  assert.match(publicEntry, /nowProvider: \(\) => Date\.now\(\)/);
  assert.doesNotMatch(publicEntry, /debugNow|perf=1|virtual_now\.mjs|performance_metrics\.mjs|LOCAL_DATA_SCOPE/);
  assert.match(publicEntry, /startPublicPreview\(\{ documentRef = document, windowRef = window \} = \{\}\)/);
});

test('core takes logical time and optional measurement hooks from its caller', () => {
  assert.match(core, /nowProvider = Date\.now/);
  assert.match(core, /const nowMs = nowProvider\(\)/);
  assert.match(core, /hooks\.beginSwitch\?\./);
  assert.match(core, /hooks\.finishAfterRender\?\./);
  assert.match(core, /hooks\.onStale\?\./);
});

class FakeElement {
  constructor() {
    this.children = [];
    this.listeners = new Map();
    this.dataset = {};
    this.style = { setProperty() {} };
    this.classList = { toggle() {}, add() {}, remove() {} };
    this.checked = false;
    this.open = false;
    this.hidden = false;
    this.textContent = '';
  }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children.flatMap(child => child.children ?? [child]); }
  setAttribute() {}
  querySelector(selector) {
    if (selector === '[data-release-reload]') return this.children.find(child => child.dataset?.releaseReload === 'true') ?? null;
    return new FakeElement();
  }
  querySelectorAll() { return []; }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
}

function initialPayload(scope) {
  const dates = ['2026-10-24', '2026-10-25', '2026-10-26'];
  return {
    schemaVersion: 1,
    dataScope: scope,
    generatedAt: '2026-10-24T00:00:00+09:00',
    timezone: 'Asia/Tokyo',
    feed: { version: 'synthetic', validFrom: dates[0], validThrough: dates[2], sourceUpdatedAt: null },
    odpt: { sourceUpdatedAt: null },
    applicationPeriod: { startsAt: '2026-10-24T00:00:00+09:00', endsAt: '2026-10-27T00:00:00+09:00' },
    webApp: { builtAt: null },
    connectionPolicy: { minimumWaitSeconds: 60, maximumWaitSeconds: 600,
      platformStatus: 'unknown', connectionGuaranteed: false },
    serviceDays: dates.map(serviceDate => ({ serviceDate, originStationId: 'Ikebukuro',
      destinationStationId: 'Hikawadai', departures: [] })),
    excludedServiceDates: [],
  };
}

for (const [name, expectedProfile, cacheMode] of [
  ['local', LOCAL_DATA_SCOPE, 'no-store'],
  ['public', PUBLIC_DATA_SCOPE, 'default'],
]) {
  test(`${name} runtime performs the initial synthetic payload load and leaves loading state`, async () => {
    const ids = ['clock', 'timetable-status', 'board', 'destination-trigger', 'route-display',
      'destination-dialog', 'destination-close', 'destination-list', 'direct-only', 'mode-line', 'mode-departure'];
    if (expectedProfile === LOCAL_DATA_SCOPE) ids.push('payload-metadata', 'meta-application-period', 'meta-generated-at',
      'meta-feed-period', 'meta-gtfs-updated', 'meta-odpt-updated', 'meta-webapp-built');
    const elements = new Map(ids.map(id => [id, new FakeElement()]));
    const documentRef = {
      getElementById: id => elements.get(id) ?? null,
      createDocumentFragment: () => new FakeElement(),
      createElement: () => new FakeElement(),
      body: new FakeElement(),
      activeElement: null,
    };
    const fetchCalls = [];
    const windowRef = {
      fetch: async (url, options) => {
        fetchCalls.push({ url, options });
        return { ok: true, headers: { get: () => null }, text: async () => JSON.stringify(initialPayload(expectedProfile)) };
      },
      setInterval() { return 1; },
    };
    createPreviewRuntime({ expectedProfile, cacheMode, nowProvider: () => Date.parse('2026-10-25T03:00:00Z'),
      documentRef, windowRef });
    for (let attempt = 0; attempt < 50 && fetchCalls.length === 0; attempt += 1) {
      await new Promise(resolve => setImmediate(resolve));
    }
    for (let attempt = 0; attempt < 50 && elements.get('timetable-status').textContent.includes('読み込んでいます'); attempt += 1) {
      await new Promise(resolve => setImmediate(resolve));
    }
    assert.equal(fetchCalls.length, 1);
    assert.equal(fetchCalls[0].url, './timetable.json');
    assert.equal(fetchCalls[0].options.cache, cacheMode);
    assert.doesNotMatch(elements.get('timetable-status').textContent, /読み込んでいます/);
    assert.notEqual(elements.get('timetable-status').dataset.state, undefined);
    assert.ok(elements.get('board').children.length > 0);
    if (expectedProfile === PUBLIC_DATA_SCOPE) assert.equal(elements.has('payload-metadata'), false);
  });
}

test('runtime converts an unexpected initial loader rejection into a visible error state', async () => {
  const ids = ['clock', 'timetable-status', 'board', 'destination-trigger', 'route-display',
    'destination-dialog', 'destination-close', 'destination-list', 'direct-only', 'mode-line', 'mode-departure',
    'payload-metadata', 'meta-application-period', 'meta-generated-at', 'meta-feed-period', 'meta-gtfs-updated',
    'meta-odpt-updated', 'meta-webapp-built'];
  const elements = new Map(ids.map(id => [id, new FakeElement()]));
  const documentRef = { getElementById: id => elements.get(id) ?? null,
    createDocumentFragment: () => new FakeElement(), createElement: () => new FakeElement(),
    body: new FakeElement(), activeElement: null };
  const windowRef = { setInterval() { return 1; } };
  Object.defineProperty(windowRef, 'fetch', { get() { throw new Error('synthetic fetch getter failure'); } });
  createPreviewRuntime({ expectedProfile: LOCAL_DATA_SCOPE, cacheMode: 'no-store',
    nowProvider: () => Date.parse('2026-10-25T03:00:00Z'), documentRef, windowRef });
  for (let attempt = 0; attempt < 50 && elements.get('timetable-status').textContent.includes('読み込んでいます'); attempt += 1) {
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.match(elements.get('timetable-status').textContent, /payloadを読み込めませんでした/);
  assert.equal(elements.get('timetable-status').dataset.state, 'error');
});

test('release-managed startup fails closed on manifest 404 and exposes one manual reload action', async () => {
  const ids = ['clock', 'timetable-status', 'board', 'destination-trigger', 'route-display',
    'destination-dialog', 'destination-close', 'destination-list', 'direct-only', 'mode-line', 'mode-departure'];
  const elements = new Map(ids.map(id => [id, new FakeElement()]));
  const documentRef = { getElementById: id => elements.get(id) ?? null,
    createDocumentFragment: () => new FakeElement(), createElement: () => new FakeElement(),
    body: new FakeElement(), activeElement: null };
  let reloads = 0;
  const saved = new Map();
  const sessionStorage = { getItem: key => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value), removeItem: key => saved.delete(key) };
  const windowRef = { fetch: async () => ({ ok: false, status: 404, arrayBuffer: async () => new ArrayBuffer(0) }),
    setInterval() { return 1; }, sessionStorage, location: { reload() { reloads += 1; } } };
  createPreviewRuntime({ expectedProfile: PUBLIC_DATA_SCOPE, cacheMode: 'default', releaseManaged: true,
    documentRef, windowRef });
  const status = elements.get('timetable-status');
  for (let attempt = 0; attempt < 50 && status.dataset.state !== 'error'; attempt += 1) {
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.equal(status.dataset.state, 'error');
  assert.match(status.textContent, /公開情報を確認できませんでした/);
  assert.equal(elements.get('board').children.length, 0, 'unverified payload never becomes no-trains content');
  const buttons = status.children.filter(child => child.dataset.releaseReload === 'true');
  assert.equal(buttons.length, 1);
  buttons[0].listeners.get('click')();
  assert.equal(buttons[0].disabled, true);
  assert.equal(reloads, 1);

  const secondElements = new Map(ids.map(id => [id, new FakeElement()]));
  const secondDocument = { getElementById: id => secondElements.get(id) ?? null,
    createDocumentFragment: () => new FakeElement(), createElement: () => new FakeElement(),
    body: new FakeElement(), activeElement: null };
  createPreviewRuntime({ expectedProfile: PUBLIC_DATA_SCOPE, cacheMode: 'default', releaseManaged: true,
    documentRef: secondDocument, windowRef });
  const secondStatus = secondElements.get('timetable-status');
  for (let attempt = 0; attempt < 50 && secondStatus.dataset.state !== 'error'; attempt += 1) {
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.match(secondStatus.textContent, /時間をおいて/);
  assert.equal(secondStatus.children.some(child => child.dataset.releaseReload === 'true'), false,
    'a failed manual reload does not keep prompting the user to reload');
});

test('release-managed runtime displays a payload only after it matches the pinned release', async () => {
  const payloads = JSON.parse(execFileSync('python3', ['-c',
    'import json; from synthetic_public_fixture_factory import STATION_FILES, make_public_fixture; d=["2026-10-26","2026-10-27","2026-10-28"]; print(json.dumps({s:make_public_fixture(s,d) for s in STATION_FILES},ensure_ascii=False,separators=(",",":")))',
  ], { cwd: root, encoding: 'utf8', env: { ...process.env, PYTHONPATH: path.join(root, 'scripts') } }));
  const descriptor = buildReleaseDescriptor({ runtimeContract: 'dotchi-public-runtime-v2',
    builderContractVersion: 'dotchi-public-builder-v1', payloads, assets: {
      'index.html': Buffer.from('<html>'), 'styles.css': Buffer.from('body{}'), 'preview.js': Buffer.from('export {};'),
    } });
  const releaseId = calculateReleaseId(descriptor);
  const envelopeBytes = Object.fromEntries(Object.keys(STATION_FILES).map(id => [id,
    encodeEnvelope({ releaseId, stationId: id, payload: payloads[id] })]));
  const manifest = createManifest({ releaseId, releaseDescriptor: descriptor, publishedAt: null,
    generatedAt: payloads.Hikawadai.generatedAt, serviceDateRange: { from: '2026-10-26', through: '2026-10-28' },
    feed: payloads.Hikawadai.feed, applicationPeriod: payloads.Hikawadai.applicationPeriod,
    stationJsonBytes: envelopeBytes });
  const calls = [];
  const response = bytes => { const raw = Buffer.from(bytes); return { ok: true,
    arrayBuffer: async () => raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength) }; };
  const ids = ['clock', 'timetable-status', 'board', 'destination-trigger', 'route-display',
    'destination-dialog', 'destination-close', 'destination-list', 'direct-only', 'mode-line', 'mode-departure'];
  const elements = new Map(ids.map(id => [id, new FakeElement()]));
  const documentRef = { getElementById: id => elements.get(id) ?? null,
    createDocumentFragment: () => new FakeElement(), createElement: () => new FakeElement(),
    body: new FakeElement(), activeElement: null };
  const windowRef = { fetch: async url => {
    calls.push(url);
    if (url === '/manifest.json') return response(encodeManifest(manifest));
    const stationId = Object.keys(STATION_FILES).find(id => manifest.stations[id].url === url);
    return response(envelopeBytes[stationId]);
  }, setInterval() { return 1; }, crypto: webcrypto };
  const runtime = createPreviewRuntime({ expectedProfile: PUBLIC_DATA_SCOPE, cacheMode: 'default', releaseManaged: true,
    nowProvider: () => Date.parse('2026-10-27T03:00:00Z'), documentRef, windowRef });
  for (let attempt = 0; attempt < 100 && elements.get('timetable-status').textContent.includes('読み込んでいます'); attempt += 1) {
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.equal(runtime.releaseId, releaseId);
  assert.equal(elements.get('timetable-status').dataset.state, 'ok');
  assert.ok(elements.get('board').children.length > 0);
  assert.deepEqual(calls, ['/manifest.json', manifest.stations.Hikawadai.url]);
});
