import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { makeBundle, configuredBundle } from './odpt_dom_fixture.mjs';
import { readFile } from 'node:fs/promises';

import { buildV2QaBoard, ODPT_V2_QA_FILES } from '../_local_preview/odpt_v2_qa_adapter.mjs';

import { makeEnvironment, startDom, waitFor, withDom, assertBoardDom } from '../scripts/odpt_dom_harness.mjs';

test('v2 QA DOM shows verified cards and UNKNOWN warning, then clears warning on station/date changes', async () => {
  const env = makeEnvironment(await makeBundle());
  const wallNow = { value: Date.parse('2026-10-29T21:06:00+09:00') };
  let restore;
  try {
    restore = await startDom(env, wallNow);
    await waitFor(() => !env.elements.get('timetable-status').textContent.includes('検証しています'));
    env.elements.get('qa-datetime').value = '2026-10-29T05:30';
    env.elements.get('qa-clock-set').dispatch('click');
    assert.equal(env.elements.get('clock').textContent, '05:30:00');
    assert.ok(env.elements.get('board').querySelectorAll('.train').length > 0,
      `${env.elements.get('timetable-status').textContent} | ${env.elements.get('board').textContent}`);
    assert.match(env.elements.get('timetable-status').textContent, /両路線の終電は未確認/);
    assert.equal(env.elements.get('timetable-status').dataset.state, 'warning');
    assert.match(env.elements.get('route-coverage').textContent, /UNKNOWN 4件.*検証済み候補だけを表示対象/);
    assert.ok(env.elements.get('board').querySelectorAll('.bestmark').some(node =>
      node.textContent === '● 表示候補内の最早着'));
    assert.equal(env.elements.get('board').querySelector('.count').textContent, '30:00');
    wallNow.value += 1000;
    [...env.intervals.values()][0]();
    assert.equal(env.elements.get('clock').textContent, '05:30:01');
    assert.equal(env.elements.get('board').querySelector('.count').textContent, '29:59');

    env.elements.get('qa-datetime').value = '2026-02-29T06:00';
    env.elements.get('qa-clock-set').dispatch('click');
    assert.equal(env.elements.get('clock').textContent, '05:30:01');
    assert.match(env.elements.get('timetable-status').textContent, /仮想日時が不正です/);
    assert.equal(env.elements.get('timetable-status').dataset.state, 'error');
    wallNow.value += 5000;
    [...env.intervals.values()][0]();
    assert.equal(env.elements.get('clock').textContent, '05:30:06');
    assert.match(env.elements.get('timetable-status').textContent, /仮想日時が不正です/);

    env.elements.get('qa-clock-real').dispatch('click');
    assert.equal(env.elements.get('clock').textContent, '21:06:06');
    assert.equal(env.elements.get('qa-datetime').value, '2026-10-29T21:06:06');
    assert.equal(env.elements.get('timetable-status').dataset.state, 'warning');
    assert.equal(env.elements.get('board').querySelectorAll('.train').length, 0,
      'resetting to 21:06 returns to the real-time candidate selection');
    env.elements.get('qa-datetime').value = '2026-10-29T05:30';
    env.elements.get('qa-clock-set').dispatch('click');
    assert.equal(env.elements.get('clock').textContent, '05:30:00');

    env.elements.get('destination-list').querySelector('[data-destination-id="Senkawa"]').dispatch('click');
    await waitFor(() => env.elements.get('route-display').textContent === '池袋 → 千川'
      && !env.elements.get('timetable-status').textContent.includes('検証しています'));
    assert.ok(env.elements.get('board').querySelectorAll('.train').length > 0);
    assert.doesNotMatch(env.elements.get('timetable-status').textContent, /UNKNOWN|未確認/);
    assert.doesNotMatch(env.elements.get('route-coverage').textContent, /UNKNOWN/);

    env.elements.get('destination-list').querySelector('[data-destination-id="Hikawadai"]').dispatch('click');
    await waitFor(() => env.elements.get('route-display').textContent === '池袋 → 氷川台'
      && env.elements.get('route-coverage').textContent.includes('UNKNOWN 4件'));
    env.elements.get('qa-datetime').value = '2026-10-30T05:30:00';
    env.elements.get('qa-clock-set').dispatch('click');
    assert.equal(env.elements.get('board').querySelectorAll('.train').length, 0);
    assert.match(env.elements.get('timetable-status').textContent, /必要な運行日データがありません: 2026-10-31/);
    assert.doesNotMatch(env.elements.get('timetable-status').textContent, /UNKNOWN|未確認/);
    assert.doesNotMatch(env.elements.get('route-coverage').textContent, /UNKNOWN/);
  } finally {
    await restore?.();
  }
});

