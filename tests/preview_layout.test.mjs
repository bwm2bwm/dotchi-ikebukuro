import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const [html, publicHtml, css, diagnosticsCss, mockCss, localEntry, publicEntry, core, perfMetrics] = await Promise.all([
  readFile(new URL('../_local_preview/index.html', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/public_index.html', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview.css', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview_diagnostics.css', import.meta.url), 'utf8'),
  readFile(new URL('../styles.css', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview.js', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview_public.js', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/preview_core.mjs', import.meta.url), 'utf8'),
  readFile(new URL('../_local_preview/performance_metrics.mjs', import.meta.url), 'utf8'),
]);
const script = `${localEntry}\n${core}`;

test('preview uses the public mock structure and fixed ad dock with safe-area reserve', () => {
  for (const marker of ['viewport-fit=cover', 'class="top"', 'class="demo"', 'class="selectbox destination-trigger"',
    'class="controls"', 'class="filter"', 'id="board"', 'class="ad-dock"', 'AD 320×50']) {
    assert.ok(html.includes(marker), `missing ${marker}`);
  }
  assert.match(html, /href="styles\.css"/);
  assert.match(html, /href="preview\.css"/);
  assert.match(html, /href="preview_diagnostics\.css"/);
  assert.ok(html.indexOf('href="preview.css"') < html.indexOf('href="preview_diagnostics.css"'));
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
  assert.match(css, /position: sticky/);
  assert.match(css, /top: 0/);
  assert.match(css, /padding: env\(safe-area-inset-top/);
  assert.match(css, /\.controls\s*\{\s*margin-top: 3px; margin-bottom: 1px;/);
  assert.doesNotMatch(script, /line-count|3本/);
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
  assert.match(css, /\.train\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) 72px 56px;[^}]*gap:\s*3px;[^}]*padding-left:\s*13px;[^}]*padding-right:\s*6px;[^}]*align-items:\s*start/);
  assert.doesNotMatch(css, /\.train\s*\{[^}]*\b(?:min-height|margin|padding):/);
  assert.match(css, /\.type-destination\s*\{[^}]*gap:\s*4px;[^}]*white-space:\s*normal/);
  assert.match(css, /\.type-normal\s*\{[^}]*color:\s*#55565B/);
  assert.match(css, /\.type-express,\s*\.type-brand\s*\{[^}]*color:\s*#B84E49/);
  assert.match(css, /\.type-supplement\s*\{[^}]*color:\s*#68727a/);
  assert.match(css, /\.type-unknown\s*\{[^}]*color:\s*#737b84/);
  assert.doesNotMatch(css, /\.type-(?:normal|express|brand|supplement|unknown)\s*\{[^}]*text-decoration/);
  assert.match(mockCss, /\.bestmark\s*\{[^}]*color:\s*#267340/);
});

test('destination picker is an ordered modal and does not enlarge the page layout', () => {
  assert.match(html, /id="destination-trigger"[^>]*aria-haspopup="dialog"/);
  assert.match(html, /<dialog id="destination-dialog"/);
  assert.match(html, /id="destination-list"/);
  assert.match(script, /Kanamecho.*要町[\s\S]*Senkawa.*千川[\s\S]*KotakeMukaihara.*小竹向原[\s\S]*Hikawadai.*氷川台[\s\S]*Heiwadai.*平和台[\s\S]*ChikatetsuAkatsuka.*地下鉄赤塚[\s\S]*ChikatetsuNarimasu.*地下鉄成増[\s\S]*Wakoshi.*和光市/);
  assert.match(script, /selectedDestinationId = readSavedDestinationId\(\)/);
  assert.match(script, /destinationDialog\.showModal\(\)/);
  assert.match(script, /ArrowDown/);
  assert.match(script, /destinationTrigger\.focus/);
  assert.match(css, /env\(safe-area-inset-top/);
  assert.match(css, /env\(safe-area-inset-bottom/);
  assert.match(css, /body\.destination-modal-open\s*\{\s*overflow:\s*hidden/);
  assert.match(script, /arrival-caption'[)]\.textContent = '到着'/);
  assert.match(mockCss, /min-height: 68px/);
  assert.match(mockCss, /height: 50px/);
});

test('destination preference stores only a whitelisted ID and exposes development timing separately', () => {
  assert.match(script, /selectedDestinationId = readSavedDestinationId\(\)/);
  assert.match(script, /saveDestinationId\(destination\.id\)/);
  assert.match(script, /const preparedPayloadCache = createPreparedPayloadCache\(2(?:,|\))/);
  assert.match(script, /if \(result\.stale\) \{/);
  assert.match(script, /loadHistory: loadPerfHistory/);
  assert.match(script, /cachedDestinationIds/);
  assert.doesNotMatch(script, /localStorage|sessionStorage/);
});

test('opt-in performance panel stays in page flow and is absent from normal display', () => {
  const main = html.match(/<main>[\s\S]*?<\/main>/)?.[0] ?? '';
  assert.match(main, /id="board"[\s\S]*?id="performance-panel" class="performance-panel" hidden/);
  assert.match(html, /id="performance-latest"/);
  assert.match(html, /id="performance-copy"/);
  assert.match(html, /id="performance-history"[^>]*readonly/);
  assert.ok(html.indexOf('class="performance-panel"') < html.indexOf('class="ad-dock"'));
  assert.match(script, /const performanceMode = isPerformanceMode\(window\.location\.search\)/);
  assert.match(localEntry, /if \(performanceMode\) \{\s*performancePanel\.hidden = false/);
  assert.match(script, /Network \$\{duration\(latest\.networkMs\)\}（fetch \$\{duration\(latest\.fetchMs\)\}＋本文 \$\{duration\(latest\.bodyReadMs\)\}）/);
  assert.match(core, /changed \? hooks\.beginSwitch\?\.\(destination\.name\)/);
  assert.match(localEntry, /if \(!performanceMode \|\| !measurement\) return/);
  assert.match(diagnosticsCss, /\.performance-history[\s\S]*max-height:\s*180px;[^}]*overflow:\s*auto/);
  assert.match(perfMetrics, /slice\(-limit\)/);
  assert.doesNotMatch(perfMetrics, /localStorage|sessionStorage|fetch\(/);
  assert.match(script, /navigator\.clipboard\?\.writeText/);
  assert.match(script, /document\.execCommand\('copy'\)/);
});

test('public shell shares normal UI, excludes local diagnostics, and loads its fixed entrypoint', () => {
  assert.match(publicHtml, /href="styles\.css"/);
  assert.match(publicHtml, /href="preview\.css"/);
  assert.match(publicHtml, /src="preview_public\.js"/);
  assert.ok(publicHtml.indexOf('href="styles.css"') < publicHtml.indexOf('href="preview.css"'));
  assert.doesNotMatch(publicHtml, /preview_diagnostics\.css|preview\.js|debugNow|perf=1|debug-now-banner|payload-metadata|performance-/i);
  for (const marker of ['id="clock"', 'id="destination-trigger"', 'id="route-display"',
    'id="timetable-status"', 'id="mode-line"', 'id="mode-departure"', 'id="direct-only"',
    'id="board"', 'id="destination-dialog"', 'id="destination-close"', 'id="destination-list"',
    'class="ad-dock"', 'AD 320×50', '▼ 目的地を選択', '直通のみ表示']) {
    assert.ok(publicHtml.includes(marker), `public shell missing ${marker}`);
    assert.ok(html.includes(marker), `local shell missing ${marker}`);
  }
  assert.match(publicEntry, /PUBLIC_DATA_SCOPE/);
  assert.match(publicEntry, /cacheMode: 'default'/);
  assert.doesNotMatch(publicEntry, /debugNow|performance_metrics|isPerformanceMode/);
  assert.match(diagnosticsCss, /\.debug-now-banner/);
  assert.match(diagnosticsCss, /\.payload-metadata/);
  assert.match(diagnosticsCss, /\.performance-panel/);
  assert.doesNotMatch(css, /debug-now-banner|payload-metadata|performance-panel|performance-history/);
});

test('Phase 4B control order, mode default, and card labels match the compact layout spec', () => {
  const controls = html.match(/<div class="controls">[\s\S]*?<\/div>\s*<div id="board"/)?.[0] ?? '';
  assert.ok(controls.indexOf('class="toggle"') < controls.indexOf('class="filter"'));
  assert.match(html, /id="mode-line" type="button" aria-pressed="false"/);
  assert.match(html, /id="mode-departure" class="sel" type="button" aria-pressed="true"/);
  assert.match(html, /▼ 目的地を選択/);
  assert.match(script, /let mode = readSavedDisplayMode\(\)/);
  const renderStart = script.indexOf('function renderGroups');
  const loadStart = script.indexOf('async function loadDestination');
  const loadEnd = script.indexOf("destinationTrigger.addEventListener", loadStart);
  assert.ok(!script.slice(loadStart, loadEnd).includes("mode = 'line'"));
  assert.ok(!script.slice(loadStart, loadEnd).includes("mode = 'departure'"));
  assert.ok(!script.slice(loadStart, loadEnd).includes('directOnlyEl.checked ='));
  assert.ok(renderStart >= 0);
  assert.match(script, /<div class="minitxt">発車まで<\/div><div class="count"><\/div>/);
  assert.match(script, /<div class="minitxt arrival-caption">到着<\/div><div class="arrival time-value"><\/div>/);
  assert.match(script, /'直通・乗換なし'/);
  assert.match(script, /`小竹向原乗換・待ち約\$\{Math\.round\(item\.transfer\.waitMinutes\)\}分`/);
  assert.match(script, /<span class="departure-text time-value"><\/span>/);
  assert.match(script, /<div class="arrival time-value"><\/div>/);
  assert.match(css, /\.depart\s*>\s*\.time-value,\s*\.arrival\.time-value\s*\{[^}]*font-family:\s*inherit;[^}]*font-size:\s*15px;[^}]*font-weight:\s*800;[^}]*line-height:\s*1\.1;[^}]*letter-spacing:\s*normal;[^}]*font-variant-numeric:\s*tabular-nums/);
  assert.match(css, /\.sub\s*\{[^}]*font-size:\s*12px/);
  assert.match(css, /\.train\s*\{[^}]*align-items:\s*start/);
  assert.match(css, /\.depart\s*\{\s*margin-top:\s*4px; column-gap:\s*3px/);
  assert.match(css, /\.sub\s*\{\s*margin-top:\s*6px/);
  assert.match(css, /\.countwrap,\s*\.arrival-wrap\s*\{[^}]*align-items:\s*center;[^}]*text-align:\s*center/);
  assert.match(css, /\.countwrap \.count,\s*\.arrival-wrap \.arrival\s*\{\s*margin-top:\s*4px/);
  assert.match(css, /\.countwrap \.minitxt,\s*\.arrival-caption\s*\{\s*text-align:\s*center/);
  assert.match(mockCss, /\.train\s*\{[^}]*grid-template-columns:[^}]*min-height:\s*68px/);
  assert.match(mockCss, /\.train\s*\{[^}]*margin-bottom:\s*4px/);
  assert.match(css, /\.hint\s*\{[^}]*font-size:\s*11px;[^}]*font-weight:\s*750/);
  assert.match(css, /\.controls\s*>\s*\.toggle\s*\{\s*order:\s*0/);
  assert.match(css, /\.controls\s*>\s*\.filter\s*\{\s*order:\s*1/);
  assert.match(css, /\.type-destination\s*\{[^}]*flex:\s*0 1 auto;[^}]*min-width:\s*0;[^}]*flex-wrap:\s*wrap;[^}]*white-space:\s*normal/);
  assert.match(css, /\.type-label,\s*\.destination-label\s*\{[^}]*overflow-wrap:\s*anywhere/);
  assert.match(css, /@media \(max-width:\s*359px\)\s*\{\s*\.train\s*\{[^}]*72px 54px/);
});

test('display mode preference uses its own storage key, restores safely, and persists button changes', () => {
  assert.match(script, /let mode = readSavedDisplayMode\(\)/);
  assert.match(script, /saveDisplayMode\(mode\)/);
  assert.match(script, /updateModeButtons\(\)/);
  assert.match(script, /readSavedDisplayMode, saveDisplayMode/);
  assert.doesNotMatch(script, /saveDirectOnly|DIRECT_ONLY_STORAGE_KEY/);
});
