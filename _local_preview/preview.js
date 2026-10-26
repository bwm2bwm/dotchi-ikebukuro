import { buildBoard, TOKYO_TIME_ZONE } from './timetable_adapter.mjs';
import { createLatestDestinationLoader, createPreparedPayloadCache, loadTimetablePayload,
  readSavedDestinationId, saveDestinationId, readSavedDisplayMode, saveDisplayMode,
  DESTINATION_PAYLOADS } from './local_preview_payload_loader.mjs';
import { countdownText, earliestVisible, selectPreviewGroups } from './selection.mjs';
import { emptyBoardText, terminalBadgeText } from './terminal_ui.mjs';
import { effectiveNowMs, parseVirtualNow } from './virtual_now.mjs';
import { appendSwitchMeasurement, beginSwitchMeasurement, finishSwitchMeasurement,
  formatSwitchMeasurements, isPerformanceMode, PERFORMANCE_HISTORY_LIMIT } from './performance_metrics.mjs';

const clock = document.getElementById('clock');
const debugNowBanner = document.getElementById('debug-now-banner');
const virtualNow = parseVirtualNow(window.location.search);
const performanceMode = isPerformanceMode(window.location.search);
const performancePanel = document.getElementById('performance-panel');
const performanceLatest = document.getElementById('performance-latest');
const performanceHistoryField = document.getElementById('performance-history');
const performanceCopy = document.getElementById('performance-copy');
const performanceCopyStatus = document.getElementById('performance-copy-status');
const statusEl = document.getElementById('timetable-status');
const metadataEl = document.getElementById('payload-metadata');
const boardEl = document.getElementById('board');
const destinationTrigger = document.getElementById('destination-trigger');
const routeDisplay = document.getElementById('route-display');
const destinationDialog = document.getElementById('destination-dialog');
const destinationClose = document.getElementById('destination-close');
const destinationList = document.getElementById('destination-list');
const directOnlyEl = document.getElementById('direct-only');
const lineButton = document.getElementById('mode-line');
const departureButton = document.getElementById('mode-departure');
const DESTINATIONS = Object.freeze([
  { id: 'Kanamecho', name: '要町' },
  { id: 'Senkawa', name: '千川' },
  { id: 'KotakeMukaihara', name: '小竹向原' },
  { id: 'Hikawadai', name: '氷川台' },
  { id: 'Heiwadai', name: '平和台' },
  { id: 'ChikatetsuAkatsuka', name: '地下鉄赤塚' },
  { id: 'ChikatetsuNarimasu', name: '地下鉄成増' },
  { id: 'Wakoshi', name: '和光市' },
]);
const clockFormatter = new Intl.DateTimeFormat('en-GB', {
  timeZone: TOKYO_TIME_ZONE, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});
const metadataFormatter = new Intl.DateTimeFormat('ja-JP', {
  timeZone: TOKYO_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});
let mode = readSavedDisplayMode();
let selectedDestinationId = readSavedDestinationId();
let prepared = null;
let loadFailure = null;
let loading = true;
const preparedPayloadCache = createPreparedPayloadCache(2);
const loadLatestDestination = createLatestDestinationLoader(async destinationId => {
  const cached = preparedPayloadCache.get(destinationId);
  if (cached) {
    const cacheStarted = performance.now();
    return { prepared: cached, failure: null, timings: {
      fetchMs: 0, bodyReadMs: 0, jsonParseMs: 0, adapterMs: 0,
      totalMs: performance.now() - cacheStarted,
      payloadBytes: null, cacheHit: true,
    } };
  }
  if (Object.hasOwn(DESTINATION_PAYLOADS, destinationId)) fetchCount += 1;
  return loadTimetablePayload(destinationId, fetch);
});
let selectedSignature = '';
let perfHistory = [];
let loadPerfHistory = [];
let switchPerfHistory = [];
let latestPerformanceRequestId = 0;
let fetchCount = 0;
let metadataSignature = '';

window.__dotchiPreviewPerf = {
  history: perfHistory,
  loadHistory: loadPerfHistory,
  get fetchCount() { return fetchCount; },
  get cachedDestinationIds() { return preparedPayloadCache.keys(); },
  get switchHistory() { return switchPerfHistory; },
};

if (performanceMode) performancePanel.hidden = false;

