import test from 'node:test';
import assert from 'node:assert/strict';

import { appendSwitchMeasurement, beginSwitchMeasurement, finishSwitchMeasurement,
  formatSwitchMeasurements, isPerformanceMode } from '../_local_preview/performance_metrics.mjs';
import { parseVirtualNow } from '../_local_preview/virtual_now.mjs';

test('performance mode requires perf=1 and can coexist with debugNow', () => {
  assert.equal(isPerformanceMode('?perf=1'), true);
  const query = '?perf=1&debugNow=2026-10-27T00%3A08';
  assert.equal(isPerformanceMode(query), true);
  assert.ok(parseVirtualNow(query));
  for (const value of ['', '?perf=0', '?perf=true', '?debugNow=2026-10-27T00%3A08']) {
    assert.equal(isPerformanceMode(value), false, value);
  }
});

test('cold switch metrics map non-overlapping loader and render stages', () => {
  const measurement = beginSwitchMeasurement('平和台', 10);
  measurement.boardMs = 12;
  measurement.selectionMs = 1;
  const record = finishSwitchMeasurement(measurement, {
    timings: { cacheHit: false, fetchMs: 5, bodyReadMs: 7, jsonParseMs: 3,
      adapterMs: 11, payloadBytes: 1234 },
    completedAt: 80,
    renderStartedAt: 50,
  });
  assert.deepEqual(record, {
    destinationName: '平和台', startedAt: 10, outcome: 'shown', totalMs: 70,
    networkMs: 12, fetchMs: 5, bodyReadMs: 7, jsonParseMs: 3, prepareMs: 11, boardMs: 12,
    selectionMs: 1, renderMs: 30, cacheHit: false, payloadBytes: 1234, error: null,
  });
  assert.match(formatSwitchMeasurements([record]), /Network 12\.0 ms/);
  assert.equal(record.networkMs, record.fetchMs + record.bodyReadMs);
  assert.match(formatSwitchMeasurements([record]), /fetch 5\.0 ms \+ body 7\.0 ms/);
  assert.match(formatSwitchMeasurements([record]), /payload 1234 B/);
});

test('memory cache hit marks skipped network, parse, and preparation as zero', () => {
  const measurement = beginSwitchMeasurement('要町', 100);
  measurement.boardMs = 4;
  measurement.selectionMs = 0.2;
  const record = finishSwitchMeasurement(measurement, {
    timings: { cacheHit: true, fetchMs: 0, bodyReadMs: 0, jsonParseMs: 0,
      adapterMs: 0, payloadBytes: null },
    completedAt: 140,
    renderStartedAt: 125,
  });
  assert.equal(record.cacheHit, true);
  assert.equal(record.networkMs, 0);
  assert.equal(record.fetchMs, 0);
  assert.equal(record.bodyReadMs, 0);
  assert.equal(record.jsonParseMs, 0);
  assert.equal(record.prepareMs, 0);
  assert.equal(record.payloadBytes, null);
  assert.equal(record.boardMs, 4);
});

test('failed loads retain reached stages and show later stages as unexecuted', () => {
  const measurement = beginSwitchMeasurement('千川', 5);
  const record = finishSwitchMeasurement(measurement, {
    timings: { cacheHit: false, fetchMs: 9, bodyReadMs: null, jsonParseMs: null,
      adapterMs: null, payloadBytes: null },
    completedAt: 40,
    renderStartedAt: 20,
    outcome: '読込エラー',
    error: 'payloadを読み込めませんでした',
  });
  assert.equal(record.totalMs, 35);
  assert.equal(record.networkMs, 9);
  assert.equal(record.fetchMs, 9);
  assert.equal(record.bodyReadMs, null);
  assert.equal(record.jsonParseMs, null);
  assert.equal(record.prepareMs, null);
  assert.equal(record.renderMs, 20);
  assert.equal(record.error, 'payloadを読み込めませんでした');
  assert.match(formatSwitchMeasurements([record]), /読込エラー/);
  assert.match(formatSwitchMeasurements([record]), /JSON 未実行/);
  assert.match(formatSwitchMeasurements([record]), /body 未実行/);
});

test('out-of-order destination results remain associated with their own measurement', () => {
  const oldRequest = beginSwitchMeasurement('地下鉄赤塚', 10);
  const latestRequest = beginSwitchMeasurement('和光市', 20);
  const latestRecord = finishSwitchMeasurement(latestRequest, {
    timings: { cacheHit: false, fetchMs: 2, bodyReadMs: 3, jsonParseMs: 4,
      adapterMs: 5, payloadBytes: 500 },
    completedAt: 70, renderStartedAt: 60,
  });
  const staleRecord = finishSwitchMeasurement(oldRequest, {
    timings: { cacheHit: false, fetchMs: 30, bodyReadMs: 40, jsonParseMs: 50,
      adapterMs: 60, payloadBytes: 900 },
    completedAt: 200, outcome: 'superseded',
  });
  assert.equal(latestRecord.destinationName, '和光市');
  assert.equal(latestRecord.payloadBytes, 500);
  assert.equal(staleRecord.destinationName, '地下鉄赤塚');
  assert.equal(staleRecord.networkMs, 70);
  assert.equal(staleRecord.totalMs, null);
  assert.equal(staleRecord.renderMs, null);
  const history = appendSwitchMeasurement([latestRecord], staleRecord);
  assert.deepEqual(history.map(entry => entry.destinationName), ['地下鉄赤塚', '和光市']);
  assert.match(formatSwitchMeasurements(history), /^目的地切替計測（最新が先頭）\n1\. 和光市/);
  assert.match(formatSwitchMeasurements([latestRecord, staleRecord]), /別駅へ切替済み/);
});

test('history keeps only the latest ten records in memory', () => {
  let history = [];
  for (let index = 0; index < 12; index += 1) {
    history = appendSwitchMeasurement(history, { destinationName: `駅${index}` });
  }
  assert.equal(history.length, 10);
  assert.equal(history[0].destinationName, '駅2');
  assert.equal(history.at(-1).destinationName, '駅11');
  assert.throws(() => appendSwitchMeasurement([], {}, 0), /positive/);
});