test('fixed-clock DOM cards follow reference groups and preserve best, labels, transfer text, and countdown edges', async () => {
  const files = await makeBundle();
  const env = makeEnvironment(files);
  const wallNow = { value: Date.parse('2026-10-29T06:00:00+09:00') };
  const restore = await startDom(env, wallNow);
  try {
    await waitFor(() => env.elements.get('board').querySelectorAll('.train').length > 0);
    const payloadBytes = files.get(ODPT_V2_QA_FILES.Hikawadai);
    const payload = JSON.parse(new TextDecoder().decode(payloadBytes));
    const state = JSON.parse(new TextDecoder().decode(files.get('_odpt_v2_qa_state.json')));
    const { buildV2QaBoard } = await import('../_local_preview/odpt_v2_qa_adapter.mjs');
    const nowMs = Date.parse('2026-10-29T06:00:00+09:00');
    env.elements.get('qa-datetime').value = '2026-10-29T06:00:00';
    env.elements.get('qa-clock-set').dispatch('click');
    const board = buildV2QaBoard(payload, state, { nowMs });
    const cards = env.elements.get('board').querySelectorAll('.train');
    const expected = board.groups.flatMap(group => group.items);
    assert.equal(cards.length, expected.length);
    assert.deepEqual(cards.map(card => card.dataset.cardId), expected.map(item => item.id));
    assert.equal(cards.filter(card => card.classList.contains('best')).length, expected.filter(item => item.isBest).length);
    assert.deepEqual(cards.map(card => card.querySelector('.bestmark').textContent), expected.map(item => item.isBest ? item.bestLabel : ''));
    assert.deepEqual(cards.map(card => card.querySelector('.time-value').textContent), expected.map(item => item.departureText));
    assert.deepEqual(cards.map(card => card.querySelector('.arrival').textContent), expected.map(item => item.arrivalText));
    assert.ok(cards.every((card, index) => card.textContent.includes(`運行日 ${expected[index].serviceDate}`)));
    assert.ok(cards.every(card => card.textContent.includes('各駅停車') && card.textContent.includes('QA行行')));
    assert.ok(cards.every(card => card.textContent.includes('直通・乗換なし')));
    assert.equal(env.elements.get('mode-departure').getAttribute('aria-pressed'), 'true');
    assert.equal(env.elements.get('mode-line').getAttribute('aria-pressed'), 'false');
    assert.equal(env.elements.get('board').querySelectorAll('.line').length, 1);

    const target = expected[0].departureAtMs;
    // Millisecond observations bypass datetime-local, whose accepted precision is seconds.
    env.elements.get('qa-clock-real').dispatch('click');
    for (const [offset, label, red] of [
      [-181000, '03:01', false], [-180001, '03:01', false],
      [-180000, '03:00', true], [-179999, '03:00', true], [-1, '00:01', true],
      [0, null, null], [1, null, null],
    ]) {
      wallNow.value = target + offset;
      [...env.intervals.values()][0]();
      const reference = buildV2QaBoard(payload, state, { nowMs: wallNow.value });
      assert.deepEqual(env.elements.get('board').querySelectorAll('.train').map(c => c.dataset.cardId),
        reference.groups.flatMap(g => g.items.map(i => i.id)));
      const visible = env.elements.get('board').querySelector(`[data-card-id="${expected[0].id}"]`);
      if (label === null) assert.equal(visible, null, `departure boundary ${offset}`);
      else {
        assert.ok(visible, `present at ${offset}`);
        assert.equal(visible.querySelector('.count').textContent, label, `countdown at ${offset}`);
        assert.equal(visible.querySelector('.count').classList.contains('red'), red, `red at ${offset}`);
      }
    }
    assert.equal(env.intervals.size, 1);
  } finally { await restore(); }
});

