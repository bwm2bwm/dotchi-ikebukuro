import { readFile } from 'node:fs/promises';
import { validateTimetablePayload, PUBLIC_DATA_SCOPE } from './timetable_adapter.mjs';

const [filename, expectedDestinationId] = process.argv.slice(2);
if (!filename || !expectedDestinationId) throw new Error('usage: validate_public_payload.mjs FILE DESTINATION_ID');
const payload = JSON.parse(await readFile(filename, 'utf8'));
validateTimetablePayload(payload, PUBLIC_DATA_SCOPE);
for (const [index, day] of payload.serviceDays.entries()) {
  if (day.originStationId !== 'Ikebukuro') throw new Error(`serviceDays[${index}].originStationId must be Ikebukuro`);
  if (day.destinationStationId !== expectedDestinationId) {
    throw new Error(`serviceDays[${index}].destinationStationId must be ${expectedDestinationId}`);
  }
  if (!day.departures.length) throw new Error(`serviceDays[${index}].departures must not be empty`);
}
console.log(`public payload valid: ${payload.serviceDays.length} service days`);
