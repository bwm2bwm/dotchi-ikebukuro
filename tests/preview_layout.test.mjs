import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const [html, css, mockCss, script] = await Promise.all([
  readFile(new URL('../_local_preview/index.html', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview.css', import.meta.url), 'utf8'),
  readFile(new URL('../styles.css', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview.js', import.meta.url), 'utf8'),
]);

test('preview uses the public mock structure and fixed ad dock with safe-area reserve', () => {
  for (const marker of ['viewport-fit=cover', 'class="top"', 'class="demo"', 'class="selectbox"',
    'class="controls"', 'class="filter"', 'id="board"', 'class="ad-dock"', 'AD 320×50']) {
    assert.ok(html.includes(marker), `missing ${marker}`);
  }
  assert.match(html, /href="styles\.css"/);
  assert.match(html, /href="preview\.css"/);
  assert.match(mockCss, /calc\(50px \+ 20px \+ env\(safe-area-inset-bottom/);
  assert.match(mockCss, /height: 50px/);
});

test('safety explanation is inside collapsed metadata details, not the normal footer area', () => {
  const details = html.match(/<details[\s\S]*?<\/details>/)?.[0] ?? '';
  assert.match(details, /有効期間外・必要な運行日データ不足・読込エラー時は古い列車を表示しません/);
  assert.doesNotMatch(html, /<footer|class="foot"/);
  for (const field of ['payload適用期間', 'payload生成日時', 'GTFS元データ更新日時',
    'ODPT元データ更新日時', 'Webアプリbuild日時']) assert.ok(details.includes(field));
});

test('public card sizing remains inherited while the iOS header stays below the status bar', () => {
  assert.match(mockCss, /min-height: 68px/);
  assert.match(mockCss, /margin-bottom: 4px/);
  assert.doesNotMatch(css, /\.train\s*\{/);
  assert.match(css, /position: sticky/);
  assert.match(css, /top: 0/);
  assert.match(css, /padding: env\(safe-area-inset-top/);
  assert.match(css, /\.controls\s*\{\s*margin-top: 3px; margin-bottom: 1px;/);
  assert.match(script, /line-count/);
});
