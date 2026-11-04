/** Private in-memory DOM harness shared with synthetic tests. No browser/network. */
import assert from 'node:assert/strict';
import { webcrypto, createHash } from 'node:crypto';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let importSequence = 0;
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
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatch('close'); }
  querySelectorAll(selector) {
    const found = [];
    const attr = selector.match(/^\[data-card-id="([^"]+)"\]$/);
    const visit = node => {
      for (const child of node.children ?? []) {
        if (selector.startsWith('.') && child.classList?.contains(selector.slice(1))) found.push(child);
        if (selector === '[data-destination-id]' && child.dataset?.destinationId) found.push(child);
        if (attr && child.dataset?.cardId === attr[1]) found.push(child);
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


function makeEnvironment(files, { destination = 'Hikawadai' } = {}) {
  const ids = ['clock', 'qa-datetime', 'qa-clock-set', 'qa-clock-real', 'qa-generated-at',
    'destination-trigger', 'route-display', 'destination-dialog', 'destination-close', 'destination-list',
    'timetable-status', 'route-coverage', 'mode-line', 'mode-departure', 'direct-only', 'board'];
  const nodes = [];
  const create = tag => { const node = new FakeElement(tag); nodes.push(node); return node; };
  const elements = new Map(ids.map(id => [id, create(id === 'board' ? 'section' : 'div')]));
  const documentRef = {
    getElementById: id => elements.get(id) ?? null,
    createElement: tagName => create(tagName),
    createDocumentFragment: () => Object.assign(create('#fragment'), { isFragment: true }),
  };
  const intervals = new Map();
  let intervalId = 0;
  const local = new Map();
  const fetchAudit = [];
  const windowRef = {
    location: { protocol: 'http:', hostname: '127.0.0.1', origin: 'http://127.0.0.1:8765',
      href: 'http://127.0.0.1:8765/odpt_v2_qa.html' },
    crypto: webcrypto,
    localStorage: { getItem: key => local.get(key) ?? null, setItem: (key, value) => local.set(key, value) },
    setInterval: callback => { intervalId += 1; intervals.set(intervalId, callback); return intervalId; },
    clearInterval: id => intervals.delete(id),
    fetch: async input => {
      const filename = new URL(String(input)).pathname.slice(1);
      const bytes = files.get(filename);
      if (!bytes) return { ok: false, type: 'basic' };
      fetchAudit.push({ filename, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') });
      return { ok: true, type: 'basic', arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) };
    },
  };
  local.set('dotchi-ikebukuro.odpt-v2-qa.destination', destination);
  return { elements, documentRef, windowRef, intervals, local, nodes, fetchAudit };
}

function installEnvironment(env, nowMs) {
  const previous = { document: Object.getOwnPropertyDescriptor(globalThis, 'document'),
    window: Object.getOwnPropertyDescriptor(globalThis, 'window'), now: Date.now };
  Date.now = () => nowMs.value;
  globalThis.document = env.documentRef;
  globalThis.window = env.windowRef;
  return async () => {
    env.intervals.clear();
    for (const node of env.nodes) { node.listeners.clear(); node.children = []; }
    env.nodes.length = 0;
    env.local.clear();
    env.windowRef.fetch = null;
    for (const key of ['document', 'window']) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    Date.now = previous.now;
  };
}

async function startDom(env, nowMs) {
  const restore = installEnvironment(env, nowMs);
  try {
    await import(`${pathToFileURL(path.join(root, '_local_preview/preview_odpt_v2_qa.mjs')).href}?dom-qa=${++importSequence}`);
    await waitFor(() => env.intervals.size > 0 || env.elements.get('timetable-status').dataset.state === 'error');
    return restore;
  } catch (error) { await restore(); throw error; }
}

async function waitFor(predicate) {
  // Resource timeout uses monotonic time; observation time remains fixed.
  const deadline = performance.now() + 5000;
  while (performance.now() < deadline) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail('v2 QA DOM did not finish updating');
}


async function withDom(files, epoch, action, options) {
  const env = makeEnvironment(files, options);
  const clock = { value: epoch };
  const restore = await startDom(env, clock);
  try { return await action(env, clock); }
  finally { await restore(); }
}


const routeLabels = { running: '運行候補あり', not_started: '始発前', ended: '運行終了',
  no_candidates: '到着候補なし', unknown: '状態未確認', data_insufficient: 'データ不足',
  start_unconfirmed: '始発・終電未確認', terminal_unconfirmed: '終電未確認' };
const emptyLabels = { ended: '本日の終電は終了しました',
  terminal_unconfirmed: '終電未確認のため、運行終了とは判定できません',
  start_unconfirmed: '始発時刻を確認できないため、始発前とは判定できません',
  unknown: '運行状態を確認できないため、終電を判定できません',
  no_candidates: '目的地に到着する候補はありません', not_started: '始発前です',
  unavailable: '必要な運行日データがありません' };

function assertBoardDom(env, board, epoch, mode = 'departure', directOnly = false) {
  const node = env.elements.get('board');
  const groups = node.querySelectorAll('.line');
  assert.equal(groups.length, board.groups.length);
  board.groups.forEach((group, index) => {
    const cards = groups[index].querySelectorAll('.train');
    assert.deepEqual(cards.map(c => c.dataset.cardId), group.items.map(i => i.id));
    assert.deepEqual(groups[index].querySelectorAll('.sectionlabel').map(n => n.textContent), group.line ? [group.line] : []);
    group.items.forEach((item, i) => {
      const card = cards[i];
      assert.equal(card.querySelector('.route').textContent, item.line);
      assert.ok(card.classList.contains(`route-${item.routeId}`));
      assert.equal(card.querySelector('.type-label').textContent, item.kind);
      assert.equal(card.querySelector('.destination-label').textContent, `${item.destination}行`);
      assert.equal(card.querySelector('.time-value').textContent, item.departureText);
      assert.equal(card.querySelector('.arrival').textContent, item.arrivalText);
      assert.equal(card.querySelector('.service-date-label').textContent, `運行日 ${item.serviceDate}`);
      const sub = item.transfer ? `${item.transfer.station}で${item.transfer.outgoingRoute}へ乗換・待ち約${Math.round(item.transfer.waitSeconds / 60)}分・接続保証なし` : '直通・乗換なし';
      assert.equal(card.querySelector('.sub').textContent, `${sub}　運行日 ${item.serviceDate}`);
      assert.equal(card.querySelector('.terminal-badge').textContent,
        item.isLastDeparture ? item.terminalBasis === 'direct_only' ? '直通終電' : '終電' : '');
      assert.equal(card.querySelector('.bestmark').textContent, item.isBest ? item.bestLabel : '');
      assert.equal(card.classList.contains('best'), item.isBest);
      const seconds = Math.max(0, Math.ceil((item.departureAtMs - epoch) / 1000));
      assert.equal(card.querySelector('.count').textContent,
        `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`);
      assert.equal(card.querySelector('.count').classList.contains('red'), seconds <= 180);
    });
  });
  const visible = board.groups.flatMap(g => g.items);
  assert.equal(node.querySelectorAll('.train').length, visible.length);
  assert.equal(node.querySelectorAll('.bestmark').filter(n => n.textContent).length, visible.filter(i => i.isBest).length);
  assert.equal(env.elements.get('timetable-status').textContent, board.status);
  const warning = board.serviceState === 'unknown' || Object.values(board.routeStates).some(s =>
    ['unknown','data_insufficient','start_unconfirmed','terminal_unconfirmed'].includes(s.state)) || board.noValidArrival || board.otherUnknownCount > 0;
  assert.equal(env.elements.get('timetable-status').dataset.state, warning ? 'warning' : 'ok');
  const labels = env.elements.get('route-coverage').querySelectorAll('.coverage-state');
  ['6','9'].forEach((route, i) => {
    const state = board.routeStates[`${board.serviceDate}|${route}`]?.state ?? 'unknown';
    assert.equal(labels[i].dataset.state, state);
    assert.equal(labels[i].textContent, `${route === '6' ? '有楽町線' : '副都心線'}: ${routeLabels[state]}`);
  });
  assert.equal(labels.length, 2 + Number(Boolean(board.noValidArrival)) + Number(board.otherUnknownCount > 0) + Number(board.infoCount > 0));
  let extra = 2;
  if (board.noValidArrival) assert.equal(labels[extra++].textContent,
    `no_valid_arrival UNKNOWN ${board.noValidArrivalCount}件・検証済み候補だけを表示対象・両路線の終電未確認`);
  if (board.otherUnknownCount > 0) assert.equal(labels[extra++].textContent,
    `その他UNKNOWN ${board.otherUnknownCount}件・検証済み候補だけを表示対象・両路線の終電未確認`);
  if (board.infoCount > 0) assert.equal(labels[extra++].textContent, `明示通過INFO ${board.infoCount}件（正常扱い）`);
  for (const name of ['line','departure']) {
    assert.equal(env.elements.get(`mode-${name}`).getAttribute('aria-pressed'), String(mode === name));
    assert.equal(env.elements.get(`mode-${name}`).classList.contains('sel'), mode === name);
  }
  if (!board.groups.length) {
    assert.equal(node.querySelector('.empty').textContent, emptyLabels[board.serviceState] ?? '現在から24時間以内に表示できる列車はありません');
    assert.equal(node.querySelector('.empty').getAttribute('role'), 'status');
    assert.equal(node.querySelector('.empty').classList.contains('terminal-ended'), board.serviceState === 'ended');
  }
  assert.equal(env.elements.get('mode-line').getAttribute('aria-pressed'), String(mode === 'line'));
  assert.equal(env.elements.get('mode-departure').classList.contains('sel'), mode === 'departure');
  assert.equal(env.elements.get('direct-only').checked, directOnly);
}


export { makeEnvironment, startDom, waitFor, withDom, assertBoardDom };
