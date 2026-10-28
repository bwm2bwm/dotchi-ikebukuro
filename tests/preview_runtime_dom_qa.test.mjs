import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { DESTINATION_PAYLOADS } from '../scripts/local_preview_payload_loader.mjs';
import { PUBLIC_DATA_SCOPE } from '../scripts/timetable_adapter.mjs';
import { createQaClock } from '../scripts/synthetic_public_qa_clock.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const qaScript = path.join(root, 'scripts', 'serve_synthetic_public_qa.py');
const qaRoot = await mkdtemp('/private/tmp/dotchi-public-qa-dom-test-');
await rm(qaRoot, { recursive: true, force: true });
execFileSync('python3', ['-B', qaScript, '--prepare-only', '--output', qaRoot], {
  cwd: root,
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'pipe'],
});
const releaseQaRoot = await mkdtemp('/private/tmp/dotchi-release-qa-dom-test-');
await rm(releaseQaRoot, { recursive: true, force: true });
execFileSync('python3', ['-B', qaScript, '--prepare-only', '--release-managed', '--output', releaseQaRoot], {
  cwd: root,
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'pipe'],
});

const stationNames = new Map([
  ['Kanamecho', '要町'], ['Senkawa', '千川'], ['KotakeMukaihara', '小竹向原'], ['Hikawadai', '氷川台'],
  ['Heiwadai', '平和台'], ['ChikatetsuAkatsuka', '地下鉄赤塚'], ['ChikatetsuNarimasu', '地下鉄成増'],
  ['Wakoshi', '和光市'],
]);
const stationFiles = new Map(Object.entries(DESTINATION_PAYLOADS).map(([id, filename]) => [filename.slice(2), id]));

async function countTreeFiles(directory) {
  let count = 0;
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const entryPath = path.join(directory, entry.name);
    count += entry.isDirectory() ? await countTreeFiles(entryPath) : 1;
  }
  return count;
}

class FakeElement {
  constructor(tagName = 'div', id = '') {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.listeners = new Map();
    this.dataset = {};
    this.attributes = new Map();
    this.style = { setProperty() {} };
    this.classTokens = new Set();
    this.classList = {
      add: (...values) => values.forEach(value => this.classTokens.add(value)),
      remove: (...values) => values.forEach(value => this.classTokens.delete(value)),
      toggle: (value, force) => {
        const shouldAdd = force === undefined ? !this.classTokens.has(value) : Boolean(force);
        if (shouldAdd) this.classTokens.add(value);
        else this.classTokens.delete(value);
        return shouldAdd;
      },
      contains: value => this.classTokens.has(value),
    };
    this.checked = false;
    this.open = false;
    this.hidden = false;
    this.value = '';
    this._textContent = '';
    this._innerHTML = '';
    this.nodes = new Map();
  }

  get className() { return [...this.classTokens].join(' '); }
  set className(value) { this.classTokens = new Set(String(value).split(/\s+/).filter(Boolean)); }
  get textContent() { return this._textContent; }
  set textContent(value) { this._textContent = value === null ? '' : String(value); }
  set innerHTML(value) {
    this._innerHTML = String(value);
    this.children = [];
    this.nodes.clear();
    for (const selector of ['.route', '.bestmark', '.departure-text', '.type-label', '.destination-label',
      '.terminal-badge', '.sub', '.arrival', '.arrival-caption', '.count']) {
      const element = new FakeElement('span');
      element.className = selector.slice(1);
      this.nodes.set(selector, element);
      this.appendChild(element);
    }
  }
  get innerHTML() { return this._innerHTML; }

  addEventListener(name, callback) {
    const callbacks = this.listeners.get(name) ?? [];
    callbacks.push(callback);
    this.listeners.set(name, callbacks);
  }
  dispatch(name, event = {}) {
    for (const callback of this.listeners.get(name) ?? []) callback({ target: this, key: '', ...event });
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  appendChild(child) {
    if (child.isFragment) {
      this.children.push(...child.children);
      child.children = [];
    } else this.children.push(child);
    return child;
  }
  replaceChildren(...children) {
    this.children = [];
    children.forEach(child => this.appendChild(child));
    this._textContent = '';
  }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatch('close'); }
  createDocumentFragment() { const fragment = new FakeElement('#document-fragment'); fragment.isFragment = true; return fragment; }