test('real HTML structure remains connected to the Fake DOM required IDs and defaults', async () => {
  const html = await readFile(new URL('../_local_preview/odpt_v2_qa.html', import.meta.url), 'utf8');
  const required = ['clock','qa-datetime','qa-clock-set','qa-clock-real','qa-generated-at','destination-trigger',
    'route-display','destination-dialog','destination-close','destination-list','timetable-status','route-coverage',
    'mode-line','mode-departure','direct-only','board'];
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(ids).size, ids.length, 'HTML IDs must be unique');
  assert.deepEqual(required, [...makeEnvironment(new Map()).elements.keys()]);
  for (const id of required) assert.ok(ids.includes(id), `required element ${id}`);
  assert.match(html, /<script\s+type="module"\s+src="preview_odpt_v2_qa\.mjs"/);
  assert.match(html, /id="mode-line"[^>]*aria-pressed="false"/);
  assert.match(html, /id="mode-departure"[^>]*aria-pressed="true"/);
  assert.match(html, /id="board"\s+aria-live="off"/);
  assert.match(html, /id="timetable-status"[^>]*role="status"/);
});

// Synthetic station bundles retain real candidate-byte hashing and public-ID validation.
function reference(files, epoch, { mode = 'departure', directOnly = false, station = 'Hikawadai' } = {}) {
  const decode = bytes => JSON.parse(new TextDecoder().decode(bytes));
  return buildV2QaBoard(decode(files.get(ODPT_V2_QA_FILES[station])),
    decode(files.get('_odpt_v2_qa_state.json')), { nowMs: epoch, mode, directOnly });
}

const noon = Date.parse('2026-10-29T12:00:00+09:00');
test('four DOM scenarios select alternatives, cap groups, preserve order and round transfer waits', async () => {
  const files = await configuredBundle();
  await withDom(files, noon, async env => {
    for (const mode of ['departure', 'line']) for (const directOnly of [false, true]) {
      env.elements.get(`mode-${mode}`).dispatch('click');
      env.elements.get('direct-only').checked = directOnly;
      env.elements.get('direct-only').dispatch('change');
      const board = reference(files, noon, { mode, directOnly });
      assert.ok(board.items.length > 6);
      assert.equal(board.groups.flatMap(g => g.items).length, 6);
      assert.ok(board.items.every(i => i.journeyKind === (directOnly ? 'direct' : 'transfer')));
      assertBoardDom(env, board, noon, mode, directOnly);
      if (!directOnly) {
        assert.match(env.elements.get('board').textContent, /待ち約1分・接続保証なし/);
        assert.match(env.elements.get('board').textContent, /待ち約2分・接続保証なし/);
      }
      const all = reference(files, noon);
      if (directOnly) {
        assert.equal(board.items[0].id, all.items[0].id);
        assert.equal(board.items[0].arrivalAtMs - all.items[0].arrivalAtMs, 600000);
      }
    }
    env.elements.get('destination-list').querySelector('[data-destination-id="Senkawa"]').dispatch('click');
    await waitFor(() => env.elements.get('board').querySelectorAll('.train').length === 6);
    assertBoardDom(env, reference(files, noon, { station: 'Senkawa', mode: 'line', directOnly: true }), noon, 'line', true);
    assert.equal(env.elements.get('route-display').textContent, '池袋 → 千川');
    const state = JSON.parse(new TextDecoder().decode(files.get('_odpt_v2_qa_state.json')));
    for (const station of ['Hikawadai', 'Senkawa']) {
      const audit = env.fetchAudit.find(a => a.filename === ODPT_V2_QA_FILES[station]);
      assert.deepEqual({ bytes: audit.bytes, sha256: audit.sha256 }, state.candidateFiles[station]);
    }
  });
});

test('best outside either card limit is not reselected; terminal cards may also be hidden', async () => {
  const files = await configuredBundle({ hiddenBest: true });
  await withDom(files, noon, async env => {
    for (const mode of ['departure', 'line']) {
      env.elements.get(`mode-${mode}`).dispatch('click');
      const board = reference(files, noon, { mode });
      assert.ok(board.bestId);
      assert.ok(!board.groups.flatMap(g => g.items).some(i => i.id === board.bestId));
      assert.equal(env.elements.get('board').querySelectorAll('.bestmark').filter(n => n.textContent).length, 0);
      assert.ok(board.items.some(i => i.isLastDeparture));
      assert.equal(env.elements.get('board').querySelectorAll('.terminal-badge').filter(n => n.textContent).length, 0);
      assertBoardDom(env, board, noon, mode);
    }
  });
});

