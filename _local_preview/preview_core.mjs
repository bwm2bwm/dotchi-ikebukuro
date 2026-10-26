import { buildBoard, LOCAL_DATA_SCOPE, PUBLIC_DATA_SCOPE, TOKYO_TIME_ZONE } from './timetable_adapter.mjs';
import { createLatestDestinationLoader, createPreparedPayloadCache, loadTimetablePayload,
  readSavedDestinationId, saveDestinationId, readSavedDisplayMode, saveDisplayMode,
  DESTINATION_PAYLOADS } from './local_preview_payload_loader.mjs';
import { countdownText, earliestVisible, selectPreviewGroups } from './selection.mjs';
import { emptyBoardText, terminalBadgeText } from './terminal_ui.mjs';

const DESTINATIONS = Object.freeze([
  { id: 'Kanamecho', name: '要町' },
  { id: 'Senkawa', name: '千川' },
  { id: 'KotakeMukaihara', name: '小竹向原' },
  { id: 'Hikawadai', name: '氷川台' },
  { id: 'Heiwadai', name: '平和台' },
  { id: 'ChikatetsuAkatsuka', name: '地下鉄赤塚' },
  { id: 'ChikatetsuNarimasu', name: '地下鉄成増' },
  { id: 'Wakoshi', name: '和光市' },
]);

const REQUIRED_ELEMENTS = Object.freeze([
  'clock', 'timetable-status', 'board', 'destination-trigger', 'route-display',
  'destination-dialog', 'destination-close', 'destination-list', 'direct-only', 'mode-line', 'mode-departure',
]);
const OPTIONAL_METADATA_ELEMENTS = Object.freeze([
  'payload-metadata', 'meta-application-period', 'meta-generated-at', 'meta-feed-period',
  'meta-gtfs-updated', 'meta-odpt-updated', 'meta-webapp-built',
]);

function collectElements(documentRef) {
  const elements = Object.fromEntries(REQUIRED_ELEMENTS.map(id => [id, documentRef.getElementById(id)]));
  const missing = REQUIRED_ELEMENTS.filter(id => !elements[id]);
  if (missing.length) throw new Error(`preview DOM is missing required elements: ${missing.join(', ')}`);
  const metadataElements = Object.fromEntries(OPTIONAL_METADATA_ELEMENTS.map(id => [id, documentRef.getElementById(id)]));
  const metadataCount = Object.values(metadataElements).filter(Boolean).length;
  if (metadataCount > 0 && metadataCount < OPTIONAL_METADATA_ELEMENTS.length) {
    throw new Error(`preview DOM has incomplete optional metadata elements: ${OPTIONAL_METADATA_ELEMENTS.filter(id => !metadataElements[id]).join(', ')}`);
  }
  Object.assign(elements, metadataElements);
  return elements;
}

