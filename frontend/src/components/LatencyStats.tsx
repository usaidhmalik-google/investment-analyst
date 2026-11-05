import { formatMs } from '../lib/format';
import type { ClientLatency, Latency } from '../types';

interface Props {
  server: Latency | null;
  client: ClientLatency;
}

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
    <dl className="ui-row tabular-nums" aria-label="Response latency">
      {items.map(([label, title, v]) => (
        <div key={label} className="ui-row" title={title}>
          <dt className="ui-eyebrow">{label}:</dt>
          <dd className="text-sm tabular-nums">{formatMs(v)}</dd>
        </div>
      ))}
    </dl>
  );
}