function addSwitchMeasurement(record) {
  switchPerfHistory = appendSwitchMeasurement(switchPerfHistory, record, PERFORMANCE_HISTORY_LIMIT);
  const latest = switchPerfHistory.at(-1);
  const outcome = latest.outcome === 'superseded' ? '別駅へ切替済み' : latest.outcome;
  const duration = value => Number.isFinite(value) ? `${value.toFixed(1)} ms` : '未実行';
  performanceLatest.textContent = `${latest.destinationName}：${outcome}／総時間 ${duration(latest.totalMs)}／Network ${duration(latest.networkMs)}（fetch ${duration(latest.fetchMs)}＋本文 ${duration(latest.bodyReadMs)}）／cache ${latest.cacheHit ? 'HIT' : 'MISS'}`;
  performanceHistoryField.value = formatSwitchMeasurements(switchPerfHistory);
  performanceHistoryField.scrollTop = 0;
}

function finishMeasurementAfterRender(measurement, renderStartedAt, outcome, error = null) {
  if (!performanceMode || !measurement) return;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const completedAt = performance.now();
    const superseded = measurement.requestId !== latestPerformanceRequestId;
    addSwitchMeasurement(finishSwitchMeasurement(measurement, {
      timings: measurement.timings,
      completedAt,
      renderStartedAt: superseded ? null : renderStartedAt,
      outcome: superseded ? 'superseded' : outcome,
      error: superseded ? null : error,
    }));
  }));
}

function setStatus(message, state) {
  if (statusEl.textContent !== message) statusEl.textContent = message;
  statusEl.dataset.state = state;
}

function updateModeButtons() {
  const lineSelected = mode === 'line';
  lineButton.classList.toggle('sel', lineSelected);
  departureButton.classList.toggle('sel', !lineSelected);
  lineButton.setAttribute('aria-pressed', String(lineSelected));
  departureButton.setAttribute('aria-pressed', String(!lineSelected));
}

if (performanceMode) {
  performanceCopy.addEventListener('click', async () => {
    const value = performanceHistoryField.value;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(value);
      performanceCopyStatus.textContent = '計測履歴をコピーしました。';
    } catch {
      performanceHistoryField.focus();
      performanceHistoryField.select();
      let copied = false;
      try { copied = document.execCommand('copy'); } catch { /* keep the selection for manual copy */ }
      performanceCopyStatus.textContent = copied
        ? '計測履歴をコピーしました。'
        : 'テキストを選択しました。長押しメニューからコピーしてください。';
    }
  });
}

function selectedDestination() {
  return DESTINATIONS.find(destination => destination.id === selectedDestinationId) ?? null;
}

function renderDestinationOptions() {
  const fragment = document.createDocumentFragment();
  for (const [index, destination] of DESTINATIONS.entries()) {
    const item = document.createElement('li');
    const button = document.createElement('button');
    button.className = 'destination-option';
    button.type = 'button';
    button.dataset.destinationId = destination.id;
    button.setAttribute('aria-pressed', String(destination.id === selectedDestinationId));
    button.setAttribute('aria-posinset', String(index + 1));
    button.setAttribute('aria-setsize', String(DESTINATIONS.length));
    const label = document.createElement('span');
    label.textContent = destination.name;
    const state = document.createElement('span');
    state.className = 'destination-option-state';
    state.textContent = destination.id === selectedDestinationId ? '選択中' : '';
    button.append(label, state);
    button.addEventListener('click', () => {
      const changed = selectedDestinationId !== destination.id;
      const measurement = changed && performanceMode
        ? beginSwitchMeasurement(destination.name, performance.now()) : null;
      if (measurement) measurement.requestId = ++latestPerformanceRequestId;
      saveDestinationId(destination.id);
      if (changed) loadDestination(destination.id, measurement);
      destinationDialog.close();
      if (!changed) destinationTrigger.focus({ preventScroll: true });
    });
    item.appendChild(button);
    fragment.appendChild(item);
  }
  destinationList.replaceChildren(fragment);
}

function updateDestinationLabel() {
  const destination = selectedDestination();
  routeDisplay.textContent = destination ? `池袋 → ${destination.name}` : '池袋 → 目的地不明';
  renderDestinationOptions();
}

function displayTimestamp(value) {
  return value ? metadataFormatter.format(new Date(value)) : '未取得';
}

function renderMetadata(diagnostics) {
  if (!diagnostics) return;
  const values = [
    `${displayTimestamp(diagnostics.applicationStartsAt)} 〜 ${displayTimestamp(diagnostics.applicationEndsAt)}（終了日時は含まない）`,
    displayTimestamp(diagnostics.generatedAt),
    `${diagnostics.feedValidFrom} 〜 ${diagnostics.feedValidThrough}（両日を含む）`,
    displayTimestamp(diagnostics.gtfsUpdatedAt),
    displayTimestamp(diagnostics.odptUpdatedAt),
    displayTimestamp(diagnostics.webAppBuiltAt),
  ];
  const signature = values.join('|');
  if (signature === metadataSignature) return;
  metadataSignature = signature;
  [
    'meta-application-period', 'meta-generated-at', 'meta-feed-period',
    'meta-gtfs-updated', 'meta-odpt-updated', 'meta-webapp-built',
  ].forEach((id, index) => { document.getElementById(id).textContent = values[index]; });
  metadataEl.hidden = false;
}