test('visible terminal and direct terminal badges, best and UNKNOWN limited labels', async () => {
  for (const unknown of [0, 2]) {
    const files = await configuredBundle({ count: 1, unknown });
    await withDom(files, noon, async env => {
      for (const directOnly of [false, true]) {
        env.elements.get('direct-only').checked = directOnly;
        env.elements.get('direct-only').dispatch('change');
        const board = reference(files, noon, { directOnly });
        assertBoardDom(env, board, noon, 'departure', directOnly);
        assert.equal(env.elements.get('board').querySelector('.bestmark').textContent,
          unknown ? '● 表示候補内の最早着' : '● 最早着');
        assert.equal(env.elements.get('board').querySelectorAll('.terminal-badge').filter(n => n.textContent).length, unknown ? 0 : 2);
        assert.ok(Object.values(board.routeStates).every(s => s.terminalKnown === !unknown));
        if (unknown) assert.match(env.elements.get('route-coverage').textContent, /UNKNOWN 2件.*両路線の終電未確認/);
      }
    });
  }
});

for (const [state, options, wall] of [
  ['running', {}, '05:30:00'], ['not_started', {}, '04:59:59'], ['ended', {}, '06:00:00'],
  ['no_candidates', { count: 0 }, '05:30:00'], ['unknown', { coverage: 'unknown' }, '05:30:00'],
  ['data_insufficient', { coverage: 'insufficient' }, '05:30:00'],
  ['start_unconfirmed', { unknown: 1 }, '04:59:59'], ['terminal_unconfirmed', { unknown: 1 }, '06:00:00'],
]) test(`route state ${state} has its DOM label and correct empty guidance`, async () => {
  const files = await configuredBundle({ count: 1, departure: 6 * 3600, transfers: false, ...options });
  const epoch = Date.parse(`2026-10-29T${wall}+09:00`);
  await withDom(files, epoch, async env => {
    const board = reference(files, epoch);
    assert.equal(board.routeStates['2026-10-29|6'].state, state);
    assert.equal(board.routeStates['2026-10-29|9'].state, state);
    assertBoardDom(env, board, epoch);
    assert.equal(env.elements.get('board').querySelectorAll('.train').length, state === 'running' ? 2 : 0);
  });
});

test('INFO stays normal, other UNKNOWN propagates, and auxiliary coverage warns without extra route labels', async () => {
  for (const options of [{ info: 3 }, { otherUnknown: 4 }, { auxiliaryInsufficient: true }]) {
    const files = await configuredBundle({ count: 1, ...options });
    await withDom(files, noon, async env => {
      const board = reference(files, noon);
      assertBoardDom(env, board, noon);
      if (options.info) {
        assert.match(env.elements.get('route-coverage').textContent, /明示通過INFO 3件（正常扱い）/);
        assert.equal(env.elements.get('timetable-status').dataset.state, 'ok');
      } else if (options.otherUnknown) {
        assert.match(env.elements.get('route-coverage').textContent, /その他UNKNOWN 4件/);
        for (const route of ['6','9']) assert.equal(board.routeStates[`2026-10-29|${route}`].terminalKnown, false);
      } else {
        assert.equal(Object.keys(board.routeStates).length, 6);
        assert.equal(env.elements.get('route-coverage').querySelectorAll('.coverage-state').length, 2);
        assert.doesNotMatch(env.elements.get('route-coverage').textContent, /データ不足/);
        assert.equal(env.elements.get('timetable-status').dataset.state, 'warning');
      }
    });
  }
});

test('24 and 25 hour trains retain original serviceDate; missing necessary day keeps current ok notification', async () => {
  for (const hour of [24, 25]) {
    const files = await configuredBundle({ count: 1, departure: hour * 3600 + 600, transfers: false });
    const epoch = Date.parse(`2026-10-29T0${hour - 24}:00:00+09:00`);
    await withDom(files, epoch, async (env, clock) => {
      const board = reference(files, epoch);
      assertBoardDom(env, board, epoch);
      assert.ok(board.items.every(i => i.serviceDate === '2026-10-28'));
      assert.equal(board.items[0].departureText, `0${hour - 24}:10`);
      const outside = Date.parse('2026-10-30T12:00:00+09:00');
      // Keep real-clock mode and move only the fake clock.
      clock.value = outside;
      [...env.intervals.values()][0]();
      const missing = reference(files, outside);
      assert.equal(missing.serviceState, 'unavailable');
      assertBoardDom(env, missing, outside);
      assert.equal(env.elements.get('timetable-status').dataset.state, 'ok');
    });
  }
});

