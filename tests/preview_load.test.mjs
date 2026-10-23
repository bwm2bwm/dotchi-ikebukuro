import test from 'node:test';
import assert from 'node:assert/strict';

import { createLatestDestinationLoader, DESTINATION_PAYLOADS, loadTimetablePayload } from '../scripts/local_preview_payload_loader.mjs';

function emptyPayload(destinationStationId = 'Hikawadai') {
  const transferCapable = ['Heiwadai', 'ChikatetsuAkatsuka', 'ChikatetsuNarimasu', 'Wakoshi']
    .includes(destinationStationId);
  const route = () => ({ originTripCount: 0, candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 0,
    ...(transferCapable ? { directCandidateCount: 0, transferCandidateCount: 0, transferPairCount: 0,
      transferOnlyCount: 0 } : {}) });
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
    serviceDays: [{ serviceDate: '2026-10-22', originStationId: 'Ikebukuro', destinationStationId,
      departures: [], ...(destinationStationId !== 'Hikawadai' ? { destinationStatus: {
        status: 'no_candidates', candidateCount: 0, passThroughCount: 0, dataInsufficientCount: 0,
        ...(transferCapable ? { directCandidateCount: 0, transferCandidateCount: 0, transferPairCount: 0,
          transferOnlyCount: 0, transferPassThroughCount: 0, transferDataInsufficientCount: 0 } : {}),
        routes: { '6': route(), '9': route() },
      } } : {}) }],
    excludedServiceDates: [],
  };
}

test('valid payload loads and is prepared once', async () => {
  let calls = 0;
  const result = await loadTimetablePayload('Hikawadai', async (path, options) => {
    calls += 1;
    assert.equal(path, DESTINATION_PAYLOADS.Hikawadai);
    assert.equal(options.cache, 'no-store');
    return { ok: true, json: async () => emptyPayload('Hikawadai') };
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
    const result = await loadTimetablePayload('Hikawadai', fetchImpl);
    assert.equal(result.prepared, null);
    assert.match(result.failure, /読み込めませんでした/);
  }
});

test('invalid or incomplete metadata returns a data error without a payload', async () => {
  const invalid = emptyPayload();
  delete invalid.applicationPeriod;
  const result = await loadTimetablePayload('Hikawadai', async () => ({ ok: true, json: async () => invalid }));
  assert.equal(result.prepared, null);
  assert.match(result.failure, /必須メタデータ/);
});

test('fixed destination mapping loads only the selected payload and rejects an unknown ID', async () => {
  const ids = ['Kanamecho', 'Senkawa', 'KotakeMukaihara', 'Hikawadai', 'Heiwadai',
    'ChikatetsuAkatsuka', 'ChikatetsuNarimasu', 'Wakoshi'];
  assert.deepEqual(Object.keys(DESTINATION_PAYLOADS), ids);
  for (const id of ids) {
    const result = await loadTimetablePayload(id, async path => ({
      ok: true, json: async () => emptyPayload(id),
      path,
    }));
    assert.ok(result.prepared, id);
  }
  let calls = 0;
  const invalid = await loadTimetablePayload('../Wakoshi', async () => { calls += 1; });
  assert.equal(invalid.prepared, null);
  assert.match(invalid.failure, /不正/);
  assert.equal(calls, 0);
});

test('payload destination mismatch is rejected without a fallback', async () => {
  const result = await loadTimetablePayload('Wakoshi', async () => ({
    ok: true, json: async () => emptyPayload('Hikawadai'),
  }));
  assert.equal(result.prepared, null);
  assert.match(result.failure, /必須メタデータ/);
});

test('late destination response is marked stale after a newer selection', async () => {
  const pending = new Map();
  const loadLatest = createLatestDestinationLoader(id => new Promise(resolve => pending.set(id, resolve)));
  const first = loadLatest('Kanamecho');
  const second = loadLatest('Wakoshi');
  pending.get('Wakoshi')({ prepared: 'wakoshi', failure: null });
  const secondResult = await second;
  pending.get('Kanamecho')({ prepared: 'kanamecho', failure: null });
  const firstResult = await first;
  assert.equal(secondResult.stale, false);
  assert.equal(secondResult.prepared, 'wakoshi');
  assert.equal(firstResult.stale, true);
});
