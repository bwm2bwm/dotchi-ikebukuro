import test from 'node:test';
import assert from 'node:assert/strict';

import { countdownText, earliestVisible, selectPreviewGroups } from '../_local_preview/selection.mjs';

const item = (id, routeId, departureAtMs, arrivalAtMs) => ({ id, routeId, departureAtMs, arrivalAtMs });

test('line mode keeps at most three per line and departure mode keeps the first six overall', () => {
  const lineA = Array.from({ length: 5 }, (_, index) => item(`a${index}`, '6', index, index + 100));
  const lineB = Array.from({ length: 5 }, (_, index) => item(`b${index}`, '9', index + 5, index + 105));
  const result = {
    items: [...lineA, ...lineB].sort((a, b) => a.departureAtMs - b.departureAtMs),
    groups: [{ line: '有楽町線', items: lineA }, { line: '副都心線', items: lineB }],
  };
  const line = selectPreviewGroups(result, 'line');
  assert.deepEqual(line.map(group => group.items.length), [3, 3]);
  const departure = selectPreviewGroups(result, 'departure');
  assert.equal(departure[0].items.length, 6);
  assert.deepEqual(departure[0].items.map(row => row.id), ['a0', 'a1', 'a2', 'a3', 'a4', 'b0']);
});

test('earliest arrival is selected only from displayed candidates, with earlier-departure tie break', () => {
  const visible = [{ items: [
    item('later-tie', '9', 200, 500), item('early-tie', '6', 100, 500), item('fast', '9', 300, 450),
  ] }];
  assert.equal(earliestVisible(visible).id, 'fast');
  assert.equal(earliestVisible([{ items: visible[0].items.slice(0, 2) }]).id, 'early-tie');
});

test('countdown rounds up by second and clamps departed trains to zero', () => {
  assert.deepEqual(countdownText(10_001, 0), { remaining: 11, label: '00:11' });
  assert.deepEqual(countdownText(0, 1), { remaining: 0, label: '00:00' });
  assert.deepEqual(countdownText(181_000, 0), { remaining: 181, label: '03:01' });
});
