import { formatMs } from '../lib/format';
import type { ClientLatency, Latency } from '../types';
import { ClockIcon } from './icons';

interface Props {
  server: Latency | null;
  client: ClientLatency;
}

/**
 * Per-answer latency. Server-reported values (from `final.latency`) are
 * preferred; client-measured values are used as a fallback (e.g. on error).
 */
export function LatencyStats({ server, client }: Props) {
  const thought = server?.time_to_first_thought_ms ?? client.firstThoughtMs;
  const token = server?.time_to_first_token_ms ?? client.firstTokenMs;
  const total = server?.total_ms ?? client.totalMs;
  if (thought == null && token == null && total == null) return null;

  const items: Array<[string, string, number | null]> = [
    ['First thought', 'Time to first agent thought', thought],
    ['First token', 'Time to first answer token', token],
    ['Total', 'Total response time', total],
  ];

  return (
    <dl
      className="inline-flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400"
      aria-label="Response latency"
    >
      <ClockIcon className="h-3.5 w-3.5" />
      {items.map(([label, title, v]) => (
        <div key={label} className="inline-flex gap-1" title={title}>
          <dt>{label}</dt>
          <dd className="font-mono tabular-nums text-slate-700 dark:text-slate-300">{formatMs(v)}</dd>
        </div>
      ))}
    </dl>
  );
}
