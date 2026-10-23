import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
const adapterUrl = new URL(existsSync(new URL('./timetable_adapter.mjs', import.meta.url))
  ? './timetable_adapter.mjs' : '../scripts/timetable_adapter.mjs', import.meta.url);
const { buildBoard, prepareTimetablePayload } = await import(adapterUrl.href);

const filename = process.argv[2];
if (!filename) throw new Error('payload path is required');
let payload;
try {
  payload = JSON.parse(await readFile(filename, 'utf8'));
} catch (error) {
  throw new Error(`payload JSONを読めません: ${error.message}`);
}
const prepared = prepareTimetablePayload(payload);
const board = buildBoard(prepared, { nowMs: Date.now() });
if (board.validity !== 'valid') {
  const missing = board.diagnostics?.missingServiceDates ?? [];
  throw new Error(`payloadが現在利用できません (${board.validity})${missing.length ? `: 不足運行日 ${missing.join(', ')}` : ''}`);
}
console.log(`payload検証OK: ${payload.serviceDays.length}運行日、${payload.serviceDays.reduce((sum, day) => sum + day.departures.length, 0)}便`);