test('candidate bytes and QA state failures do not become normal empty candidate results', async () => {
  for (const failure of ['bytes', 'schema', 'state']) {
    const files = await configuredBundle();
    if (failure === 'state') files.set('_odpt_v2_qa_state.json', new TextEncoder().encode('{}'));
    else if (failure === 'bytes') files.set(ODPT_V2_QA_FILES.Hikawadai, new TextEncoder().encode('{}'));
    else {
      const state = JSON.parse(new TextDecoder().decode(files.get('_odpt_v2_qa_state.json')));
      const bytes = new TextEncoder().encode('{}');
      files.set(ODPT_V2_QA_FILES.Hikawadai, bytes);
      state.candidateFiles.Hikawadai = { sha256: createHash('sha256').update(bytes).digest('hex'), bytes: bytes.length };
      files.set('_odpt_v2_qa_state.json', new TextEncoder().encode(JSON.stringify(state)));
    }
    await withDom(files, noon, async env => {
      assert.equal(env.elements.get('timetable-status').dataset.state, 'error');
      assert.equal(env.elements.get('board').querySelectorAll('.train').length, 0);
      assert.match(env.elements.get('timetable-status').textContent, /検証に失敗/);
      if (failure !== 'state') assert.match(env.elements.get('board').textContent, /候補データを確認できません/);
    });
  }
});

test('harness disposes globals, listeners, timers, storage and fetch after failure and repeats deterministically', async () => {
  const files = await configuredBundle({ count: 1 });
  const before = { now: Date.now, window: globalThis.window, document: globalThis.document, fetch: globalThis.fetch };
  let disposed;
  let oldNodes;
  await assert.rejects(withDom(files, noon, async env => { disposed = env; oldNodes = [...env.nodes]; throw new Error('synthetic assertion failure'); }), /synthetic assertion failure/);
  assert.equal(disposed.intervals.size, 0);
  assert.equal(disposed.nodes.length, 0);
  assert.ok(oldNodes.every(n => n.listeners.size === 0 && n.children.length === 0));
  assert.equal(disposed.local.size, 0);
  assert.equal(disposed.windowRef.fetch, null);
  const snapshots = [];
  for (let n = 0; n < 2; n += 1) await withDom(files, noon, async env => {
    assertBoardDom(env, reference(files, noon), noon);
    snapshots.push(env.elements.get('board').textContent);
  });
  assert.equal(snapshots[0], snapshots[1]);
  assert.equal(Date.now, before.now);
  assert.equal(globalThis.window, before.window);
  assert.equal(globalThis.document, before.document);
  assert.equal(globalThis.fetch, before.fetch);
});

// The entry guard throws before its asynchronous start; cleanup must cover import itself.
test('entry import failure restores preexisting globals and clock', async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const previousDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
  const originalNow = Date.now;
  const sentinelWindow = {}; const sentinelDocument = {};
  globalThis.window = sentinelWindow; globalThis.document = sentinelDocument;
  const env = makeEnvironment(await makeBundle());
  env.windowRef.location.protocol = 'https:';
  try {
    await assert.rejects(startDom(env, { value: noon }), /127.0.0.1/);
    assert.equal(globalThis.window, sentinelWindow);
    assert.equal(globalThis.document, sentinelDocument);
    assert.equal(Date.now, originalNow);
    assert.equal(env.intervals.size, 0);
    assert.equal(env.nodes.length, 0);
  } finally {
    if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow);
    else delete globalThis.window;
    if (previousDocument) Object.defineProperty(globalThis, 'document', previousDocument);
    else delete globalThis.document;
  }
});

test('fixed initial render and manual ticks honor the inclusive 60-minute candidate gate', async () => {
  const files = await configuredBundle({ count: 1, departure: 6 * 3600, transfers: false });
  const gate = Date.parse('2026-10-29T05:00:00+09:00');
  await withDom(files, gate - 1, async (env, clock) => {
    assert.equal(env.elements.get('board').querySelectorAll('.train').length, 0);
    assertBoardDom(env, reference(files, clock.value), clock.value);
    for (const epoch of [gate, gate + 1]) {
      clock.value = epoch;
      [...env.intervals.values()][0]();
      assertBoardDom(env, reference(files, epoch), epoch);
      assert.equal(env.elements.get('board').querySelectorAll('.train').length, 2);
      assert.equal(env.elements.get('board').querySelector('.count').textContent, '60:00');
    }
  });
});
