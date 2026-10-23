import { prepareTimetablePayload } from './timetable_adapter.mjs';

export async function loadTimetablePayload(fetchImpl = fetch) {
  let raw;
  try {
    const response = await fetchImpl('./timetable.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('payload response is not successful');
    raw = await response.json();
  } catch {
    return { prepared: null, failure: '実ダイヤpayloadを読み込めませんでした。ローカルpreviewを再生成してください。' };
  }
  try {
    return { prepared: prepareTimetablePayload(raw), failure: null };
  } catch {
    return { prepared: null, failure: 'payloadの形式または必須メタデータを確認できません。プレビューを再生成してください。' };
  }
}
