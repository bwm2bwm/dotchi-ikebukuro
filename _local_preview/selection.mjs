/** Preview-only display limits and countdown formatting. */
export function selectPreviewGroups(result, mode) {
  if (mode === 'departure') {
    const items = result.items.slice(0, 6);
    return items.length ? [{ line: null, items }] : [];
  }
  if (mode !== 'line') throw new TypeError("mode must be 'line' or 'departure'");
  return result.groups.map(group => ({ ...group, items: group.items.slice(0, 3) }))
    .filter(group => group.items.length > 0);
}

export function earliestVisible(groups) {
  return groups.flatMap(group => group.items).reduce((current, item) => !current
    || item.arrivalAtMs < current.arrivalAtMs
    || (item.arrivalAtMs === current.arrivalAtMs && item.departureAtMs < current.departureAtMs)
    ? item : current, null);
}

export function countdownText(departureAtMs, nowMs) {
  const remaining = Math.max(0, Math.ceil((departureAtMs - nowMs) / 1000));
  return {
    remaining,
    label: `${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`,
  };
}
