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

test('train type and destination have separate compact elements with distinct source styling', () => {
  assert.match(script, /class="type-destination"><span class="type-label"><\/span><span class="destination-label"><\/span>/);
  for (const style of ['type-normal', 'type-express', 'type-brand', 'type-supplement', 'type-unknown']) {
    assert.ok(css.includes(`.${style}`), `missing ${style} style`);
  }
  assert.match(script, /item\.kind === 'Fライナー'/);
  assert.match(script, /item\.kind === '急行' \|\| item\.kind === '通勤急行'/);
  assert.match(script, /item\.typeSource === 'official_route_rule'/);
  assert.match(script, /item\.typeSource === 'gtfs_stop_pattern'/);
  assert.match(script, /destination-label'\)\.textContent = `\$\{item\.destination\}行`/);
  assert.doesNotMatch(script, /destination-label'\)\.textContent = `・/);
  assert.doesNotMatch(css, /\.type-label\s*\{[^}]*display:\s*block/);
  assert.doesNotMatch(css, /\.train\s*\{/);
  assert.match(css, /\.type-destination\s*\{[^}]*gap:\s*4px;[^}]*white-space:\s*nowrap/);
  assert.match(css, /\.type-normal\s*\{[^}]*color:\s*#55565B/);
  assert.match(css, /\.type-express,\s*\.type-brand\s*\{[^}]*color:\s*#B84E49/);
  assert.match(css, /\.type-supplement\s*\{[^}]*color:\s*#68727a/);
  assert.match(css, /\.type-unknown\s*\{[^}]*color:\s*#737b84/);
  assert.doesNotMatch(css, /\.type-(?:normal|express|brand|supplement|unknown)\s*\{[^}]*text-decoration/);
  assert.match(mockCss, /\.bestmark\s*\{[^}]*color:\s*#267340/);
});
