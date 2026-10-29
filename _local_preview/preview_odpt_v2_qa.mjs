import { buildV2QaBoard, ODPT_V2_QA_FILES, ODPT_V2_QA_ROUTES, ODPT_V2_QA_STATIONS,
  parseJstInput, serviceDateAt, validateQaState, validateV2Payload, verifyCandidateBytes } from './odpt_v2_qa_adapter.mjs';
import { countdownText } from './selection.mjs';

const DESTINATION_KEY = 'dotchi-ikebukuro.odpt-v2-qa.destination';
const IDS = ['clock', 'qa-datetime', 'qa-clock-set', 'qa-clock-real', 'qa-generated-at',
  'destination-trigger', 'route-display', 'destination-dialog', 'destination-close', 'destination-list',
  'timetable-status', 'route-coverage', 'mode-line', 'mode-departure', 'direct-only', 'board'];
const elements = Object.fromEntries(IDS.map(id => [id, document.getElementById(id)]));
if (IDS.some(id => !elements[id])) throw new Error('ODPT v2 QA画面に必要な要素がありません');
if (window.location.protocol !== 'http:' || window.location.hostname !== '127.0.0.1') {
  throw new Error('ODPT v2 QAは127.0.0.1からのみ起動できます');
}
if (!window.crypto?.subtle?.digest) throw new Error('このブラウザーでは候補IDを検証できません');

const serviceDateList = Object.values(ODPT_V2_QA_FILES);
const stationIds = Object.keys(ODPT_V2_QA_STATIONS);
const routeIds = Object.keys(ODPT_V2_QA_ROUTES);
const stationCache = new Map();
const destinationList = elements['destination-list'];
let qaState = null;
let selectedDestinationId = readDestination();
let selectedPayload = null;
let loadRequest = 0;
let mode = 'departure';
let directOnly = false;
let virtualClock = null;
let virtualElapsedAt = 0;
let clockInputError = false;

function readDestination() {
  try {
    const saved = window.localStorage.getItem(DESTINATION_KEY);
    return Object.hasOwn(ODPT_V2_QA_STATIONS, saved) ? saved : 'Hikawadai';
  } catch { return 'Hikawadai'; }
}

function setStatus(message, state = 'warning') {
  elements['timetable-status'].textContent = message;
  elements['timetable-status'].dataset.state = state;
}

function currentNow() {
  return virtualClock === null ? Date.now() : virtualClock + (Date.now() - virtualElapsedAt);
}

