import { createPreviewRuntime } from './preview_core.mjs';
import { PUBLIC_DATA_SCOPE } from './timetable_adapter.mjs';

/** Production bootstrap: callers may provide DOM surfaces, but cannot override profile or cache policy. */
export function startPublicPreview({ documentRef = document, windowRef = window } = {}) {
  return createPreviewRuntime({
    expectedProfile: PUBLIC_DATA_SCOPE,
    cacheMode: 'default',
    nowProvider: () => Date.now(),
    documentRef,
    windowRef,
  });
}

if (typeof document !== 'undefined') {
  try {
    startPublicPreview();
  } catch (error) {
    const status = document.getElementById('timetable-status');
    if (status) {
      status.textContent = 'プレビューを初期化できませんでした。ページを再読み込みしてください。';
      status.dataset.state = 'error';
    }
    console.error('public preview runtime initialization failed', error);
  }
}