/** Start the shared display runtime with an explicit payload profile and cache policy. */
export function createPreviewRuntime({ expectedProfile = LOCAL_DATA_SCOPE, cacheMode, nowProvider = Date.now,
  hooks = {}, documentRef = document, windowRef = window } = {}) {
  if (![LOCAL_DATA_SCOPE, PUBLIC_DATA_SCOPE].includes(expectedProfile)) {
    throw new TypeError('explicit supported expected payload profile required');
  }
  const requiredCacheMode = expectedProfile === LOCAL_DATA_SCOPE ? 'no-store' : 'default';
  if (cacheMode !== requiredCacheMode) throw new TypeError(`${expectedProfile} requires cacheMode ${requiredCacheMode}`);
  if (typeof nowProvider !== 'function') throw new TypeError('nowProvider must be a function');
  const elements = collectElements(documentRef);
  const {
    clock,
    'timetable-status': statusEl,
    'payload-metadata': metadataEl,
    board: boardEl,
    'destination-trigger': destinationTrigger,
    'route-display': routeDisplay,
    'destination-dialog': destinationDialog,
    'destination-close': destinationClose,
    'destination-list': destinationList,
    'direct-only': directOnlyEl,
    'mode-line': lineButton,
    'mode-departure': departureButton,
  } = elements;
  const clockFormatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: TOKYO_TIME_ZONE, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  });
  const metadataFormatter = new Intl.DateTimeFormat('ja-JP', {
    timeZone: TOKYO_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  });
  let mode = readSavedDisplayMode();
  let selectedDestinationId = readSavedDestinationId();
  let prepared = null;
  let loadFailure = null;
  let loading = true;
  const preparedPayloadCache = createPreparedPayloadCache(2);
  let fetchCount = 0;
  let selectedSignature = '';
  let metadataSignature = '';
  const loadLatestDestination = createLatestDestinationLoader(async destinationId => {
    const cached = preparedPayloadCache.get(destinationId);
    if (cached) {
      const cacheStarted = performanceClock();
      return { prepared: cached, failure: null, timings: {
        fetchMs: 0, bodyReadMs: 0, jsonParseMs: 0, adapterMs: 0,
        totalMs: performanceClock() - cacheStarted,
        payloadBytes: null, cacheHit: true,
      } };
    }
    if (Object.hasOwn(DESTINATION_PAYLOADS, destinationId)) fetchCount += 1;
    return loadTimetablePayload(destinationId, windowRef.fetch.bind(windowRef), { expectedProfile, cacheMode });
  });
  const performanceClock = () => globalThis.performance.now();

  function setStatus(message, state) {
    if (statusEl.textContent !== message) statusEl.textContent = message;
    statusEl.dataset.state = state;
  }

  function updateModeButtons() {
    const lineSelected = mode === 'line';
    lineButton.classList.toggle('sel', lineSelected);
    departureButton.classList.toggle('sel', !lineSelected);
    lineButton.setAttribute('aria-pressed', String(lineSelected));
    departureButton.setAttribute('aria-pressed', String(!lineSelected));
  }

  function selectedDestination() {
    return DESTINATIONS.find(destination => destination.id === selectedDestinationId) ?? null;
  }

  function renderDestinationOptions() {
    const fragment = documentRef.createDocumentFragment();
    for (const [index, destination] of DESTINATIONS.entries()) {
      const item = documentRef.createElement('li');
      const button = documentRef.createElement('button');
      button.className = 'destination-option';
      button.type = 'button';
      button.dataset.destinationId = destination.id;
      button.setAttribute('aria-pressed', String(destination.id === selectedDestinationId));
      button.setAttribute('aria-posinset', String(index + 1));
      button.setAttribute('aria-setsize', String(DESTINATIONS.length));
      const label = documentRef.createElement('span');
      label.textContent = destination.name;
      const state = documentRef.createElement('span');
      state.className = 'destination-option-state';
      state.textContent = destination.id === selectedDestinationId ? '選択中' : '';
      button.append(label, state);
      button.addEventListener('click', () => {
        const changed = selectedDestinationId !== destination.id;
        const measurement = changed ? hooks.beginSwitch?.(destination.name) ?? null : null;
        saveDestinationId(destination.id);
        if (changed) loadDestination(destination.id, measurement);
        destinationDialog.close();
        if (!changed) destinationTrigger.focus({ preventScroll: true });
      });
      item.appendChild(button);
      fragment.appendChild(item);
    }
    destinationList.replaceChildren(fragment);
  }

  function updateDestinationLabel() {
    const destination = selectedDestination();
    routeDisplay.textContent = destination ? `池袋 → ${destination.name}` : '池袋 → 目的地不明';
    renderDestinationOptions();
  }

  function displayTimestamp(value) {
    return value ? metadataFormatter.format(new Date(value)) : '未取得';
  }

  function renderMetadata(diagnostics) {
    if (!diagnostics || !metadataEl) return;
    const values = [
      `${displayTimestamp(diagnostics.applicationStartsAt)} 〜 ${displayTimestamp(diagnostics.applicationEndsAt)}（終了日時は含まない）`,
      displayTimestamp(diagnostics.generatedAt),
      `${diagnostics.feedValidFrom} 〜 ${diagnostics.feedValidThrough}（両日を含む）`,
      displayTimestamp(diagnostics.gtfsUpdatedAt),
      displayTimestamp(diagnostics.odptUpdatedAt),
      displayTimestamp(diagnostics.webAppBuiltAt),
    ];
    const signature = values.join('|');
    if (signature === metadataSignature) return;
    metadataSignature = signature;
    [
      'meta-application-period', 'meta-generated-at', 'meta-feed-period',
      'meta-gtfs-updated', 'meta-odpt-updated', 'meta-webapp-built',
    ].forEach((id, index) => { elements[id].textContent = values[index]; });
    metadataEl.hidden = false;
  }

  function typeStyle(item) {
    if (item.kind === 'Fライナー') return 'type-brand';
    if (item.kind === '急行' || item.kind === '通勤急行') return 'type-express';
    if (item.typeSource === 'gtfs_stop_pattern') return 'type-supplement';
    if (item.typeSource === 'official_route_rule') return 'type-normal';
    if (item.typeSource === 'unknown') return 'type-unknown';
    return 'type-normal';
  }

  function renderGroups(groups, nowMs, serviceState) {
    const visible = groups.flatMap(group => group.items);
    const best = earliestVisible(groups);
    const signature = `${mode}|${directOnlyEl.checked}|${serviceState}|${visible.map(item => `${item.id}:${item.isLastDeparture === true}:${item.terminalBasis ?? ''}`).join(',')}|${best?.id ?? ''}`;
    if (signature !== selectedSignature) {
      const fragment = documentRef.createDocumentFragment();
      if (serviceState !== 'ended') {
        for (const group of groups) {
          const section = documentRef.createElement('section');
          section.className = 'line';
          for (const item of group.items) {
            const card = documentRef.createElement('article');
            card.className = `train${item.id === best?.id ? ' best' : ''}`;
            card.style.setProperty('--line-color', item.color);
            card.innerHTML = `<div class="primary"><div class="train-head"><span class="route"></span><span class="bestmark"></span></div><div class="depart"><span class="departure-text time-value"></span><span class="depart-suffix">発</span><span class="type-destination"><span class="type-label"></span><span class="destination-label"></span><span class="terminal-badge"></span></span></div><div class="sub"></div></div><div class="countwrap"><div class="minitxt">発車まで</div><div class="count"></div></div><div class="arrival-wrap"><div class="minitxt arrival-caption">到着</div><div class="arrival time-value"></div></div>`;
            card.querySelector('.route').textContent = item.line;
            card.querySelector('.bestmark').textContent = item.id === best?.id ? '● 最早着' : '';
            card.querySelector('.departure-text').textContent = item.departureText;
            const typeLabel = card.querySelector('.type-label');
            typeLabel.textContent = item.kind;
            typeLabel.className = `type-label ${typeStyle(item)}`;
            typeLabel.dataset.typeSource = item.typeSource;
            card.querySelector('.destination-label').textContent = `${item.destination}行`;
            card.querySelector('.terminal-badge').textContent = terminalBadgeText(item);
            card.querySelector('.sub').textContent = item.journeyKind === 'direct'
              ? '直通・乗換なし' : `小竹向原乗換・待ち約${Math.round(item.transfer.waitMinutes)}分`;
            card.querySelector('.arrival').textContent = item.arrivalText ?? '—';
            card.querySelector('.arrival-caption').textContent = '到着';
            card.dataset.departureAt = String(item.departureAtMs);
            section.appendChild(card);
          }
          fragment.appendChild(section);
        }
      }
      if (!visible.length || serviceState === 'ended') {
        const empty = documentRef.createElement('p');
        empty.className = serviceState === 'ended' ? 'empty terminal-ended' : 'empty';
        empty.setAttribute('role', 'status');
        empty.textContent = emptyBoardText(serviceState);
        fragment.appendChild(empty);
      }
      boardEl.replaceChildren(fragment);
      selectedSignature = signature;
    }
    for (const card of boardEl.querySelectorAll('[data-departure-at]')) {
      const { remaining, label } = countdownText(Number(card.dataset.departureAt), nowMs);
      const counter = card.querySelector('.count');
      counter.textContent = label;
      counter.classList.toggle('red', remaining <= 180);
    }
  }

  function tick(eventStarted = performanceClock(), measurement = null) {
    const nowMs = nowProvider();
    clock.textContent = clockFormatter.format(new Date(nowMs));
    if (loadFailure) {
      const renderStartedAt = measurement ? performanceClock() : null;
      setStatus(loadFailure, 'error');
      boardEl.replaceChildren();
      selectedSignature = '';
      hooks.onTick?.({ at: nowMs, eventToDomMs: performanceClock() - eventStarted, adapterMs: 0, selectionMs: 0, domMs: 0 });
      if (measurement) hooks.finishAfterRender?.(measurement, renderStartedAt, '読込エラー', loadFailure);
      return;
    }
    if (loading) {
      setStatus(`${selectedDestination()?.name ?? '目的地'}の時刻表を読み込んでいます…`, 'warning');
      boardEl.replaceChildren();
      selectedSignature = '';
      hooks.onTick?.({ at: nowMs, eventToDomMs: performanceClock() - eventStarted, adapterMs: 0, selectionMs: 0, domMs: 0 });
      return;
    }
    let adapterStartedAt = null;
    try {
      const adapterStarted = performanceClock();
      adapterStartedAt = adapterStarted;
      const result = buildBoard(prepared, { nowMs, directOnly: directOnlyEl.checked, mode,
        expectedProfile });
      const adapterMs = performanceClock() - adapterStarted;
      if (measurement) measurement.boardMs = adapterMs;
      const selectionStarted = performanceClock();
      const groups = selectPreviewGroups(result, mode);
      const selectionMs = performanceClock() - selectionStarted;
      if (measurement) measurement.selectionMs = selectionMs;
      const domStarted = performanceClock();
      const state = result.validity === 'valid' ? 'ok' : 'warning';
      setStatus(result.statusMessage, state);
      statusEl.title = result.periodText;
      renderMetadata(result.diagnostics);
      if (result.validity !== 'valid') {
        selectedSignature = '';
        boardEl.replaceChildren();
      } else {
        renderGroups(groups, nowMs, result.serviceState);
      }
      const domMs = performanceClock() - domStarted;
      hooks.onTick?.({ at: nowMs, eventToDomMs: performanceClock() - eventStarted, adapterMs, selectionMs, domMs });
      const outcome = result.validity === 'valid' ? '表示完了' : '表示停止';
      const message = result.validity === 'valid' ? null : result.statusMessage;
      if (measurement) hooks.finishAfterRender?.(measurement, domStarted, outcome, message);
    } catch {
      if (measurement && adapterStartedAt !== null && measurement.boardMs === null) {
        measurement.boardMs = performanceClock() - adapterStartedAt;
      }
      loadFailure = 'payloadの形式または必須メタデータを確認できません。プレビューを再生成してください。';
      tick(eventStarted, measurement);
    }
  }

  async function loadDestination(destinationId, measurement = null) {
    if (!DESTINATIONS.some(destination => destination.id === destinationId)) {
      void loadLatestDestination(destinationId);
      selectedDestinationId = destinationId;
      prepared = null;
      loading = false;
      loadFailure = '選択した目的地IDが不正です。氷川台へ戻ってください。';
      updateDestinationLabel();
      if (metadataEl) metadataEl.hidden = true;
      tick();
      return;
    }
    selectedDestinationId = destinationId;
    updateDestinationLabel();
    prepared = null;
    loadFailure = null;
    loading = true;
    selectedSignature = '';
    metadataSignature = '';
    if (metadataEl) metadataEl.hidden = true;
    boardEl.replaceChildren();
    tick();
    let result;
    try {
      result = await loadLatestDestination(destinationId);
    } catch {
      result = { prepared: null,
        failure: '実ダイヤpayloadを読み込めませんでした。ローカルpreviewを再生成してください。',
        stale: false, timings: null };
    }
    hooks.onLoad?.({
      at: Date.now(), destinationStationId: destinationId, stale: result.stale,
      ...(result.timings ?? {}),
    });
    if (measurement) measurement.timings = result.timings ?? null;
    if (result.stale) {
      if (measurement) hooks.onStale?.(measurement, measurement.timings);
      return;
    }
    prepared = result.prepared;
    loadFailure = result.failure;
    loading = false;
    if (prepared) preparedPayloadCache.set(destinationId, prepared);
    tick(measurement?.startedAt ?? performanceClock(), measurement);
  }

  destinationTrigger.addEventListener('click', () => {
    if (destinationDialog.open) return;
    destinationDialog.showModal();
    documentRef.body.classList.add('destination-modal-open');
    destinationList.querySelector(`[data-destination-id="${selectedDestinationId}"]`)?.focus({ preventScroll: true });
  });
  destinationClose.addEventListener('click', () => destinationDialog.close());
  destinationDialog.addEventListener('close', () => {
    documentRef.body.classList.remove('destination-modal-open');
    destinationTrigger.focus({ preventScroll: true });
  });
  destinationDialog.addEventListener('click', event => {
    if (event.target === destinationDialog) destinationDialog.close();
  });
  destinationDialog.addEventListener('keydown', event => {
    const options = [...destinationList.querySelectorAll('.destination-option')];
    const currentIndex = options.indexOf(documentRef.activeElement);
    if (currentIndex < 0 || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const nextIndex = event.key === 'Home' ? 0
      : event.key === 'End' ? options.length - 1
        : (currentIndex + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
    options[nextIndex].focus();
  });

  lineButton.addEventListener('click', () => {
    mode = 'line';
    saveDisplayMode(mode);
    updateModeButtons();
    tick();
  });
  departureButton.addEventListener('click', () => {
    mode = 'departure';
    saveDisplayMode(mode);
    updateModeButtons();
    tick();
  });
  directOnlyEl.addEventListener('change', () => tick());

  updateModeButtons();
  updateDestinationLabel();
  loadDestination(selectedDestinationId);
  windowRef.setInterval(() => tick(), 1000);

  return Object.freeze({
    tick,
    loadDestination,
    get fetchCount() { return fetchCount; },
    get cachedDestinationIds() { return preparedPayloadCache.keys(); },
  });
}
