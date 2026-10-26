const TOKYO_OFFSET_MS = 9 * 60 * 60 * 1000;
const DEBUG_NOW_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

/** Parse debugNow as a JST wall time, independent of the device's local timezone. */
export function parseVirtualNow(search) {
  let raw;
  try {
    raw = new URLSearchParams(search).get('debugNow');
  } catch {
    return null;
  }
  if (raw === null) return null;

  const match = DEBUG_NOW_PATTERN.exec(raw);
  if (!match) return null;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText = '00'] = match;
  const [year, month, day, hour, minute, second] = [
    yearText, monthText, dayText, hourText, minuteText, secondText,
  ].map(Number);
  if (month < 1 || month > 12 || day < 1 || day > 31
      || hour > 23 || minute > 59 || second > 59) return null;

  const wallTime = new Date(0);
  wallTime.setUTCFullYear(year, month - 1, day);
  wallTime.setUTCHours(hour, minute, second, 0);
  if (wallTime.getUTCFullYear() !== year || wallTime.getUTCMonth() !== month - 1
      || wallTime.getUTCDate() !== day || wallTime.getUTCHours() !== hour
      || wallTime.getUTCMinutes() !== minute || wallTime.getUTCSeconds() !== second) return null;

  return Object.freeze({
    nowMs: wallTime.getTime() - TOKYO_OFFSET_MS,
    displayText: `${yearText}/${monthText}/${dayText} ${hourText}:${minuteText}`,
  });
}

/** Use a parsed override when present; otherwise preserve the real clock. */
export function effectiveNowMs(virtualNow, actualNowMs = Date.now()) {
  return virtualNow?.nowMs ?? actualNowMs;
}
