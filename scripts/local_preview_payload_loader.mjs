import { prepareTimetablePayload } from './timetable_adapter.mjs';

export const DEFAULT_DESTINATION_ID = 'Hikawadai';
export const DESTINATION_PAYLOADS = Object.freeze({
  Kanamecho: './timetable-Kanamecho.json',
  Senkawa: './timetable-Senkawa.json',
  KotakeMukaihara: './timetable-KotakeMukaihara.json',
  Hikawadai: './timetable.json',
  Heiwadai: './timetable-Heiwadai.json',
  ChikatetsuAkatsuka: './timetable-ChikatetsuAkatsuka.json',
  ChikatetsuNarimasu: './timetable-ChikatetsuNarimasu.json',
  Wakoshi: './timetable-Wakoshi.json',
});

export function createLatestDestinationLoader(loadPayload) {
  if (typeof loadPayload !== 'function') throw new TypeError('loadPayload must be a function');
  let latestRequest = 0;
  return async destinationStationId => {
    const requestId = ++latestRequest;
    const result = await loadPayload(destinationStationId);
    return { ...result, destinationStationId, stale: requestId !== latestRequest };
  };
}

export async function loadTimetablePayload(destinationStationId = DEFAULT_DESTINATION_ID, fetchImpl = fetch) {
  const filename = Object.hasOwn(DESTINATION_PAYLOADS, destinationStationId)
    ? DESTINATION_PAYLOADS[destinationStationId]
    : null;
  if (!filename) {
    return { prepared: null, failure: '選択した目的地IDが不正です。氷川台へ戻ってください。' };
  }

  let raw;
  try {
    const response = await fetchImpl(filename, { cache: 'no-store' });
    if (!response.ok) throw new Error('payload response is not successful');
    raw = await response.json();
  } catch {
    return { prepared: null, failure: '実ダイヤpayloadを読み込めませんでした。ローカルpreviewを再生成してください。' };
  }
  try {
    if (!Array.isArray(raw?.serviceDays)
        || raw.serviceDays.length === 0
        || raw.serviceDays.some(day => day.destinationStationId !== destinationStationId)) {
      throw new TypeError('payload destination does not match the requested destination');
    }
    return { prepared: prepareTimetablePayload(raw), failure: null };
  } catch {
    return { prepared: null, failure: 'payloadの形式または必須メタデータを確認できません。プレビューを再生成してください。' };
  }
}