function dateTimeInputValue(epochMs) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(epochMs));
  const value = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}T${value.hour}:${value.minute}:${value.second}`;
}

function fetchUrl(path) {
  const url = new URL(path, window.location.href);
  if (url.origin !== window.location.origin || url.hostname !== '127.0.0.1') {
    throw new Error('local_origin_required');
  }
  return url;
}

async function fetchJsonBytes(path, maximumBytes = 1_500_000) {
  const response = await window.fetch(fetchUrl(path), {
    method: 'GET', mode: 'same-origin', credentials: 'omit', cache: 'no-store', redirect: 'error',
  });
  if (!response.ok || response.type === 'opaque') throw new Error('local_payload_fetch_failed');
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > maximumBytes) throw new Error('local_payload_too_large');
  let value;
  try { value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  catch { throw new Error('local_payload_json_invalid'); }
  return { value, bytes };
}

async function fetchJson(path, maximumBytes = 1_500_000) {
  return (await fetchJsonBytes(path, maximumBytes)).value;
}

async function loadQaState() {
  const state = await fetchJson('_odpt_v2_qa_state.json', 100_000);
  if (!Array.isArray(state.serviceDates) || state.serviceDates.length !== 3) throw new Error('qa_service_date_set_invalid');
  const dates = state.serviceDates;
  validateQaState(state, stationIds, dates);
  for (let index = 1; index < dates.length; index += 1) {
    const [year, month, day] = dates[index - 1].split('-').map(Number);
    const next = new Date(0);
    next.setUTCFullYear(year, month - 1, day + 1);
    next.setUTCHours(0, 0, 0, 0);
    if (next.toISOString().slice(0, 10) !== dates[index]) throw new Error('qa_service_dates_not_contiguous');
  }
  return state;
}

async function loadStation(stationId) {
  if (!Object.hasOwn(ODPT_V2_QA_FILES, stationId)) throw new Error('station_invalid');
  if (stationCache.has(stationId)) return stationCache.get(stationId);
  const { value: payload, bytes } = await fetchJsonBytes(ODPT_V2_QA_FILES[stationId]);
  await verifyCandidateBytes(bytes, qaState.candidateFiles[stationId]);
  await validateV2Payload(payload, { stationId, serviceDates: qaState.serviceDates });
  if (stationCache.size && [...stationCache.values()].some(value => value.generatedAt !== payload.generatedAt)) {
    throw new Error('station_generation_timestamp_mismatch');
  }
  stationCache.set(stationId, payload);
  return payload;
}

function makeDestinationOptions() {
  const fragment = document.createDocumentFragment();
  for (const [index, [stationId, name]] of Object.entries(ODPT_V2_QA_STATIONS).entries()) {
    const li = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'destination-option';
    button.dataset.destinationId = stationId;
    button.setAttribute('aria-pressed', String(stationId === selectedDestinationId));
    button.setAttribute('aria-posinset', String(index + 1));
    button.setAttribute('aria-setsize', String(stationIds.length));
    const label = document.createElement('span');
    label.textContent = name;
    const selected = document.createElement('span');
    selected.className = 'destination-option-state';
    selected.textContent = stationId === selectedDestinationId ? '選択中' : '';
    button.append(label, selected);
    button.addEventListener('click', () => {
      elements['destination-dialog'].close();
      if (stationId !== selectedDestinationId) {
        selectedDestinationId = stationId;
        try { window.localStorage.setItem(DESTINATION_KEY, stationId); } catch { /* optional local preference */ }
        loadSelectedStation();
      }
    });
    li.append(button);
    fragment.append(li);
  }
  destinationList.replaceChildren(fragment);
}

function renderCoverage(board) {
  const fragment = document.createDocumentFragment();
  for (const routeId of routeIds) {
    const route = document.createElement('span');
    route.className = 'coverage-state';
    route.dataset.state = board.routeStates[`${board.serviceDate}|${routeId}`]?.state ?? 'unknown';
    const labels = { running: '運行候補あり', not_started: '始発前', ended: '運行終了',
      start_unconfirmed: '始発・終電未確認', terminal_unconfirmed: '終電未確認',
      data_insufficient: 'データ不足', unknown: '状態未確認', no_candidates: '到着候補なし' };
    route.textContent = `${ODPT_V2_QA_ROUTES[routeId].name}: ${labels[route.dataset.state] ?? '状態未確認'}`;
    fragment.append(route);
  }
  if (board.noValidArrival) {
    const warning = document.createElement('span');
    warning.className = 'coverage-state';
    warning.dataset.state = 'unknown';
    warning.textContent = `no_valid_arrival UNKNOWN ${board.noValidArrivalCount}件・検証済み候補だけを表示対象・両路線の終電未確認`;
    fragment.append(warning);
  }
  if (board.otherUnknownCount > 0) {
    const warning = document.createElement('span');
    warning.className = 'coverage-state';
    warning.dataset.state = 'unknown';
    warning.textContent = `その他UNKNOWN ${board.otherUnknownCount}件・検証済み候補だけを表示対象・両路線の終電未確認`;
    fragment.append(warning);
  }
  if (board.infoCount > 0) {
    const info = document.createElement('span');
    info.className = 'coverage-state';
    info.textContent = `明示通過INFO ${board.infoCount}件（正常扱い）`;
    fragment.append(info);
  }
  elements['route-coverage'].replaceChildren(fragment);
}

function emptyMessage(board) {
  if (board.serviceState === 'ended') return '本日の終電は終了しました';
  if (board.serviceState === 'terminal_unconfirmed') return '終電未確認のため、運行終了とは判定できません';
  if (board.serviceState === 'start_unconfirmed') return '始発時刻を確認できないため、始発前とは判定できません';
  if (board.serviceState === 'unknown') return '運行状態を確認できないため、終電を判定できません';
  if (board.serviceState === 'no_candidates') return '目的地に到着する候補はありません';
  if (board.serviceState === 'not_started') return '始発前です';
  if (board.serviceState === 'unavailable') return '必要な運行日データがありません';
  return '現在から24時間以内に表示できる列車はありません';
}

function terminalBadge(item) {
  if (!item.isLastDeparture) return '';
  return item.terminalBasis === 'direct_only' ? '直通終電' : '終電';
}

function createCard(item, nowMs) {
  const article = document.createElement('article');
  article.className = `train route-${item.routeId}${item.isBest ? ' best' : ''}`;
  article.dataset.cardId = item.id;
  const primary = document.createElement('div');
  primary.className = 'primary';
  const head = document.createElement('div');
  head.className = 'train-head';
  const line = document.createElement('span');
  line.className = 'route';
  line.textContent = item.line;
  const best = document.createElement('span');
  best.className = 'bestmark';
  best.textContent = item.isBest ? item.bestLabel : '';
  head.append(line, best);
  const depart = document.createElement('div');
  depart.className = 'depart';
  const time = document.createElement('span');
  time.className = 'time-value';
  time.textContent = item.departureText;
  const suffix = document.createElement('span');
  suffix.textContent = '発';
  const presentation = document.createElement('span');
  presentation.className = 'type-destination';
  const kind = document.createElement('span');
  kind.className = 'type-label type-normal';
  kind.textContent = item.kind;
  const destination = document.createElement('span');
  destination.className = 'destination-label';
  destination.textContent = `${item.destination}行`;
  const badge = document.createElement('span');
  badge.className = 'terminal-badge';
  badge.textContent = terminalBadge(item);
  presentation.append(kind, destination, badge);
  depart.append(time, suffix, presentation);
  const sub = document.createElement('div');
  sub.className = 'sub';
  sub.textContent = item.transfer
    ? `${item.transfer.station}で${item.transfer.outgoingRoute}へ乗換・待ち約${Math.round(item.transfer.waitMinutes)}分・接続保証なし`
    : '直通・乗換なし';
  const serviceDate = document.createElement('span');
  serviceDate.className = 'service-date-label';
  serviceDate.textContent = `運行日 ${item.serviceDate}`;
  sub.append('　', serviceDate);
  primary.append(head, depart, sub);

  const countWrap = document.createElement('div');
  countWrap.className = 'countwrap';
  const countCaption = document.createElement('div');
  countCaption.className = 'minitxt';
  countCaption.textContent = '発車まで';
  const count = document.createElement('div');
  count.className = 'count';
  const remaining = countdownText(item.departureAtMs, nowMs);
  count.textContent = remaining.label;
  if (remaining.remaining <= 180) count.classList.add('red');
  countWrap.append(countCaption, count);

  const arrivalWrap = document.createElement('div');
  arrivalWrap.className = 'arrival-wrap';
  const arrivalCaption = document.createElement('div');
  arrivalCaption.className = 'minitxt arrival-caption';
  arrivalCaption.textContent = '到着';
  const arrival = document.createElement('div');
  arrival.className = 'arrival time-value';
  arrival.textContent = item.arrivalText;
  arrivalWrap.append(arrivalCaption, arrival);
  article.append(primary, countWrap, arrivalWrap);
  return article;
}

function render(board, nowMs) {
  elements['timetable-status'].textContent = board.status;
  const hasUncertainRoute = Object.values(board.routeStates).some(route =>
    ['unknown', 'data_insufficient', 'start_unconfirmed', 'terminal_unconfirmed'].includes(route.state));
  elements['timetable-status'].dataset.state = board.serviceState === 'unknown' || hasUncertainRoute
    || board.noValidArrival || board.otherUnknownCount > 0
    ? 'warning' : 'ok';
  renderCoverage(board);
  const boardNode = elements.board;
  const fragment = document.createDocumentFragment();
  if (board.groups.length) {
    for (const group of board.groups) {
      const section = document.createElement('section');
      section.className = 'line';
      if (group.line) {
        const title = document.createElement('h2');
        title.className = 'sectionlabel';
        title.textContent = group.line;
        section.append(title);
      }
      for (const item of group.items) section.append(createCard(item, nowMs));
      fragment.append(section);
    }
  } else {
    const empty = document.createElement('p');
    empty.className = board.serviceState === 'ended' ? 'empty terminal-ended' : 'empty';
    empty.setAttribute('role', 'status');
    empty.textContent = emptyMessage(board);
    fragment.append(empty);
  }
  boardNode.replaceChildren(fragment);
}

function updateDestinationLabel() {
  elements['route-display'].textContent = `池袋 → ${ODPT_V2_QA_STATIONS[selectedDestinationId]}`;
  makeDestinationOptions();
}

function tick() {
  const nowMs = currentNow();
  elements.clock.textContent = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).format(new Date(nowMs));
  if (!selectedPayload || !qaState) return;
  const board = buildV2QaBoard(selectedPayload, qaState, { nowMs, directOnly, mode });
  render(board, nowMs);
  if (clockInputError) {
    setStatus('仮想日時が不正です。YYYY-MM-DDTHH:mm または YYYY-MM-DDTHH:mm:ss のJST日時を確認してください。', 'error');
  }
}

async function loadSelectedStation() {
  const request = ++loadRequest;
  selectedPayload = null;
  elements.board.replaceChildren();
  elements['route-coverage'].replaceChildren();
  updateDestinationLabel();
  setStatus(`${ODPT_V2_QA_STATIONS[selectedDestinationId]}の候補を検証しています…`);
  try {
    const payload = await loadStation(selectedDestinationId);
    if (request !== loadRequest) return;
    selectedPayload = payload;
    elements['qa-generated-at'].textContent = `候補生成日時: ${new Date(payload.generatedAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}（source取得日時ではありません）`;
    tick();
  } catch (error) {
    if (request !== loadRequest) return;
    selectedPayload = null;
    stationCache.delete(selectedDestinationId);
    setStatus('ローカル候補の読込・検証に失敗しました。候補を表示しません。', 'error');
    elements.board.replaceChildren(Object.assign(document.createElement('p'), {
      className: 'empty', textContent: '候補データを確認できません。QA bundleを再準備してください。',
    }));
    elements['route-coverage'].replaceChildren();
  }
}

function updateClockInput() { elements['qa-datetime'].value = dateTimeInputValue(currentNow()); }

elements['destination-trigger'].addEventListener('click', () => elements['destination-dialog'].showModal());
elements['destination-close'].addEventListener('click', () => elements['destination-dialog'].close());
elements['mode-line'].addEventListener('click', () => { mode = 'line'; updateModes(); tick(); });
elements['mode-departure'].addEventListener('click', () => { mode = 'departure'; updateModes(); tick(); });
elements['direct-only'].addEventListener('change', event => { directOnly = event.currentTarget.checked; tick(); });
elements['qa-clock-set'].addEventListener('click', () => {
  const parsed = parseJstInput(elements['qa-datetime'].value);
  if (parsed === null) {
    clockInputError = true;
    setStatus('仮想日時が不正です。YYYY-MM-DDTHH:mm または YYYY-MM-DDTHH:mm:ss のJST日時を確認してください。', 'error');
    return;
  }
  clockInputError = false;
  virtualClock = parsed;
  virtualElapsedAt = Date.now();
  tick();
});
elements['qa-clock-real'].addEventListener('click', () => {
  clockInputError = false;
  virtualClock = null;
  updateClockInput();
  tick();
});

function updateModes() {
  const lineMode = mode === 'line';
  elements['mode-line'].classList.toggle('sel', lineMode);
  elements['mode-departure'].classList.toggle('sel', !lineMode);
  elements['mode-line'].setAttribute('aria-pressed', String(lineMode));
  elements['mode-departure'].setAttribute('aria-pressed', String(!lineMode));
}

async function start() {
  try {
    qaState = await loadQaState();
    updateDestinationLabel();
    updateClockInput();
    await loadSelectedStation();
    window.setInterval(tick, 1000);
  } catch {
    setStatus('ローカルQA bundleの検証に失敗しました。候補を表示しません。', 'error');
    elements.board.replaceChildren();
  }
}

updateModes();
start();
