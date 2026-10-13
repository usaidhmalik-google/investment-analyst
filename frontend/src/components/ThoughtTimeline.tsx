import { useEffect, useId, useState } from 'react';
import { formatMs, humanize } from '../lib/format';
import type { ThoughtEventData } from '../types';
import { ArrowRightLeftIcon, ChevronIcon, DatabaseIcon, DotIcon, ToolIcon } from './icons';

interface Props {
  thoughts: ThoughtEventData[];
  active: boolean;
}

function KindIcon({ kind }: { kind: string }) {
  const cls = 'h-3.5 w-3.5';
  switch (kind) {
    case 'tool_call':
      return <ToolIcon className={cls} />;
    case 'tool_result':
      return <DatabaseIcon className={cls} />;
    case 'agent_transfer':
      return <ArrowRightLeftIcon className={cls} />;
    default:
      return <DotIcon className={cls} />;
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

/** Live "agent thoughts" timeline; open while streaming, collapsible after. */
export function ThoughtTimeline({ thoughts, active }: Props) {
  const [open, setOpen] = useState(active);
  const panelId = useId();
  useEffect(() => {
    setOpen(active);
  }, [active]);

  if (thoughts.length === 0 && !active) return null;
  const last = thoughts[thoughts.length - 1];

  return (
    <div className="mb-3 rounded-lg border border-slate-200 bg-slate-50/70 dark:border-slate-800 dark:bg-slate-900/50">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white"
      >
        <ChevronIcon className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-90' : ''}`} />
        {active ? (
          <span className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-brand-500" />
            </span>
            {last ? describe(last) : 'Analyzing your request'}…
          </span>
        ) : (
          <span>
            Agent activity · {thoughts.length} step{thoughts.length === 1 ? '' : 's'}
          </span>
        )}
      </button>
      {open && (
        <ol id={panelId} aria-live="polite" className="max-h-64 space-y-1 overflow-y-auto px-3 pb-3 text-xs">
          {thoughts.map((t, i) => (
            <li key={i} className="flex items-start gap-2">
              <span className="mt-0.5 text-slate-400 dark:text-slate-500">
                <KindIcon kind={t.kind} />
              </span>
              <span className="w-14 shrink-0 font-mono tabular-nums text-slate-400 dark:text-slate-500">
                +{formatMs(t.elapsed_ms)}
              </span>
              <span className="shrink-0 rounded bg-slate-200 px-1.5 py-[1px] text-[10px] font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                {humanize(t.agent || 'agent')}
              </span>
              <span className="min-w-0 flex-1 text-slate-700 dark:text-slate-300">
                {describe(t)}
                {t.detail && (
                  <span className="ml-1 break-words font-mono text-[11px] text-slate-500 dark:text-slate-400">
                    {t.detail}
                  </span>
                )}
              </span>
            </li>
          ))}
          {thoughts.length === 0 && <li className="text-slate-400">Waiting for the first agent step…</li>}
        </ol>
      )}
    </div>
  );
}
