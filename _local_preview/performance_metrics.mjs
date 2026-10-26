/** Opt-in, in-memory timing helpers for the local timetable preview. */
export const PERFORMANCE_HISTORY_LIMIT = 10;

export function isPerformanceMode(search) {
  try {
    return new URLSearchParams(search).get('perf') === '1';
  } catch {
    return false;
  }
}

export function beginSwitchMeasurement(destinationName, startedAt = performance.now()) {
  return { destinationName, startedAt, boardMs: null, selectionMs: null };
}

function elapsedValue(value, cacheHit) {
  if (cacheHit) return 0;
  return Number.isFinite(value) && value >= 0 ? value : null;
}

export function finishSwitchMeasurement(measurement, {
  timings = null,
  completedAt = performance.now(),
  renderStartedAt = null,
  outcome = 'shown',
  error = null,
} = {}) {
  const cacheHit = timings?.cacheHit === true;
  const fetchMs = elapsedValue(timings?.fetchMs, cacheHit);
  const bodyReadMs = elapsedValue(timings?.bodyReadMs, cacheHit);
  const networkValues = [fetchMs, bodyReadMs].filter(Number.isFinite);
  return {
    destinationName: measurement.destinationName,
    startedAt: measurement.startedAt,
    outcome,
    totalMs: outcome === 'superseded' ? null : Math.max(0, completedAt - measurement.startedAt),
    networkMs: cacheHit ? 0 : networkValues.length ? networkValues.reduce((sum, value) => sum + value, 0) : null,
    fetchMs,
    bodyReadMs,
    jsonParseMs: elapsedValue(timings?.jsonParseMs, cacheHit),
    prepareMs: elapsedValue(timings?.adapterMs, cacheHit),
    boardMs: outcome === 'superseded' ? null : elapsedValue(measurement.boardMs, false),
    selectionMs: outcome === 'superseded' ? null : elapsedValue(measurement.selectionMs, false),
    renderMs: outcome === 'superseded' || !Number.isFinite(renderStartedAt)
      ? null : Math.max(0, completedAt - renderStartedAt),
    cacheHit,
    payloadBytes: cacheHit || !Number.isFinite(timings?.payloadBytes) ? null : timings.payloadBytes,
    error: typeof error === 'string' && error ? error : null,
  };
}

export function appendSwitchMeasurement(history, record, limit = PERFORMANCE_HISTORY_LIMIT) {
  if (!Array.isArray(history)) throw new TypeError('history must be an array');
  if (!Number.isInteger(limit) || limit < 1) throw new TypeError('history limit must be positive');
  return [...history, record]
    .sort((left, right) => (left.startedAt ?? 0) - (right.startedAt ?? 0))
    .slice(-limit);
}

function duration(value) {
  return Number.isFinite(value) ? `${value.toFixed(1)} ms` : '未実行';
}

function outcomeLabel(outcome) {
  if (outcome === 'superseded') return '別駅へ切替済み';
  return outcome;
}

export function formatSwitchMeasurements(history) {
  if (!history.length) return '目的地を切り替えると、ここに結果が表示されます。';
  return [
    '目的地切替計測（最新が先頭）',
    ...[...history].reverse().flatMap((entry, index) => [
      `${index + 1}. ${entry.destinationName} — ${outcomeLabel(entry.outcome)}`,
      `総時間 ${duration(entry.totalMs)} / Network ${duration(entry.networkMs)} (fetch ${duration(entry.fetchMs)} + body ${duration(entry.bodyReadMs)}) / cache ${entry.cacheHit ? 'HIT' : 'MISS'} / payload ${Number.isFinite(entry.payloadBytes) ? `${entry.payloadBytes} B` : '—'}`,
      `JSON ${duration(entry.jsonParseMs)} / 準備 ${duration(entry.prepareMs)} / board ${duration(entry.boardMs)} / 選択 ${duration(entry.selectionMs)} / 描画 ${duration(entry.renderMs)}`,
      ...(entry.error ? [`エラー: ${entry.error}`] : []),
    ]),
  ].join('\n');
}