  querySelector(selector) {
    if (this.nodes.has(selector)) return this.nodes.get(selector);
    const destinationMatch = selector.match(/^\[data-destination-id="([^"]+)"\]$/);
    if (destinationMatch) return this.querySelectorAll('[data-destination-id]').find(node =>
      node.dataset.destinationId === destinationMatch[1]) ?? null;
    return this.querySelectorAll(selector)[0] ?? null;
  }
  querySelectorAll(selector) {
    const descendants = [];
    const visit = element => {
      for (const child of element.children) {
        descendants.push(child);
        visit(child);
      }
    };
    visit(this);
    if (selector === '[data-departure-at]') return descendants.filter(element => element.dataset.departureAt !== undefined);
    if (selector === '[data-destination-id]') return descendants.filter(element => element.dataset.destinationId !== undefined);
    if (selector === '.destination-option') return descendants.filter(element => element.classList.contains('destination-option'));
    if (selector === '.line') return descendants.filter(element => element.classList.contains('line'));
    return [];
  }
}

function makeDom() {
  const ids = ['clock', 'timetable-status', 'board', 'destination-trigger', 'route-display',
    'destination-dialog', 'destination-close', 'destination-list', 'direct-only', 'mode-line', 'mode-departure'];
  const elements = new Map(ids.map(id => [id, new FakeElement(id === 'board' ? 'section' : 'div', id)]));
  const documentRef = {
    body: new FakeElement('body'),
    activeElement: null,
    getElementById: id => elements.get(id) ?? null,
    createDocumentFragment: () => new FakeElement('#document-fragment').markFragment(),
    createElement: tagName => new FakeElement(tagName),
  };
  return { elements, documentRef };
}

FakeElement.prototype.markFragment = function markFragment() { this.isFragment = true; return this; };

async function createRuntime({ artifact = 'evening', instant = '2026-10-26T22:05:00+09:00',
  releaseManaged = false, nowProvider = () => Date.parse(instant), fetchOverride = null } = {}) {
  const { elements, documentRef } = makeDom();
  const calls = [];
  let manifestFetches = 0;
  const intervals = [];
  const artifactRoot = releaseManaged ? releaseQaRoot : qaRoot;
  const artifactPath = path.join(artifactRoot, 'artifacts', artifact);
  const manifest = releaseManaged ? JSON.parse(await readFile(path.join(artifactPath, 'manifest.json'), 'utf8')) : null;
  const respond = bytes => {
    const raw = Buffer.from(bytes);
    return { ok: true, status: 200, headers: { get: () => String(raw.length) },
      text: async () => raw.toString('utf8'),
      arrayBuffer: async () => raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength) };
  };
  const windowRef = {
    setInterval(callback) { intervals.push(callback); return intervals.length; },
    fetch: async input => {
      const url = String(input);
      if (releaseManaged && url === '/manifest.json') {
        manifestFetches += 1;
        return respond(await readFile(path.join(artifactPath, 'manifest.json')));
      }
      let stationId;
      let filePath;
      if (releaseManaged) {
        stationId = Object.keys(manifest.stations).find(id => manifest.stations[id].url === url);
        assert.ok(stationId, `unexpected release-managed station request: ${url}`);
        filePath = path.join(artifactPath, manifest.stations[stationId].url.slice(1));
      } else {
        stationId = stationFiles.get(path.basename(url));
        assert.ok(stationId, `unexpected legacy payload request: ${url}`);
        filePath = path.join(artifactPath, path.basename(url));
      }
      const raw = await readFile(filePath);
      const json = JSON.parse(raw.toString('utf8'));
      const payload = releaseManaged ? json.payload : json;
      const call = { stationId, url, payloadDestinationId: payload.serviceDays[0].destinationStationId,
        releaseId: releaseManaged ? json.releaseId : null };
      calls.push(call);
      const response = respond(raw);
      return fetchOverride ? fetchOverride({ input, url, stationId, call, response }) : response;
    },
  };
  const runtimeModule = await import(pathToFileURL(path.join(artifactRoot, 'artifacts', artifact, 'preview_core.mjs')).href);
  const runtime = runtimeModule.createPreviewRuntime({
    expectedProfile: PUBLIC_DATA_SCOPE,
    cacheMode: 'default',
    releaseManaged,
    nowProvider,
    documentRef,
    windowRef,
  });
  await waitFor(() => !elements.get('timetable-status').textContent.includes('読み込んでいます'));
  return { runtime, elements, documentRef, calls, intervals, manifest, get manifestFetches() { return manifestFetches; } };
}

async function waitFor(predicate) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail('runtime did not finish loading synthetic payload');
}

function cards(elements) {
  return elements.get('board').querySelectorAll('[data-departure-at]');
}

function cardTimes(elements) {
  return cards(elements).map(card => card.querySelector('.departure-text').textContent);
}

