// 架空ダイヤ。実データへ切り替える際はこの配列をデータアダプターで置き換える。
// departSec はアプリ起動時からの相対秒、travelMin は目的地までの仮所要分。
window.DOTCHI_EXAMPLES = [
  { id: 1, line: '副都心線', color: '#9C5E31', departSec: 220, travelMin: 10, destination: '和光市', kind: '各駅停車', transfer: null },
  { id: 2, line: '有楽町線', color: '#c1a026', departSec: 340, travelMin: 15, destination: '小手指', kind: '各駅停車', transfer: { station: '小竹向原', wait: 3, detail: '小竹向原で和光市方面の列車に乗換（接続は仮設定）' } },
  { id: 3, line: '副都心線', color: '#9C5E31', departSec: 510, travelMin: 15, destination: '飯能', kind: '急行', transfer: { station: '小竹向原', wait: 6, detail: '小竹向原で和光市方面の列車に乗換（接続は仮設定）' } },
  { id: 4, line: '有楽町線', color: '#c1a026', departSec: 690, travelMin: 11, destination: '和光市', kind: '各駅停車', transfer: null },
  { id: 5, line: '副都心線', color: '#9C5E31', departSec: 940, travelMin: 10, destination: '和光市', kind: '各駅停車', transfer: null },
  { id: 6, line: '有楽町線', color: '#c1a026', departSec: 1080, travelMin: 12, destination: '小手指', kind: '各駅停車', transfer: { station: '小竹向原', wait: 2, detail: '小竹向原で和光市方面の列車に乗換（接続は仮設定）' } }
];
