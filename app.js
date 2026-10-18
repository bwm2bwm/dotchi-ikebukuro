// 表示と操作。列車データは data.js の DOTCHI_EXAMPLES を参照する。
const boot = Date.now();
const examples = window.DOTCHI_EXAMPLES;
const pad = n => String(n).padStart(2, '0');
const hhmm = timestamp => { const date = new Date(timestamp); return `${pad(date.getHours())}:${pad(date.getMinutes())}`; };
const nowEl = document.getElementById('now');
const board = document.getElementById('board');
const directEl = document.getElementById('onlyDirect');
let mode = 'line';

function card(train, now, bestId) {
  const departure = boot + train.departSec * 1000;
  const arrival = departure + train.travelMin * 60000;
  const left = Math.max(0, Math.ceil((departure - now) / 1000));
  const minutes = pad(Math.floor(left / 60));
  const seconds = pad(left % 60);
  const isBest = train.id === bestId;
  const row = document.createElement('article');
  row.className = `train${isBest ? ' best' : ''}`;
  row.style.setProperty('--line-color', train.color);
  row.innerHTML = `<div class="primary"><div class="train-head"><span class="route">${train.line}</span>${isBest ? '<span class="bestmark">● 最早着</span>' : ''}</div><div class="depart">${hhmm(departure)}発 <span class="minitxt">${train.kind}・${train.destination}行</span></div><div class="sub">${train.transfer ? `小竹向原乗換・待ち約${train.transfer.wait}分` : '直通・乗換なし'}</div></div><div class="countwrap"><div class="count ${left <= 180 ? 'red' : ''}">${minutes}:${seconds}</div><div class="minitxt">発車まで</div></div><div><div class="arrival">${hhmm(arrival)}</div><div class="minitxt" style="text-align:right">氷川台着</div></div>`;
  return row;
}

function draw() {
  const now = Date.now();
  const date = new Date(now);
  nowEl.textContent = `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  const current = examples.filter(train => boot + train.departSec * 1000 > now && (!directEl.checked || !train.transfer));
  if (!current.length) {
    board.innerHTML = '<p class="empty">デモ列車はすべて発車しました。画面を再読み込みすると新しい架空ダイヤを生成します。</p>' ;
    return;
  }
  const best = current.reduce((a, b) => a.departSec + a.travelMin * 60 < b.departSec + b.travelMin * 60 ? a : b).id;
  board.replaceChildren();
  if (mode === 'line') {
    for (const name of ['副都心線', '有楽町線']) {
      const trains = current.filter(train => train.line === name);
      if (!trains.length) continue;
      const section = document.createElement('div');
      section.className = 'line';
      section.innerHTML = `<div class="linehead"><span>${name}</span><span class="line-note">${trains.length}本</span></div>`;
      trains.forEach(train => section.appendChild(card(train, now, best)));
      board.appendChild(section);
    }
  } else {
    const section = document.createElement('div');
    section.className = 'line';
    [...current].sort((a, b) => a.departSec - b.departSec).forEach(train => section.appendChild(card(train, now, best)));
    board.appendChild(section);
  }
}

function setMode(next) {
  mode = next;
  document.getElementById('byLine').classList.toggle('sel', next === 'line');
  document.getElementById('byDeparture').classList.toggle('sel', next === 'departure');
  document.getElementById('byLine').setAttribute('aria-pressed', String(next === 'line'));
  document.getElementById('byDeparture').setAttribute('aria-pressed', String(next === 'departure'));
  draw();
}

document.getElementById('byLine').onclick = () => setMode('line');
document.getElementById('byDeparture').onclick = () => setMode('departure');
directEl.onchange = draw;
draw();
setInterval(draw, 1000);
