import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { emptyBoardText, terminalBadgeText } from '../_local_preview/terminal_ui.mjs';

const [entry, core, css, mockCss] = await Promise.all([
  readFile(new URL('../_local_preview/preview.js', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview_core.mjs', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview.css', import.meta.url), 'utf8'),
  readFile(new URL('../styles.css', import.meta.url), 'utf8'),
]);
const script = `${entry}\n${core}`;

test('terminal badges require a true terminal flag and a recognized basis', () => {
  assert.equal(terminalBadgeText({ isLastDeparture: true, terminalBasis: 'all_reachable' }), '終電');
  assert.equal(terminalBadgeText({ isLastDeparture: true, terminalBasis: 'direct_only' }), '直通終電');
  assert.equal(terminalBadgeText({ isLastDeparture: false, terminalBasis: 'all_reachable' }), '');
  assert.equal(terminalBadgeText({ isLastDeparture: true, terminalBasis: 'unknown' }), '');
  assert.equal(terminalBadgeText(null), '');
});

test('only the verified ended state gets the terminal-finished message', () => {
  assert.equal(emptyBoardText('ended'), '本日の終電は終了しました');
  for (const state of ['running', 'partial', 'not_started', 'no_service', 'no_candidates',
    'unknown', 'data_insufficient', 'unavailable']) {
    assert.equal(emptyBoardText(state), '現在から24時間以内に表示できる列車はありません。', state);
  }
});

test('preview renders terminal status per card and refreshes it through the normal tick path', () => {
  assert.match(script, /import \{ emptyBoardText, terminalBadgeText \} from '\.\/terminal_ui\.mjs'/);
  assert.match(script, /<span class="terminal-badge"><\/span>/);
  assert.match(script, /terminal-badge'\)\.textContent = terminalBadgeText\(item\)/);
  assert.match(script, /renderGroups\(groups, nowMs, result\.serviceState\)/);
  assert.match(script, /empty\.textContent = emptyBoardText\(serviceState\)/);
  assert.match(script, /empty\.className = serviceState === 'ended' \? 'empty terminal-ended' : 'empty'/);
  assert.match(script, /setInterval\(\(\) => tick\(\), 1000\)/);
  assert.match(script, /directOnlyEl\.addEventListener\('change', \(\) => tick\(\)\)/);
  assert.match(script, /boardEl\.replaceChildren\(\);\s*selectedSignature = '';/);
});

test('terminal badge fits near the type and destination without changing card or dock geometry', () => {
  assert.match(css, /\.terminal-badge\s*\{[^}]*flex:\s*0 0 auto;[^}]*white-space:\s*nowrap/);
  assert.match(css, /\.terminal-badge:empty\s*\{\s*display:\s*none/);
  assert.match(css, /\.type-destination\s*\{[^}]*flex-wrap:\s*wrap/);
  assert.match(css, /\.type-label,\s*\.destination-label\s*\{[^}]*overflow-wrap:\s*anywhere/);
  assert.match(css, /\.terminal-badge\s*\{[^}]*color:\s*#73551f;[^}]*background:\s*#fff7df/);
  assert.doesNotMatch(css, /\.terminal-badge\s*\{[^}]*#B84E49/);
  assert.match(mockCss, /min-height:\s*68px/);
  assert.match(mockCss, /margin-bottom:\s*4px/);
  assert.match(mockCss, /height:\s*50px/);
  assert.match(mockCss, /calc\(50px \+ 20px \+ env\(safe-area-inset-bottom/);
});
