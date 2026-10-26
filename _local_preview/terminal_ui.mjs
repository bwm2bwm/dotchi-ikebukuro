/** Return a terminal badge only when the adapter provides a recognized basis. */
export function terminalBadgeText(item) {
  if (item?.isLastDeparture !== true) return '';
  if (item.terminalBasis === 'all_reachable') return '終電';
  if (item.terminalBasis === 'direct_only') return '直通終電';
  return '';
}

/** Empty-board copy is terminal only for a verified, fully ended service state. */
export function emptyBoardText(serviceState) {
  return serviceState === 'ended'
    ? '本日の終電は終了しました'
    : '現在から24時間以内に表示できる列車はありません。';
}
