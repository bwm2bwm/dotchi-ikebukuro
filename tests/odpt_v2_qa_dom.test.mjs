import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { computeV2PublicId, ODPT_V2_QA_FILES, ODPT_V2_QA_STATIONS,
  ODPT_V2_QA_STATE_SCOPE } from '../_local_preview/odpt_v2_qa_adapter.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const serviceDates = ['2026-10-28', '2026-10-29', '2026-10-30'];

class FakeElement {
  constructor(tagName = 'div') {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = new Map();
    this.dataset = {};
    this.attributes = new Map();
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
    this.value = '';
    this.checked = false;
    this.open = false;
    this._text = '';
  }
  get className() { return [...this.classTokens].join(' '); }
  set className(value) { this.classTokens = new Set(String(value).split(/\s+/).filter(Boolean)); }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = value === null ? '' : String(value); this.children = []; }
  addEventListener(name, callback) {
    const callbacks = this.listeners.get(name) ?? [];
    callbacks.push(callback);
    this.listeners.set(name, callbacks);
  }
  dispatch(name) {
    for (const callback of this.listeners.get(name) ?? []) callback({ target: this, currentTarget: this });
  }
  append(...nodes) { nodes.forEach(node => this.appendChild(typeof node === 'string' ? new FakeText(node) : node)); }
  appendChild(node) {
    if (node?.isFragment) { this.children.push(...node.children); node.children = []; }
    else this.children.push(node);
    return node;
  }
  replaceChildren(...nodes) { this.children = []; this._text = ''; this.append(...nodes); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatch('close'); }
  querySelectorAll(selector) {
    const found = [];
    const visit = node => {
      for (const child of node.children ?? []) {
        if (selector.startsWith('.') && child.classList?.contains(selector.slice(1))) found.push(child);
        if (selector === '[data-destination-id]' && child.dataset?.destinationId) found.push(child);
        visit(child);
      }
    };
    visit(this);
    return found;
  }
  querySelector(selector) {
    const match = selector.match(/^\[data-destination-id="([^"]+)"\]$/);
    return match ? this.querySelectorAll('[data-destination-id]')
      .find(node => node.dataset.destinationId === match[1]) ?? null
      : this.querySelectorAll(selector)[0] ?? null;
  }
}

class FakeText {
  constructor(text) { this.textContent = text; this.children = []; }
}

async function makeBundle() {
  const files = new Map();
  const stations = {};
  const candidateFiles = {};
  for (const stationId of Object.keys(ODPT_V2_QA_STATIONS)) {
    const serviceDays = [];
    for (const serviceDate of serviceDates) {
      const departures = [];
      for (const [routeId, departureSeconds, arrivalSeconds] of [
        ['6', 6 * 3600, 6 * 3600 + 20 * 60],
        ['9', 6 * 3600 + 300, 6 * 3600 + 45 * 60],
      ]) {
        const journey = { kind: 'direct', departureServiceSeconds: departureSeconds,
          arrivalServiceSeconds: arrivalSeconds, transfer: null };
        const row = { routeId, destination: 'QA行', displayType: '各駅停車',
          departureServiceSeconds: departureSeconds, primary: journey, directAlternative: journey,
          bestTransferAlternative: null };
        row.id = await computeV2PublicId(stationId, serviceDate, row, webcrypto);
        departures.push(row);
      }
      serviceDays.push({ serviceDate,
        routeCoverage: { '6': { scheduledTripCount: 439, dataState: 'complete' },
          '9': { scheduledTripCount: 500, dataState: 'complete' } }, departures });
    }
    const payload = { schemaVersion: 2, dataScope: 'public-display-v2', generatedAt: '2026-10-29T00:00:00Z',
      timezone: 'Asia/Tokyo', applicationPeriod: null, stationId, originStationId: 'Ikebukuro', serviceDays };
    const bytes = new TextEncoder().encode(JSON.stringify(payload));
    files.set(ODPT_V2_QA_FILES[stationId], bytes);
    candidateFiles[stationId] = { sha256: createHash('sha256').update(bytes).digest('hex'), bytes: bytes.length };
    stations[stationId] = Object.fromEntries(serviceDates.map(serviceDate => [serviceDate, {
      infoCount: 0,
      noValidArrivalCount: stationId === 'Hikawadai' && serviceDate === '2026-10-29' ? 4 : 0,
      otherUnknownCount: 0,
    }]));
  }
  const state = { schemaVersion: 1, dataScope: ODPT_V2_QA_STATE_SCOPE, serviceDates, stations, candidateFiles };
  files.set('_odpt_v2_qa_state.json', new TextEncoder().encode(JSON.stringify(state)));
  return files;
}

function makeEnvironment(files) {
  const ids = ['clock', 'qa-datetime', 'qa-clock-set', 'qa-clock-real', 'qa-generated-at',
    'destination-trigger', 'route-display', 'destination-dialog', 'destination-close', 'destination-list',
    'timetable-status', 'route-coverage', 'mode-line', 'mode-departure', 'direct-only', 'board'];
  const elements = new Map(ids.map(id => [id, new FakeElement(id === 'board' ? 'section' : 'div')]));
  const documentRef = {
    getElementById: id => elements.get(id) ?? null,
    createElement: tagName => new FakeElement(tagName),
    createDocumentFragment: () => Object.assign(new FakeElement('#fragment'), { isFragment: true }),
  };
  const intervals = [];
  const local = new Map();
  const windowRef = {
    location: { protocol: 'http:', hostname: '127.0.0.1', origin: 'http://127.0.0.1:8765',
      href: 'http://127.0.0.1:8765/odpt_v2_qa.html' },
    crypto: webcrypto,
    localStorage: { getItem: key => local.get(key) ?? null, setItem: (key, value) => local.set(key, value) },
    setInterval: callback => { intervals.push(callback); return intervals.length; },
    fetch: async input => {
      const filename = new URL(String(input)).pathname.slice(1);
      const bytes = files.get(filename);
      if (!bytes) return { ok: false, type: 'basic' };
      return { ok: true, type: 'basic', arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) };
    },
  };
  return { elements, documentRef, windowRef, intervals };
}

