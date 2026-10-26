import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { effectiveNowMs, parseVirtualNow } from '../_local_preview/virtual_now.mjs';

const [html, script, core, css, mockCss] = await Promise.all([
  readFile(new URL('../_local_preview/index.html', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview.js', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview_core.mjs', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview.css', import.meta.url), 'utf8'),
  readFile(new URL('../styles.css', import.meta.url), 'utf8'),
]);

test('no virtual parameter uses the caller-provided current time', () => {
  assert.equal(parseVirtualNow(''), null);
  assert.equal(parseVirtualNow('?mode=departure'), null);
  assert.equal(effectiveNowMs(null, 123456), 123456);
});

test('valid debugNow is parsed as a fixed Asia/Tokyo wall time', () => {
  const parsed = parseVirtualNow('?debugNow=2026-10-27T00%3A10%3A00');
  assert.deepEqual(parsed, {
    nowMs: Date.parse('2026-10-26T15:10:00Z'),
    displayText: '2026/10/27 00:10',
  });
  assert.equal(effectiveNowMs(parsed, 0), parsed.nowMs);
  assert.equal(effectiveNowMs(parsed, 999999), parsed.nowMs);
});

test('invalid virtual dates fall back to real time without partial interpretation', () => {
  for (const value of [
    '2026-02-29T00:10:00', '2026-13-01T00:00:00', '2026-10-27T24:00:00',
    '2026-10-27T00:60:00', '2026-10-27T00:00:60', 'tomorrow', '2026-10-27T00:10:00Z',
  ]) {
    assert.equal(parseVirtualNow(`?debugNow=${encodeURIComponent(value)}`), null, value);
    assert.equal(effectiveNowMs(parseVirtualNow(`?debugNow=${encodeURIComponent(value)}`), 456), 456, value);
  }
});

test('night and morning QA examples preserve their JST date and time', () => {
  const cases = [
    ['2026-10-26T23:50:00', '2026-10-26T14:50:00.000Z', '2026/10/26 23:50'],
    ['2026-10-27T00:10:00', '2026-10-26T15:10:00.000Z', '2026/10/27 00:10'],
    ['2026-10-27T00:40:00', '2026-10-26T15:40:00.000Z', '2026/10/27 00:40'],
    ['2026-10-27T01:30:00', '2026-10-26T16:30:00.000Z', '2026/10/27 01:30'],
    ['2026-10-27T05:00:00', '2026-10-26T20:00:00.000Z', '2026/10/27 05:00'],
  ];
  for (const [value, expectedIso, expectedLabel] of cases) {
    const parsed = parseVirtualNow(`?debugNow=${value}`);
    assert.ok(parsed, value);
    assert.equal(new Date(parsed.nowMs).toISOString(), expectedIso, value);
    assert.equal(parsed.displayText, expectedLabel, value);
  }
});

test('preview exposes the override only when valid and keeps normal layout unchanged', () => {
  assert.match(script, /parseVirtualNow\(window\.location\.search\)/);
  assert.match(script, /nowProvider: \(\) => effectiveNowMs\(virtualNow\)/);
  assert.match(script, /debugNowBanner\.textContent = `テスト日時：\$\{virtualNow\.displayText\}`/);
  assert.match(script, /debugNowBanner\.hidden = false/);
  assert.match(core, /windowRef\.setInterval\(\(\) => tick\(\), 1000\)/);
  assert.match(html, /id="debug-now-banner" class="debug-now-banner" hidden/);
  assert.match(css, /\.debug-now-banner\s*\{[^}]*font-size:\s*10px/);
  assert.match(mockCss, /height:\s*50px/);
  assert.match(mockCss, /calc\(50px \+ 20px \+ env\(safe-area-inset-bottom/);
});
