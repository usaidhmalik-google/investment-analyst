import { useCallback, useEffect, useMemo, useState } from 'react';
import { citationDomId, findUnresolvedCitations, orderCitations } from '../lib/citations';
import type { AssistantMessage as AssistantMessageT, Citation } from '../types';
import { FactCheckBadge } from './FactCheckBadge';
import { FeedbackControls } from './FeedbackControls';
import { AlertIcon, ShieldIcon } from './icons';
import { LatencyStats } from './LatencyStats';
import { MarkdownAnswer } from './MarkdownAnswer';
import { SourcesPanel } from './SourcesPanel';
import { ThoughtTimeline } from './ThoughtTimeline';

export function AssistantMessage({ message }: { message: AssistantMessageT }) {
  const { final, status, content, thoughts, error } = message;
  const streaming = status === 'streaming';
  const blocked = final?.blocked === true;
  const [highlight, setHighlight] = useState<{ id: string; nonce: number } | null>(null);

  const ordered = useMemo<Citation[]>(
    () => (final ? orderCitations(final.citations, final.response) : []),
    [final],
  );
  const citationIndex = useMemo(
    () => new Map(ordered.map((c, i) => [c.id, { n: i + 1, citation: c }])),
    [ordered],
  );
  const unresolved = useMemo(
    () => (final ? findUnresolvedCitations(final.response, final.citations) : []),
    [final],
  );

  const onCitationClick = useCallback((id: string) => {
    setHighlight((h) => ({ id, nonce: (h?.nonce ?? 0) + 1 }));
  }, []);

  // Scroll/focus after commit: the highlighted source entry is re-mounted
  // (keyed by nonce) to restart its flash animation.
  useEffect(() => {
    if (!highlight) return;
    const el = document.getElementById(citationDomId(message.id, highlight.id));
    if (!el) return;
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    el.scrollIntoView?.({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
    el.focus({ preventScroll: true });
  }, [highlight, message.id]);

  return (
    <article
      aria-label="Analyst response"
      aria-busy={streaming}
      className={[
        'rounded-xl border p-4 shadow-sm',
        blocked
          ? 'border-rose-300 bg-rose-50 dark:border-rose-500/40 dark:bg-rose-950/30'
          : 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900',
      ].join(' ')}
    >
      <ThoughtTimeline thoughts={thoughts} active={streaming} />

      {blocked && (
        <div role="alert" className="mb-2 flex items-start gap-2 text-sm text-rose-800 dark:text-rose-300">
          <ShieldIcon className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-semibold">Request blocked by safety policy</p>
            {final?.block_reason && <p className="text-xs opacity-90">{final.block_reason}</p>}
          </div>
        </div>
      )}

      {content ? (
        <MarkdownAnswer
          content={content}
          citationIndex={citationIndex}
          onCitationClick={onCitationClick}
          streaming={streaming}
        />
      ) : (
        streaming && (
          <div className="space-y-2" aria-hidden="true">
            <div className="h-3 w-3/4 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
            <div className="h-3 w-1/2 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
          </div>
        )
      )}

      {status === 'error' && error && (
        <div
          role="alert"
          className="mt-3 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800 dark:border-rose-500/30 dark:bg-rose-950/40 dark:text-rose-300"
        >
          <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-semibold">Something went wrong</p>
            <p>{error.message}</p>
            <p className="mt-0.5 font-mono text-[10px] opacity-70">{error.code}</p>
          </div>
        </div>
      )}

      {status === 'cancelled' && (
        <p className="mt-3 text-xs italic text-slate-500 dark:text-slate-400">Generation stopped.</p>
      )}

      {final && !blocked && (
        <SourcesPanel messageId={message.id} citations={ordered} highlight={highlight} unresolved={unresolved} />
      )}

      {!streaming && (
        <footer className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-100 pt-3 dark:border-slate-800">
          {final && !blocked && <FactCheckBadge factCheck={final.fact_check} />}
          <LatencyStats server={final?.latency ?? null} client={message.clientLatency} />
          {final?.report_id && (
            <div className="w-full">
              <FeedbackControls reportId={final.report_id} />
            </div>
          )}
        </footer>
      )}
    </article>
  );
}
