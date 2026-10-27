import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { DESTINATION_PAYLOADS } from '../scripts/local_preview_payload_loader.mjs';
import { PUBLIC_DATA_SCOPE } from '../scripts/timetable_adapter.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const qaScript = path.join(root, 'scripts', 'serve_synthetic_public_qa.py');
const qaRoot = await mkdtemp('/private/tmp/dotchi-public-qa-dom-test-');
await rm(qaRoot, { recursive: true, force: true });
execFileSync('python3', ['-B', qaScript, '--prepare-only', '--output', qaRoot], {
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

async function createRuntime({ artifact = 'evening', instant = '2026-10-26T22:05:00+09:00' } = {}) {
  const { elements, documentRef } = makeDom();
  const calls = [];
  const windowRef = {
    setInterval() { return 1; },
    fetch: async filename => {
      const stationId = stationFiles.get(path.basename(filename));
      assert.ok(stationId, `unexpected payload request: ${filename}`);
      const filePath = path.join(qaRoot, 'artifacts', artifact, path.basename(filename));
      const text = await readFile(filePath, 'utf8');
      const payload = JSON.parse(text);
      calls.push({ stationId, payloadDestinationId: payload.serviceDays[0].destinationStationId });
      return { ok: true, headers: { get: () => null }, text: async () => text };
    },
  };
  const runtimeModule = await import(pathToFileURL(path.join(qaRoot, 'artifacts', artifact, 'preview_core.mjs')).href);
  const runtime = runtimeModule.createPreviewRuntime({
    expectedProfile: PUBLIC_DATA_SCOPE,
    cacheMode: 'default',
    nowProvider: () => Date.parse(instant),
    documentRef,
    windowRef,
  });
  await waitFor(() => !elements.get('timetable-status').textContent.includes('読み込んでいます'));
  return { runtime, elements, documentRef, calls };
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

function fire(elements, id, eventName) { elements.get(id).dispatch(eventName); }

test.after(async () => rm(qaRoot, { recursive: true, force: true }));

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
    assert.deepEqual(latest, { stationId, payloadDestinationId: stationId });
  }
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

test('QA code stays outside both exact 17-file public artifacts and deploy workflow', async () => {
  for (const artifactName of ['baseline', 'evening']) {
    const directory = path.join(qaRoot, 'artifacts', artifactName);
    const files = await readdir(directory);
    assert.equal(files.length, 17);
    assert.ok(!files.includes('qa_entry.mjs'));
    const forbidden = /debugNow|perf=1|synthetic-qa-panel|qa_entry\.mjs/;
    for (const filename of files.filter(name => name.endsWith('.js') || name.endsWith('.mjs') || name.endsWith('.html'))) {
      assert.doesNotMatch(await readFile(path.join(directory, filename), 'utf8'), forbidden);
    }
  }
  const workflow = await readFile(path.join(root, '.github/workflows/synthetic-public-ci.yml'), 'utf8');
  assert.doesNotMatch(workflow, /serve_synthetic_public_qa|qa_entry\.mjs/);
  const wrapper = await readFile(path.join(qaRoot, 'qa_entry.mjs'), 'utf8');
  assert.match(wrapper, /nowProvider: \(\) => fixedNow/);
  assert.match(wrapper, /PUBLIC_DATA_SCOPE/);
  execFileSync(process.execPath, ['--check', path.join(qaRoot, 'qa_entry.mjs')]);

  const wildcardBind = spawnSync('python3', [qaScript, '--bind', '0.0.0.0'], { cwd: root, encoding: 'utf8' });
  assert.equal(wildcardBind.status, 1);
  assert.match(wildcardBind.stderr, /explicit private LAN IPv4 address/);
});
