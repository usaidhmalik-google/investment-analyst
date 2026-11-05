import { formatMs, humanize } from '../lib/format';
import type { ThoughtEventData } from '../types';
import { ArrowRightLeftIcon, DatabaseIcon, DotIcon, ToolIcon } from './icons';

interface Props {
  thoughts: ThoughtEventData[];
  active: boolean;
}

function KindIcon({ kind }: { kind: string }) {
  switch (kind) {
    case 'tool_call':
      return <ToolIcon />;
    case 'tool_result':
      return <DatabaseIcon />;
    case 'agent_transfer':
      return <ArrowRightLeftIcon />;
    default:
      return <DotIcon />;
  }
}

function describe(t: ThoughtEventData): string {
  switch (t.kind) {
    case 'tool_call':
      return `Calling ${t.name}`;
    case 'tool_result':
      return `Received ${t.name}`;
    case 'agent_transfer':
      return `Handing off to ${humanize(t.name)}`;
    default:
      return t.name ? humanize(t.name) : 'Working';
  }
}

/** Layer 3 Progressive Disclosure: collapsed-by-default after streaming, open while streaming. */
export function ThoughtTimeline({ thoughts, active }: Props) {
  if (thoughts.length === 0 && !active) return null;
  const last = thoughts[thoughts.length - 1];

  return (
    <details className="ui-disclosure" open={active}>
      <summary>
        {active ? (
          <span>{last ? describe(last) : 'Analyzing your request'}…</span>
        ) : (
          <span>
            Agent execution trace · {thoughts.length} step{thoughts.length === 1 ? '' : 's'}
          </span>
        )}
      </summary>
      <div className="ui-disclosure-body" aria-live="polite">
        {thoughts.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>Specialist Agent</th>
                <th>Action</th>
                <th>Detail</th>
                <th className="is-num">Elapsed</th>
              </tr>
            </thead>
            <tbody>
              {thoughts.map((t, i) => (
                <tr key={i}>
                  <td>
                    <div className="ui-row">
                      <KindIcon kind={t.kind} />
                      <span>{humanize(t.agent || 'agent')}</span>
                    </div>
                  </td>
                  <td>{describe(t)}</td>
                  <td>
                    <code>{t.detail || '—'}</code>
                  </td>
                  <td className="is-num">+{formatMs(t.elapsed_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <small className="text-secondary">Waiting for the first agent step…</small>
        )}
      </div>
    </details>
  );
}