async function waitFor(predicate) {
  for (let count = 0; count < 100; count += 1) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail('v2 QA DOM did not finish updating');
}

test('v2 QA DOM shows verified cards and UNKNOWN warning, then clears warning on station/date changes', async () => {
  const env = makeEnvironment(await makeBundle());
  const originalNow = Date.now;
  let wallNow = Date.parse('2026-10-29T21:06:00+09:00');
  Date.now = () => wallNow;
  globalThis.document = env.documentRef;
  globalThis.window = env.windowRef;
  try {
    await import(`${pathToFileURL(path.join(root, '_local_preview/preview_odpt_v2_qa.mjs')).href}?dom-qa=${Date.now()}`);
    await waitFor(() => !env.elements.get('timetable-status').textContent.includes('検証しています'));
    env.elements.get('qa-datetime').value = '2026-10-29T05:30';
    env.elements.get('qa-clock-set').dispatch('click');
    assert.equal(env.elements.get('clock').textContent, '05:30:00');
    assert.ok(env.elements.get('board').querySelectorAll('.train').length > 0,
      `${env.elements.get('timetable-status').textContent} | ${env.elements.get('board').textContent}`);
    assert.match(env.elements.get('timetable-status').textContent, /両路線の終電は未確認/);
    assert.equal(env.elements.get('timetable-status').dataset.state, 'warning');
    assert.match(env.elements.get('route-coverage').textContent, /UNKNOWN 4件.*検証済み候補だけを表示対象/);
    assert.ok(env.elements.get('board').querySelectorAll('.bestmark').some(node =>
      node.textContent === '● 表示候補内の最早着'));
    assert.equal(env.elements.get('board').querySelector('.count').textContent, '30:00');
    wallNow += 1000;
    env.intervals[0]();
    assert.equal(env.elements.get('clock').textContent, '05:30:01');
    assert.equal(env.elements.get('board').querySelector('.count').textContent, '29:59');

    env.elements.get('qa-datetime').value = '2026-02-29T06:00';
    env.elements.get('qa-clock-set').dispatch('click');
    assert.equal(env.elements.get('clock').textContent, '05:30:01');
    assert.match(env.elements.get('timetable-status').textContent, /仮想日時が不正です/);
    assert.equal(env.elements.get('timetable-status').dataset.state, 'error');
    wallNow += 5000;
    env.intervals[0]();
    assert.equal(env.elements.get('clock').textContent, '05:30:06');
    assert.match(env.elements.get('timetable-status').textContent, /仮想日時が不正です/);

    env.elements.get('qa-clock-real').dispatch('click');
    assert.equal(env.elements.get('clock').textContent, '21:06:06');
    assert.equal(env.elements.get('qa-datetime').value, '2026-10-29T21:06:06');
    assert.equal(env.elements.get('timetable-status').dataset.state, 'warning');
    assert.equal(env.elements.get('board').querySelectorAll('.train').length, 0,
      'resetting to 21:06 returns to the real-time candidate selection');
    env.elements.get('qa-datetime').value = '2026-10-29T05:30';
    env.elements.get('qa-clock-set').dispatch('click');
    assert.equal(env.elements.get('clock').textContent, '05:30:00');

    env.elements.get('destination-list').querySelector('[data-destination-id="Senkawa"]').dispatch('click');
    await waitFor(() => env.elements.get('route-display').textContent === '池袋 → 千川'
      && !env.elements.get('timetable-status').textContent.includes('検証しています'));
    assert.ok(env.elements.get('board').querySelectorAll('.train').length > 0);
    assert.doesNotMatch(env.elements.get('timetable-status').textContent, /UNKNOWN|未確認/);
    assert.doesNotMatch(env.elements.get('route-coverage').textContent, /UNKNOWN/);

    env.elements.get('destination-list').querySelector('[data-destination-id="Hikawadai"]').dispatch('click');
    await waitFor(() => env.elements.get('route-display').textContent === '池袋 → 氷川台'
      && env.elements.get('route-coverage').textContent.includes('UNKNOWN 4件'));
    env.elements.get('qa-datetime').value = '2026-10-30T05:30:00';
    env.elements.get('qa-clock-set').dispatch('click');
    assert.equal(env.elements.get('board').querySelectorAll('.train').length, 0);
    assert.match(env.elements.get('timetable-status').textContent, /必要な運行日データがありません: 2026-10-31/);
    assert.doesNotMatch(env.elements.get('timetable-status').textContent, /UNKNOWN|未確認/);
    assert.doesNotMatch(env.elements.get('route-coverage').textContent, /UNKNOWN/);
  } finally {
    Date.now = originalNow;
    delete globalThis.document;
    delete globalThis.window;
  }
});