function arrivalTimes(elements) {
  return cards(elements).map(card => card.querySelector('.arrival').textContent);
}

function fire(elements, id, eventName) { elements.get(id).dispatch(eventName); }

test.after(async () => {
  await rm(qaRoot, { recursive: true, force: true });
  await rm(releaseQaRoot, { recursive: true, force: true });
});

test('fixed-time render is repeatable and shows ordered cards, earliest arrival, line cap, and transfer filtering', async () => {
  const first = await createRuntime();
  const second = await createRuntime();
  const snapshot = runtime => cards(runtime.elements).map(card => ({
    time: card.querySelector('.departure-text').textContent,
    route: card.querySelector('.route').textContent,
    best: card.querySelector('.bestmark').textContent,
    transfer: card.querySelector('.sub').textContent,
  }));
  assert.deepEqual(snapshot(first), snapshot(second));
  assert.deepEqual(cardTimes(first.elements), ['22:15', '22:30', '22:32', '22:35', '22:40', '22:45']);
  assert.equal(cards(first.elements).length, 6);
  assert.match(first.elements.get('timetable-status').textContent, /^ダイヤ適用期限 /);
  assert.doesNotMatch(first.elements.get('timetable-status').textContent, /undefined|null/);

  const best = cards(first.elements).filter(card => card.querySelector('.bestmark').textContent === '● 最早着');
  assert.equal(best.length, 1);
  assert.equal(best[0].querySelector('.departure-text').textContent, '22:15');

  fire(first.elements, 'mode-line', 'click');
  const routeSections = first.elements.get('board').querySelectorAll('.line');
  assert.deepEqual(routeSections.map(section => section.children.length), [3, 3]);
  assert.equal(cards(first.elements).filter(card => card.querySelector('.sub').textContent.includes('小竹向原乗換')).length, 1);

  const directOnly = first.elements.get('direct-only');
  directOnly.checked = true;
  directOnly.dispatch('change');
  assert.equal(cards(first.elements).length, 6);
  assert.equal(cards(first.elements).some(card => card.querySelector('.sub').textContent.includes('小竹向原乗換')), false);
  assert.equal(cards(first.elements).filter(card => card.querySelector('.bestmark').textContent === '● 最早着').length, 1);
  directOnly.checked = false;
  directOnly.dispatch('change');
  assert.equal(cards(first.elements).filter(card => card.querySelector('.sub').textContent.includes('小竹向原乗換')).length, 1);
});

test('all eight destinations load the matching public synthetic payload', async () => {
  const runtime = await createRuntime();
  for (const [stationId, name] of stationNames) {
    const option = runtime.elements.get('destination-list').querySelector(`[data-destination-id="${stationId}"]`);
    assert.ok(option, `missing station option ${stationId}`);
    option.dispatch('click');
    await waitFor(() => runtime.elements.get('route-display').textContent === `池袋 → ${name}`
      && !runtime.elements.get('timetable-status').textContent.includes('読み込んでいます'));
    const latest = runtime.calls.at(-1);
    assert.equal(latest.stationId, stationId);
    assert.equal(latest.payloadDestinationId, stationId);
    assert.equal(latest.releaseId, null);
  }
});

test('release-managed destination switch fetches pinned station URLs and renders station-specific arrivals', async () => {
  const runtime = await createRuntime({ artifact: 'destination-switch', releaseManaged: true });
  assert.equal(runtime.calls.filter(call => call.stationId === 'Hikawadai').length, 1);
  assert.deepEqual(runtime.calls[0], { stationId: 'Hikawadai', url: runtime.manifest.stations.Hikawadai.url,
    payloadDestinationId: 'Hikawadai', releaseId: runtime.manifest.releaseId });

  const displayed = new Map([['Hikawadai', arrivalTimes(runtime.elements).join('|')]]);
  for (const stationId of ['Senkawa', 'KotakeMukaihara', 'ChikatetsuNarimasu']) {
    const option = runtime.elements.get('destination-list').querySelector(`[data-destination-id="${stationId}"]`);
    option.dispatch('click');
    await waitFor(() => runtime.elements.get('route-display').textContent === `池袋 → ${stationNames.get(stationId)}`
      && !runtime.elements.get('timetable-status').textContent.includes('読み込んでいます'));
    const latest = runtime.calls.at(-1);
    assert.equal(latest.stationId, stationId);
    assert.equal(latest.payloadDestinationId, stationId);
    assert.equal(latest.releaseId, runtime.manifest.releaseId);
    assert.equal(latest.url, runtime.manifest.stations[stationId].url);
    displayed.set(stationId, arrivalTimes(runtime.elements).join('|'));
  }
  assert.equal(runtime.manifestFetches, 1, 'one runtime session keeps its manifest pinned while switching stations');
  assert.equal(new Set(displayed.values()).size, displayed.size,
    'QA fixture renders visibly different existing arrival fields across destinations');
});