function typeStyle(item) {
  if (item.kind === 'Fライナー') return 'type-brand';
  if (item.kind === '急行' || item.kind === '通勤急行') return 'type-express';
  if (item.typeSource === 'gtfs_stop_pattern') return 'type-supplement';
  if (item.typeSource === 'official_route_rule') return 'type-normal';
  if (item.typeSource === 'unknown') return 'type-unknown';
  return 'type-normal';
}

function renderGroups(groups, nowMs, serviceState) {
  const visible = groups.flatMap(group => group.items);
  const best = earliestVisible(groups);
  const signature = `${mode}|${directOnlyEl.checked}|${serviceState}|${visible.map(item => `${item.id}:${item.isLastDeparture === true}:${item.terminalBasis ?? ''}`).join(',')}|${best?.id ?? ''}`;
  if (signature !== selectedSignature) {
    const fragment = document.createDocumentFragment();
    if (serviceState !== 'ended') {
      for (const group of groups) {
        const section = document.createElement('section');
        section.className = 'line';
        for (const item of group.items) {
          const card = document.createElement('article');
          card.className = `train${item.id === best?.id ? ' best' : ''}`;
          card.style.setProperty('--line-color', item.color);
          card.innerHTML = `<div class="primary"><div class="train-head"><span class="route"></span><span class="bestmark"></span></div><div class="depart"><span class="departure-text time-value"></span><span class="depart-suffix">発</span><span class="type-destination"><span class="type-label"></span><span class="destination-label"></span><span class="terminal-badge"></span></span></div><div class="sub"></div></div><div class="countwrap"><div class="minitxt">発車まで</div><div class="count"></div></div><div class="arrival-wrap"><div class="minitxt arrival-caption">到着</div><div class="arrival time-value"></div></div>`;
          card.querySelector('.route').textContent = item.line;
          card.querySelector('.bestmark').textContent = item.id === best?.id ? '● 最早着' : '';
          card.querySelector('.departure-text').textContent = item.departureText;
          const typeLabel = card.querySelector('.type-label');
          typeLabel.textContent = item.kind;
          typeLabel.className = `type-label ${typeStyle(item)}`;
          typeLabel.dataset.typeSource = item.typeSource;
          card.querySelector('.destination-label').textContent = `${item.destination}行`;
          card.querySelector('.terminal-badge').textContent = terminalBadgeText(item);
          card.querySelector('.sub').textContent = item.journeyKind === 'direct'
            ? '直通・乗換なし' : `小竹向原乗換・待ち約${Math.round(item.transfer.waitMinutes)}分`;
          card.querySelector('.arrival').textContent = item.arrivalText ?? '—';
          card.querySelector('.arrival-caption').textContent = '到着';
          card.dataset.departureAt = String(item.departureAtMs);
          section.appendChild(card);
        }
        fragment.appendChild(section);
      }
    }
    if (!visible.length || serviceState === 'ended') {
      const empty = document.createElement('p');
      empty.className = serviceState === 'ended' ? 'empty terminal-ended' : 'empty';
      empty.setAttribute('role', 'status');
      empty.textContent = emptyBoardText(serviceState);
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

function recordLoadPerf(entry) {
  loadPerfHistory.push(entry);
  if (loadPerfHistory.length > 50) loadPerfHistory.shift();
}

function tick(eventStarted = performance.now(), measurement = null) {
  const nowMs = effectiveNowMs(virtualNow);
  clock.textContent = clockFormatter.format(new Date(nowMs));
  const started = performance.now();
  if (loadFailure) {
    const renderStartedAt = measurement ? performance.now() : null;
    setStatus(loadFailure, 'error');
    boardEl.replaceChildren();
    selectedSignature = '';
    recordPerf({ at: nowMs, eventToDomMs: performance.now() - eventStarted, adapterMs: 0, selectionMs: 0, domMs: 0 });
    if (measurement) finishMeasurementAfterRender(measurement, renderStartedAt, '読込エラー', loadFailure);
    return;
  }
  if (loading) {
    setStatus(`${selectedDestination()?.name ?? '目的地'}の時刻表を読み込んでいます…`, 'warning');
    boardEl.replaceChildren();
    selectedSignature = '';
    recordPerf({ at: nowMs, eventToDomMs: performance.now() - eventStarted, adapterMs: 0, selectionMs: 0, domMs: 0 });
    return;
  }
  let adapterStartedAt = null;
  try {
    const adapterStarted = performance.now();
    adapterStartedAt = adapterStarted;
    const result = buildBoard(prepared, { nowMs, directOnly: directOnlyEl.checked, mode });
    const adapterMs = performance.now() - adapterStarted;
    if (measurement) measurement.boardMs = adapterMs;
    const selectionStarted = performance.now();
    const groups = selectPreviewGroups(result, mode);
    const selectionMs = performance.now() - selectionStarted;
    if (measurement) measurement.selectionMs = selectionMs;
    const domStarted = performance.now();
    const state = result.validity === 'valid' ? 'ok' : 'warning';
    setStatus(result.statusMessage, state);
    statusEl.title = result.periodText;
    renderMetadata(result.diagnostics);
    if (result.validity !== 'valid') {
      selectedSignature = '';
      boardEl.replaceChildren();
    } else {
      renderGroups(groups, nowMs, result.serviceState);
    }
    const domMs = performance.now() - domStarted;
    recordPerf({ at: nowMs, eventToDomMs: performance.now() - eventStarted, adapterMs, selectionMs, domMs });
    const outcome = result.validity === 'valid' ? '表示完了' : '表示停止';
    const message = result.validity === 'valid' ? null : result.statusMessage;
    if (measurement) finishMeasurementAfterRender(measurement, domStarted, outcome, message);
  } catch {
    if (measurement && adapterStartedAt !== null && measurement.boardMs === null) {
      measurement.boardMs = performance.now() - adapterStartedAt;
    }
    loadFailure = 'payloadの形式または必須メタデータを確認できません。プレビューを再生成してください。';
    tick(eventStarted, measurement);
  }
}

async function loadDestination(destinationId, measurement = null) {
  if (!DESTINATIONS.some(destination => destination.id === destinationId)) {
    void loadLatestDestination(destinationId);
    selectedDestinationId = destinationId;
    prepared = null;
    loading = false;
    loadFailure = '選択した目的地IDが不正です。氷川台へ戻ってください。';
    updateDestinationLabel();
    metadataEl.hidden = true;
    tick();
    return;
  }
  selectedDestinationId = destinationId;
  updateDestinationLabel();
  prepared = null;
  loadFailure = null;
  loading = true;
  selectedSignature = '';
  metadataSignature = '';
  metadataEl.hidden = true;
  boardEl.replaceChildren();
  tick();
  const result = await loadLatestDestination(destinationId);
  recordLoadPerf({
    at: Date.now(), destinationStationId: destinationId, stale: result.stale,
    ...(result.timings ?? {}),
  });
  if (measurement) measurement.timings = result.timings ?? null;
  if (result.stale) {
    if (measurement) {
      addSwitchMeasurement(finishSwitchMeasurement(measurement, {
        timings: measurement.timings,
        completedAt: performance.now(),
        outcome: 'superseded',
      }));
    }
    return;
  }
  prepared = result.prepared;
  loadFailure = result.failure;
  loading = false;
  if (prepared) preparedPayloadCache.set(destinationId, prepared);
  tick(measurement?.startedAt ?? performance.now(), measurement);
}

destinationTrigger.addEventListener('click', () => {
  if (destinationDialog.open) return;
  destinationDialog.showModal();
  document.body.classList.add('destination-modal-open');
  destinationList.querySelector(`[data-destination-id="${selectedDestinationId}"]`)?.focus({ preventScroll: true });
});
destinationClose.addEventListener('click', () => destinationDialog.close());
destinationDialog.addEventListener('close', () => {
  document.body.classList.remove('destination-modal-open');
  destinationTrigger.focus({ preventScroll: true });
});
destinationDialog.addEventListener('click', event => {
  if (event.target === destinationDialog) destinationDialog.close();
});
destinationDialog.addEventListener('keydown', event => {
  const options = [...destinationList.querySelectorAll('.destination-option')];
  const currentIndex = options.indexOf(document.activeElement);
  if (currentIndex < 0 || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const nextIndex = event.key === 'Home' ? 0
    : event.key === 'End' ? options.length - 1
      : (currentIndex + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
  options[nextIndex].focus();
});

lineButton.addEventListener('click', () => {
  mode = 'line';
  saveDisplayMode(mode);
  updateModeButtons();
  tick();
});
departureButton.addEventListener('click', () => {
  mode = 'departure';
  saveDisplayMode(mode);
  updateModeButtons();
  tick();
});
directOnlyEl.addEventListener('change', () => tick());

updateModeButtons();
updateDestinationLabel();
if (virtualNow) {
  debugNowBanner.textContent = `テスト日時：${virtualNow.displayText}`;
  debugNowBanner.hidden = false;
}
loadDestination(selectedDestinationId);
setInterval(() => tick(), 1000);
