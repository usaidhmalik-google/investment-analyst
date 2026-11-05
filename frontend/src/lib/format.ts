let seq = 0;

export function localId(prefix = 'id'): string {
  seq += 1;
  return `${prefix}-${seq}-${Math.random().toString(36).slice(2, 8)}`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatAccuracy(accuracy: number | null | undefined): string {
  if (accuracy == null || !Number.isFinite(accuracy)) return '—';
  const pct = Math.max(0, Math.min(100, accuracy * 100));
  return Number.isInteger(pct) ? `${pct}%` : `${pct.toFixed(1)}%`;
}

export function humanize(value: string): string {
  const cleaned = value.trim().replace(/[_-]+/g, ' ');
  if (!cleaned) return '';
  return cleaned.replace(/\b\w/g, (ch) => ch.toUpperCase());
}