test('release-managed station cache hits, evicts at two entries, and refetches the evicted station', async () => {
  const runtime = await createRuntime({ artifact: 'destination-switch', releaseManaged: true });
  const stationCount = stationId => runtime.calls.filter(call => call.stationId === stationId).length;
  for (const stationId of ['Senkawa', 'KotakeMukaihara']) {
    runtime.elements.get('destination-list').querySelector(`[data-destination-id="${stationId}"]`).dispatch('click');
    await waitFor(() => runtime.elements.get('route-display').textContent === `池袋 → ${stationNames.get(stationId)}`
      && !runtime.elements.get('timetable-status').textContent.includes('読み込んでいます'));
  }
  assert.deepEqual(runtime.runtime.cachedDestinationIds, ['Senkawa', 'KotakeMukaihara']);
  const senkawaFetches = stationCount('Senkawa');
  runtime.elements.get('destination-list').querySelector('[data-destination-id="Senkawa"]').dispatch('click');
  await waitFor(() => runtime.elements.get('route-display').textContent === '池袋 → 千川'
    && !runtime.elements.get('timetable-status').textContent.includes('読み込んでいます'));
  assert.equal(stationCount('Senkawa'), senkawaFetches, 'LRU hit avoids a second station request');
  runtime.elements.get('destination-list').querySelector('[data-destination-id="Hikawadai"]').dispatch('click');
  await waitFor(() => runtime.elements.get('route-display').textContent === '池袋 → 氷川台'
    && !runtime.elements.get('timetable-status').textContent.includes('読み込んでいます'));
  assert.equal(stationCount('Hikawadai'), 2, 'evicted station is fetched again through its pinned URL');
  assert.deepEqual(runtime.runtime.cachedDestinationIds, ['Senkawa', 'Hikawadai']);
});

test('release-managed latest destination wins when an older station response arrives late', async () => {
  let finishSenkawa;
  const runtime = await createRuntime({ artifact: 'destination-switch', releaseManaged: true,
    fetchOverride: ({ stationId, response }) => stationId === 'Senkawa'
      ? new Promise(resolve => { finishSenkawa = () => resolve(response); }) : response });
  runtime.elements.get('destination-list').querySelector('[data-destination-id="Senkawa"]').dispatch('click');
  await waitFor(() => typeof finishSenkawa === 'function');
  runtime.elements.get('destination-list').querySelector('[data-destination-id="KotakeMukaihara"]').dispatch('click');
  await waitFor(() => runtime.elements.get('route-display').textContent === '池袋 → 小竹向原'
    && !runtime.elements.get('timetable-status').textContent.includes('読み込んでいます'));
  finishSenkawa();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(runtime.elements.get('route-display').textContent, '池袋 → 小竹向原');
  assert.ok(runtime.runtime.cachedDestinationIds.includes('KotakeMukaihara'));
  assert.ok(!runtime.runtime.cachedDestinationIds.includes('Senkawa'), 'stale response is not admitted to the LRU');
});

test('fixed QA clock remains fixed and advancing QA clock updates current time and countdown', async () => {
  const startAt = Date.parse('2026-10-26T22:05:00+09:00');
  let monotonicMs = 0;
  const fixedClock = createQaClock({ startAt, mode: 'fixed', monotonicNow: () => monotonicMs });
  const fixed = await createRuntime({ nowProvider: fixedClock });
  const fixedTime = fixed.elements.get('clock').textContent;
  const fixedCountdown = cards(fixed.elements)[0].querySelector('.count').textContent;
  monotonicMs += 5000;
  fixed.intervals[0]();
  assert.equal(fixed.elements.get('clock').textContent, fixedTime);
  assert.equal(cards(fixed.elements)[0].querySelector('.count').textContent, fixedCountdown);

  monotonicMs = 0;
  const advancingClock = createQaClock({ startAt, mode: 'advancing', monotonicNow: () => monotonicMs });
  const advancing = await createRuntime({ nowProvider: advancingClock });
  const initialTime = advancing.elements.get('clock').textContent;
  const initialCountdown = cards(advancing.elements)[0].querySelector('.count').textContent;
  monotonicMs += 2100;
  advancing.intervals[0]();
  assert.notEqual(advancing.elements.get('clock').textContent, initialTime);
  assert.notEqual(cards(advancing.elements)[0].querySelector('.count').textContent, initialCountdown);
});

