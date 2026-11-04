/** Synthetic fixtures only. Never reads saved source data. */
import { webcrypto, createHash } from 'node:crypto';
import { computeV2PublicId, ODPT_V2_QA_FILES, ODPT_V2_QA_STATIONS, ODPT_V2_QA_STATE_SCOPE } from '../_local_preview/odpt_v2_qa_adapter.mjs';
const serviceDates = ['2026-10-28', '2026-10-29', '2026-10-30'];
async function makeBundle() {
  const files = new Map();
  const stations = {};
  const candidateFiles = {};
  for (const stationId of Object.keys(ODPT_V2_QA_STATIONS)) {
    const serviceDays = [];
    for (const serviceDate of serviceDates) {
      const departures = [];
      for (const [routeId, departureSeconds, arrivalSeconds] of [
        ['6', 6 * 3600, 6 * 3600 + 20 * 60],
        ['9', 6 * 3600 + 300, 6 * 3600 + 45 * 60],
      ]) {
        const journey = { kind: 'direct', departureServiceSeconds: departureSeconds,
          arrivalServiceSeconds: arrivalSeconds, transfer: null };
        const row = { routeId, destination: 'QA行', displayType: '各駅停車',
          departureServiceSeconds: departureSeconds, primary: journey, directAlternative: journey,
          bestTransferAlternative: null };
        row.id = await computeV2PublicId(stationId, serviceDate, row, webcrypto);
        departures.push(row);
      }
      serviceDays.push({ serviceDate,
        routeCoverage: { '6': { scheduledTripCount: 439, dataState: 'complete' },
          '9': { scheduledTripCount: 500, dataState: 'complete' } }, departures });
    }
    const payload = { schemaVersion: 2, dataScope: 'public-display-v2', generatedAt: '2026-10-29T00:00:00Z',
      timezone: 'Asia/Tokyo', applicationPeriod: null, stationId, originStationId: 'Ikebukuro', serviceDays };
    const bytes = new TextEncoder().encode(JSON.stringify(payload));
    files.set(ODPT_V2_QA_FILES[stationId], bytes);
    candidateFiles[stationId] = { sha256: createHash('sha256').update(bytes).digest('hex'), bytes: bytes.length };
    stations[stationId] = Object.fromEntries(serviceDates.map(serviceDate => [serviceDate, {
      infoCount: 0,
      noValidArrivalCount: stationId === 'Hikawadai' && serviceDate === '2026-10-29' ? 4 : 0,
      otherUnknownCount: 0,
    }]));
  }
  const state = { schemaVersion: 1, dataScope: ODPT_V2_QA_STATE_SCOPE, serviceDates, stations, candidateFiles };
  files.set('_odpt_v2_qa_state.json', new TextEncoder().encode(JSON.stringify(state)));
  return files;
}


async function configuredBundle({ count = 8, departure = 12 * 3600 + 60,
  unknown = 0, otherUnknown = 0, info = 0, coverage = 'complete', hiddenBest = false,
  transfers = true, auxiliaryInsufficient = false } = {}) {
  const files = await makeBundle();
  const decode = bytes => JSON.parse(new TextDecoder().decode(bytes));
  const state = decode(files.get('_odpt_v2_qa_state.json'));
  for (const stationId of Object.keys(ODPT_V2_QA_STATIONS)) {
    const payload = decode(files.get(ODPT_V2_QA_FILES[stationId]));
    for (const day of payload.serviceDays) {
      day.departures = [];
      for (const routeId of ['6', '9']) {
        day.routeCoverage[routeId].dataState = auxiliaryInsufficient && day.serviceDate === serviceDates[2]
          ? 'insufficient' : coverage;
        for (let n = 0; n < count; n += 1) {
          const dep = departure + n * 60;
          const direct = { kind: 'direct', departureServiceSeconds: dep,
            arrivalServiceSeconds: dep + 5400, transfer: null };
          const transfer = { kind: 'transfer', departureServiceSeconds: dep,
            arrivalServiceSeconds: hiddenBest && n === count - 1 && routeId === '9' ? dep + 4000 : dep + 4800,
            transfer: { stationId: 'KotakeMukaihara', waitSeconds: [89, 90, 91, 3600][n % 4],
              outgoingRouteId: routeId === '6' ? '9' : '6' } };
          const primary = transfers ? transfer : direct;
          const row = { routeId, destination: '合成終点', displayType: '合成種別',
            departureServiceSeconds: dep, primary, directAlternative: transfers && n === 2 ? null : direct,
            bestTransferAlternative: transfers ? transfer : null };
          row.id = await computeV2PublicId(stationId, day.serviceDate, row, webcrypto);
          day.departures.push(row);
        }
      }
      day.departures.sort((a, b) => a.departureServiceSeconds - b.departureServiceSeconds || a.routeId.localeCompare(b.routeId));
      state.stations[stationId][day.serviceDate] = { infoCount: info,
        noValidArrivalCount: unknown, otherUnknownCount: otherUnknown };
    }
    const bytes = new TextEncoder().encode(JSON.stringify(payload));
    files.set(ODPT_V2_QA_FILES[stationId], bytes);
    state.candidateFiles[stationId] = { sha256: createHash('sha256').update(bytes).digest('hex'), bytes: bytes.length };
  }
  files.set('_odpt_v2_qa_state.json', new TextEncoder().encode(JSON.stringify(state)));
  return files;
}


export { makeBundle, configuredBundle };
