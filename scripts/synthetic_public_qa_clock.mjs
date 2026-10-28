/** QA-only clock provider; this module is copied beside the harness shell, never into an artifact. */
export function createQaClock({ startAt, mode = 'fixed', monotonicNow = () => performance.now() } = {}) {
  if (!Number.isFinite(startAt)) throw new TypeError('finite QA startAt is required');
  if (mode !== 'fixed' && mode !== 'advancing') throw new TypeError('QA clock mode must be fixed or advancing');
  if (typeof monotonicNow !== 'function') throw new TypeError('monotonicNow must be a function');
  const startedAt = monotonicNow();
  if (!Number.isFinite(startedAt)) throw new TypeError('monotonic clock must return a finite number');
  return () => mode === 'fixed' ? startAt : startAt + Math.max(0, monotonicNow() - startedAt);
}
