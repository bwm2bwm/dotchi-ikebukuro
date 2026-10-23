import { buildBoard, TOKYO_TIME_ZONE } from './timetable_adapter.mjs';
import { loadTimetablePayload } from './local_preview_payload_loader.mjs';
import { countdownText, earliestVisible, selectPreviewGroups } from './selection.mjs';

const clock = document.getElementById('clock');
const statusEl = document.getElementById('timetable-status');
const boardEl = document.getElementById('board');
const directOnlyEl = document.getElementById('direct-only');
const lineButton = document.getElementById('mode-line');
const departureButton = document.getElementById('mode-departure');
const clockFormatter = new Intl.DateTimeFormat('en-GB', {
  timeZone: TOKYO_TIME_ZONE, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});
let mode = 'line';
let prepared = null;
let loadFailure = null;
let selectedSignature = '';
let perfHistory = [];
let fetchCount = 0;

window.__dotchiPreviewPerf = { history: perfHistory, get fetchCount() { return fetchCount; } };

function setStatus(message, state) {
  if (statusEl.textContent !== message) statusEl.textContent = message;
  statusEl.dataset.state = state;
}

function renderGroups(groups, nowMs) {
  const visible = groups.flatMap(group => group.items);
  const best = earliestVisible(groups);
  const signature = `${mode}|${directOnlyEl.checked}|${visible.map(item => item.id).join(',')}|${best?.id ?? ''}`;
  if (signature !== selectedSignature) {
    const fragment = document.createDocumentFragment();
    for (const group of groups) {
      const section = document.createElement('section');
      section.className = 'line';
      if (group.line) {
        const heading = document.createElement('h2');
        heading.className = 'line-title';
        heading.textContent = `${group.line} · ${group.items.length}本表示`;
        section.appendChild(heading);
      }
      for (const item of group.items) {
        const card = document.createElement('article');
        card.className = `train${item.id === best?.id ? ' best' : ''}`;
        card.style.setProperty('--line-color', item.color);
        card.innerHTML = `<div><div><span class="route"></span><span class="bestmark"></span></div><div class="depart"><span class="departure-text"></span>発 <span class="kind"></span></div><div class="sub"></div></div><div><div class="count"></div><div class="tiny">発車まで</div></div><div><div class="arrival"></div><div class="tiny">氷川台着</div></div>`;
        card.querySelector('.route').textContent = item.line;
        card.querySelector('.bestmark').textContent = item.id === best?.id ? '● 最早着' : '';
        card.querySelector('.departure-text').textContent = item.departureText;
        card.querySelector('.kind').textContent = `${item.kind}・${item.destination}行`;
        card.querySelector('.sub').textContent = item.journeyKind === 'direct'
          ? '直通・乗換なし' : `小竹向原乗換・待ち約${Math.round(item.transfer.waitMinutes)}分`;
        card.querySelector('.arrival').textContent = item.arrivalText ?? '—';
        card.dataset.departureAt = String(item.departureAtMs);
        section.appendChild(card);
      }
      fragment.appendChild(section);
    }
    if (!visible.length) {
      const empty = document.createElement('p');
      empty.className = 'empty';
      empty.textContent = '現在から24時間以内に表示できる列車はありません。';
      fragment.appendChild(empty);
    }
    boardEl.replaceChildren(fragment);
    selectedSignature = signature;
  }
  for (const card of boardEl.querySelectorAll('[data-departure-at]')) {
    const { remaining, label } = countdownText(Number(card.dataset.departureAt), nowMs);
    const counter = card.querySelector('.count');
    counter.textContent = label;
    counter.classList.toggle('red', remaining <= 180);
  }
}

function recordPerf(entry) {
  perfHistory.push(entry);
  if (perfHistory.length > 50) perfHistory.shift();
}

function tick(eventStarted = performance.now()) {
  const nowMs = Date.now();
  clock.textContent = clockFormatter.format(new Date(nowMs));
  const started = performance.now();
  if (loadFailure) {
    setStatus(loadFailure, 'error');
    boardEl.replaceChildren();
    selectedSignature = '';
    recordPerf({ at: nowMs, eventToDomMs: performance.now() - eventStarted, adapterMs: 0, selectionMs: 0, domMs: 0 });
    return;
  }
  try {
    const adapterStarted = performance.now();
    const result = buildBoard(prepared, { nowMs, directOnly: directOnlyEl.checked, mode });
    const adapterMs = performance.now() - adapterStarted;
    const selectionStarted = performance.now();
    const groups = selectPreviewGroups(result, mode);
    const selectionMs = performance.now() - selectionStarted;
    const domStarted = performance.now();
    const state = result.validity === 'valid' ? 'ok' : 'warning';
    setStatus(result.statusMessage, state);
    statusEl.title = result.periodText;
    if (result.validity !== 'valid') {
      selectedSignature = '';
      boardEl.replaceChildren();
    } else {
      renderGroups(groups, nowMs);
    }
    const domMs = performance.now() - domStarted;
    recordPerf({ at: nowMs, eventToDomMs: performance.now() - eventStarted, adapterMs, selectionMs, domMs });
  } catch {
    loadFailure = 'payloadの形式または必須メタデータを確認できません。プレビューを再生成してください。';
    tick(eventStarted);
  }
}

async function load() {
  fetchCount += 1;
  const result = await loadTimetablePayload(fetch);
  prepared = result.prepared;
  loadFailure = result.failure;
  tick();
}

lineButton.addEventListener('click', () => {
  mode = 'line';
  lineButton.setAttribute('aria-pressed', 'true');
  departureButton.setAttribute('aria-pressed', 'false');
  tick();
});
departureButton.addEventListener('click', () => {
  mode = 'departure';
  lineButton.setAttribute('aria-pressed', 'false');
  departureButton.setAttribute('aria-pressed', 'true');
  tick();
});
directOnlyEl.addEventListener('change', () => tick());

load();
setInterval(() => tick(), 1000);
