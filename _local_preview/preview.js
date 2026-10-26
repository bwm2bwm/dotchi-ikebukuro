import { createPreviewRuntime } from './preview_core.mjs';
import { LOCAL_DATA_SCOPE } from './timetable_adapter.mjs';
import { effectiveNowMs, parseVirtualNow } from './virtual_now.mjs';
import { appendSwitchMeasurement, beginSwitchMeasurement, finishSwitchMeasurement,
  formatSwitchMeasurements, isPerformanceMode, PERFORMANCE_HISTORY_LIMIT } from './performance_metrics.mjs';

const virtualNow = parseVirtualNow(window.location.search);
const performanceMode = isPerformanceMode(window.location.search);
const debugNowBanner = document.getElementById('debug-now-banner');
const performancePanel = document.getElementById('performance-panel');
const performanceLatest = document.getElementById('performance-latest');
const performanceHistoryField = document.getElementById('performance-history');
const performanceCopy = document.getElementById('performance-copy');
const performanceCopyStatus = document.getElementById('performance-copy-status');
const requiredLocalElements = [['debug-now-banner', debugNowBanner]];
if (performanceMode) requiredLocalElements.push(
  ['performance-panel', performancePanel], ['performance-latest', performanceLatest],
  ['performance-history', performanceHistoryField], ['performance-copy', performanceCopy],
  ['performance-copy-status', performanceCopyStatus],
);
const missingLocalElements = requiredLocalElements.filter(([, element]) => !element);
if (missingLocalElements.length) {
  throw new Error(`local preview DOM is missing required elements: ${missingLocalElements.map(([id]) => id).join(', ')}`);
}
let perfHistory = [];
let loadPerfHistory = [];
let switchPerfHistory = [];
let latestPerformanceRequestId = 0;

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
    const superseded = measurement.requestId !== latestPerformanceRequestId;
    addSwitchMeasurement(finishSwitchMeasurement(measurement, {
      timings: measurement.timings,
      completedAt: performance.now(),
      renderStartedAt: superseded ? null : renderStartedAt,
      outcome: superseded ? 'superseded' : outcome,
      error: superseded ? null : error,
    }));
  }));
}

if (performanceMode) {
  performancePanel.hidden = false;
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

if (virtualNow) {
  debugNowBanner.textContent = `テスト日時：${virtualNow.displayText}`;
  debugNowBanner.hidden = false;
}

let runtime = null;
try {
  runtime = createPreviewRuntime({
    expectedProfile: LOCAL_DATA_SCOPE,
    cacheMode: 'no-store',
    nowProvider: () => effectiveNowMs(virtualNow),
    hooks: {
      beginSwitch(destinationName) {
        if (!performanceMode) return null;
        const measurement = beginSwitchMeasurement(destinationName, performance.now());
        measurement.requestId = ++latestPerformanceRequestId;
        return measurement;
      },
      finishAfterRender: finishMeasurementAfterRender,
      onStale(measurement, timings) {
        addSwitchMeasurement(finishSwitchMeasurement(measurement, {
          timings, completedAt: performance.now(), outcome: 'superseded',
        }));
      },
      onTick(entry) {
        perfHistory.push(entry);
        if (perfHistory.length > 50) perfHistory.shift();
      },
      onLoad(entry) {
        loadPerfHistory.push(entry);
        if (loadPerfHistory.length > 50) loadPerfHistory.shift();
      },
    },
  });
} catch (error) {
  const status = document.getElementById('timetable-status');
  if (status) {
    status.textContent = 'プレビューを初期化できませんでした。ページを再読み込みしてください。';
    status.dataset.state = 'error';
  }
  console.error('local preview runtime initialization failed', error);
}

window.__dotchiPreviewPerf = {
  history: perfHistory,
  loadHistory: loadPerfHistory,
  get fetchCount() { return runtime?.fetchCount ?? 0; },
  get cachedDestinationIds() { return runtime?.cachedDestinationIds ?? []; },
  get switchHistory() { return switchPerfHistory; },
};
