import test from 'node:test';
import assert from 'node:assert/strict';

import { loadTimetablePayload } from '../scripts/local_preview_payload_loader.mjs';

function emptyPayload() {
  return {
    schemaVersion: 1,
    dataScope: 'local-preview-only',
    generatedAt: '2026-10-22T00:00:00+09:00',
    timezone: 'Asia/Tokyo',
    feed: { version: 'test', validFrom: '2026-10-21', validThrough: '2026-10-23', sourceUpdatedAt: null },
    odpt: { sourceUpdatedAt: null },
    applicationPeriod: { startsAt: '2026-10-21T00:00:00+09:00', endsAt: '2026-10-24T00:00:00+09:00' },
    webApp: { builtAt: null },
    connectionPolicy: { minimumWaitSeconds: 60, maximumWaitSeconds: 600,
      platformStatus: 'unknown', connectionGuaranteed: false },
    serviceDays: [],
    excludedServiceDates: [],
  };
}

test('valid payload loads and is prepared once', async () => {
  let calls = 0;
  const result = await loadTimetablePayload(async (path, options) => {
    calls += 1;
    assert.equal(path, './timetable.json');
    assert.equal(options.cache, 'no-store');
    return { ok: true, json: async () => emptyPayload() };
  });
  assert.ok(result.prepared);
  assert.equal(result.failure, null);
  assert.equal(calls, 1);
});

test('fetch, HTTP, and JSON failures return a load error without a payload', async () => {
  const failures = [
    () => Promise.reject(new Error('offline')),
    async () => ({ ok: false, json: async () => emptyPayload() }),
    async () => ({ ok: true, json: async () => { throw new SyntaxError('invalid JSON'); } }),
  ];
  for (const fetchImpl of failures) {
    const result = await loadTimetablePayload(fetchImpl);
    assert.equal(result.prepared, null);
    assert.match(result.failure, /読み込めませんでした/);
  }
});

test('invalid or incomplete metadata returns a data error without a payload', async () => {
  const invalid = emptyPayload();
  delete invalid.applicationPeriod;
  const result = await loadTimetablePayload(async () => ({ ok: true, json: async () => invalid }));
  assert.equal(result.prepared, null);
  assert.match(result.failure, /必須メタデータ/);
});
