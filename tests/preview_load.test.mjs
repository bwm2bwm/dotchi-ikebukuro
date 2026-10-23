import test from 'node:test';
import assert from 'node:assert/strict';

import { createLatestDestinationLoader, createPreparedPayloadCache, DEFAULT_DESTINATION_ID,
  DEFAULT_DISPLAY_MODE, DESTINATION_PAYLOADS, DESTINATION_STORAGE_KEY, DISPLAY_MODE_STORAGE_KEY,
  loadTimetablePayload, readSavedDestinationId, readSavedDisplayMode, saveDestinationId,
  saveDisplayMode } from '../scripts/local_preview_payload_loader.mjs';

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

function payloadResponse(payload, { ok = true, contentLength = null, textError = null, textBody = undefined } = {}) {
  return {
    ok,
    headers: { get: name => name.toLowerCase() === 'content-length' ? contentLength : null },
    text: async () => {
      if (textError) throw textError;
      return textBody ?? JSON.stringify(payload);
    },
  };
}

test('valid payload loads and is prepared once', async () => {
  let calls = 0;
  const result = await loadTimetablePayload('Hikawadai', async (path, options) => {
    calls += 1;
    assert.equal(path, DESTINATION_PAYLOADS.Hikawadai);
    assert.equal(options.cache, 'no-store');
    return payloadResponse(emptyPayload('Hikawadai'), { contentLength: '1234' });
  });
  assert.ok(result.prepared);
  assert.equal(result.failure, null);
  assert.equal(calls, 1);
  assert.equal(result.timings.payloadBytes, 1234);
  for (const key of ['fetchMs', 'bodyReadMs', 'jsonParseMs', 'adapterMs', 'totalMs']) {
    assert.equal(typeof result.timings[key], 'number');
  }
});

test('fetch, HTTP, and JSON failures return a load error without a payload', async () => {
  const failures = [
    () => Promise.reject(new Error('offline')),
    async () => payloadResponse(emptyPayload(), { ok: false }),
    async () => payloadResponse(null, { textError: new Error('read failed') }),
  ];
  for (const fetchImpl of failures) {
    const result = await loadTimetablePayload('Hikawadai', fetchImpl);
    assert.equal(result.prepared, null);
    assert.match(result.failure, /読み込めませんでした/);
  }
});

test('invalid JSON reports a parse error and is not prepared', async () => {
  const result = await loadTimetablePayload('Hikawadai', async () => payloadResponse(null, { textBody: '{' }));
  assert.equal(result.prepared, null);
  assert.match(result.failure, /JSON形式/);
  assert.equal(typeof result.timings.jsonParseMs, 'number');
});

test('invalid or incomplete metadata returns a data error without a payload', async () => {
  const invalid = emptyPayload();
  delete invalid.applicationPeriod;
  const result = await loadTimetablePayload('Hikawadai', async () => payloadResponse(invalid));
  assert.equal(result.prepared, null);
  assert.match(result.failure, /必須メタデータ/);
});

test('fixed destination mapping loads only the selected payload and rejects an unknown ID', async () => {
  const ids = ['Kanamecho', 'Senkawa', 'KotakeMukaihara', 'Hikawadai', 'Heiwadai',
    'ChikatetsuAkatsuka', 'ChikatetsuNarimasu', 'Wakoshi'];
  assert.deepEqual(Object.keys(DESTINATION_PAYLOADS), ids);
  for (const id of ids) {
    const result = await loadTimetablePayload(id, async path => ({
      ...payloadResponse(emptyPayload(id)), path,
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
    ...payloadResponse(emptyPayload('Hikawadai')),
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

test('first visit defaults to Hikawadai and remembered supported ID is restored', () => {
  assert.equal(DEFAULT_DESTINATION_ID, 'Hikawadai');
  assert.equal(readSavedDestinationId(() => null), 'Hikawadai');
  const values = new Map([[DESTINATION_STORAGE_KEY, 'Wakoshi']]);
  const storage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  assert.equal(readSavedDestinationId(() => storage), 'Wakoshi');
  assert.equal(saveDestinationId('Heiwadai', () => storage), true);
  assert.deepEqual([...values.entries()], [[DESTINATION_STORAGE_KEY, 'Heiwadai']]);
});

test('unknown stored ID and storage failures safely fall back or remain non-fatal', () => {
  const unknown = { getItem: () => 'UnknownStation' };
  assert.equal(readSavedDestinationId(() => unknown), 'Hikawadai');
  assert.equal(readSavedDestinationId(() => { throw new Error('storage blocked'); }), 'Hikawadai');
  assert.equal(saveDestinationId('Wakoshi', () => { throw new Error('storage blocked'); }), false);
  assert.equal(saveDestinationId('UnknownStation', () => { throw new Error('must not be called'); }), false);
});

test('display mode is stored under a separate key and restores only supported values', () => {
  assert.equal(DEFAULT_DISPLAY_MODE, 'departure');
  assert.equal(readSavedDisplayMode(() => null), 'departure');
  const values = new Map([[DESTINATION_STORAGE_KEY, 'Wakoshi']]);
  const storage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  assert.equal(saveDisplayMode('line', () => storage), true);
  assert.equal(readSavedDisplayMode(() => storage), 'line');
  assert.deepEqual([...values.entries()], [
    [DESTINATION_STORAGE_KEY, 'Wakoshi'],
    [DISPLAY_MODE_STORAGE_KEY, 'line'],
  ]);
  values.set(DISPLAY_MODE_STORAGE_KEY, 'invalid');
  assert.equal(readSavedDisplayMode(() => storage), 'departure');
});

test('display mode storage failures and invalid writes do not break interaction', () => {
  assert.equal(readSavedDisplayMode(() => { throw new Error('blocked'); }), 'departure');
  assert.equal(saveDisplayMode('line', () => { throw new Error('blocked'); }), false);
  assert.equal(saveDisplayMode('route', () => { throw new Error('must not be called'); }), false);
});

test('prepared payload cache reuses only validated stations and stays bounded', () => {
  const cache = createPreparedPayloadCache(2);
  const first = { schemaVersion: 1 };
  const second = { schemaVersion: 1, id: 2 };
  const third = { schemaVersion: 1, id: 3 };
  assert.equal(cache.set('Hikawadai', first), true);
  assert.equal(cache.get('Hikawadai'), first);
  assert.equal(cache.set('Wakoshi', second), true);
  assert.equal(cache.set('Heiwadai', third), true);
  assert.deepEqual(cache.keys(), ['Wakoshi', 'Heiwadai']);
  assert.equal(cache.get('Hikawadai'), undefined);
  assert.equal(cache.set('../Wakoshi', third), false);
  assert.equal(cache.set('Senkawa', null), false);
});