test('fixed morning scenarios prove the 60-minute gate and previous-service-date 25:50 card', async () => {
  const before = await createRuntime({ artifact: 'baseline', instant: '2026-10-27T05:09:59+09:00' });
  assert.equal(cards(before.elements).length, 0);
  assert.equal(before.elements.get('board').children[0].textContent, '本日の終電は終了しました');

  const gate = await createRuntime({ artifact: 'baseline', instant: '2026-10-27T05:10:00+09:00' });
  assert.deepEqual(cardTimes(gate.elements), ['06:10']);
  assert.equal(gate.elements.get('timetable-status').dataset.state, 'ok');

  const overnight = await createRuntime({ artifact: 'baseline', instant: '2026-10-27T01:40:00+09:00' });
  assert.ok(cardTimes(overnight.elements).includes('01:50'));
  assert.match(overnight.elements.get('timetable-status').textContent, /^ダイヤ適用期限 /);
});

test('evening gates, direct terminal, transfer terminal, and full service end render at exact fixed boundaries', async () => {
  const beforeGate = await createRuntime({ instant: '2026-10-26T21:14:59+09:00' });
  assert.equal(cards(beforeGate.elements).length, 0);
  const gate = await createRuntime({ instant: '2026-10-26T21:15:00+09:00' });
  assert.deepEqual(cardTimes(gate.elements), ['22:15', '22:35', '22:45']);

  const directTerminal = await createRuntime({ instant: '2026-10-26T22:59:59+09:00' });
  directTerminal.elements.get('direct-only').checked = true;
  directTerminal.elements.get('direct-only').dispatch('change');
  assert.ok(cards(directTerminal.elements).some(card => card.querySelector('.terminal-badge').textContent === '直通終電'));

  const transferTerminal = await createRuntime({ instant: '2026-10-26T23:04:59+09:00' });
  assert.deepEqual(cardTimes(transferTerminal.elements), ['23:05']);
  assert.equal(cards(transferTerminal.elements)[0].querySelector('.terminal-badge').textContent, '終電');

  const ended = await createRuntime({ instant: '2026-10-26T23:05:01+09:00' });
  assert.equal(cards(ended.elements).length, 0);
  assert.equal(ended.elements.get('board').children[0].textContent, '本日の終電は終了しました');
});

test('QA code stays outside exact legacy and release-managed public artifact trees and deploy workflow', async () => {
  for (const artifactName of ['baseline', 'evening', 'destination-switch']) {
    const directory = path.join(qaRoot, 'artifacts', artifactName);
    const files = await readdir(directory);
    assert.equal(files.length, 17);
    assert.ok(!files.includes('qa_entry.mjs'));
    assert.ok(!files.includes('qa_clock.mjs'));
    const forbidden = /debugNow|perf=1|synthetic-qa-panel|qa_entry\.mjs/;
    for (const filename of files.filter(name => name.endsWith('.js') || name.endsWith('.mjs') || name.endsWith('.html'))) {
      assert.doesNotMatch(await readFile(path.join(directory, filename), 'utf8'), forbidden);
    }
  }
  for (const artifactName of ['baseline', 'evening', 'destination-switch']) {
    const directory = path.join(releaseQaRoot, 'artifacts', artifactName);
    assert.equal(await countTreeFiles(directory), 18);
    assert.ok(!await readFile(path.join(directory, 'index.html'), 'utf8').then(html => html.includes('qa_entry.mjs')));
  }
  const workflow = await readFile(path.join(root, '.github/workflows/synthetic-public-ci.yml'), 'utf8');
  assert.doesNotMatch(workflow, /serve_synthetic_public_qa|qa_entry\.mjs/);
  const wrapper = await readFile(path.join(qaRoot, 'qa_entry.mjs'), 'utf8');
  assert.match(wrapper, /nowProvider,/);
  assert.match(wrapper, /clock-running/);
  assert.match(wrapper, /destination-switch/);
  assert.match(wrapper, /PUBLIC_DATA_SCOPE/);
  execFileSync(process.execPath, ['--check', path.join(qaRoot, 'qa_entry.mjs')]);
  assert.equal(await readFile(path.join(qaRoot, 'qa_clock.mjs'), 'utf8'),
    await readFile(path.join(root, 'scripts', 'synthetic_public_qa_clock.mjs'), 'utf8'));

  const wildcardBind = spawnSync('python3', [qaScript, '--bind', '0.0.0.0'], { cwd: root, encoding: 'utf8' });
  assert.equal(wildcardBind.status, 1);
  assert.match(wildcardBind.stderr, /explicit private LAN IPv4 address/);
});
