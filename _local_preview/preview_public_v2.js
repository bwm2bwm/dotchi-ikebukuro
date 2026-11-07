import { createPreviewRuntime } from './preview_core.mjs';
import { V2_PROFILE, V2_PUBLIC_ADAPTER } from './odpt_public_runtime.mjs';

/** Public clock and release policy are fixed; QA controls are never imported. */
export function startOdptPublicPreview({ documentRef = document, windowRef = window } = {}) {
  if (documentRef.querySelector('meta[name="dotchi-data-mode"]')?.content !== 'release-managed'
      || documentRef.querySelector('meta[name="dotchi-payload-profile"]')?.content !== V2_PROFILE) {
    throw new TypeError('explicit v2 release-managed shell required');
  }
  for (const id of ['publication-information', 'publication-provider', 'publication-source',
    'publication-retrieved', 'publication-period', 'publication-contact', 'publication-contact-unset']) {
    if (!documentRef.getElementById(id)) throw new TypeError('publication information is incomplete');
  }
  const contact = documentRef.getElementById('publication-contact');
  const url = contact.dataset.contactUrl ?? '';
  if (url) {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password) throw new TypeError('contact must be an HTTPS URL');
    contact.setAttribute('href', parsed.href);
    contact.hidden = false;
    documentRef.getElementById('publication-contact-unset').hidden = true;
  }
  return createPreviewRuntime({ expectedProfile: V2_PROFILE, cacheMode: 'default', releaseManaged: true,
    releaseAdapter: V2_PUBLIC_ADAPTER, nowProvider: () => Date.now(), documentRef, windowRef });
}

if (typeof document !== 'undefined') {
  try { startOdptPublicPreview(); }
  catch {
    document.getElementById('board')?.replaceChildren();
    const status = document.getElementById('timetable-status');
    if (status) { status.textContent = '時刻表を初期化できませんでした。ページを再読み込みしてください。'; status.dataset.state = 'error'; }
  }
}
