import { useCallback, useEffect, useMemo, useState } from 'react';
import { citationDomId, findUnresolvedCitations, orderCitations } from '../lib/citations';
import type { AssistantMessage as AssistantMessageT, Citation } from '../types';
import { FactCheckBadge } from './FactCheckBadge';
import { FeedbackControls } from './FeedbackControls';
import { WarningIcon } from './icons';
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
      className={`ui-sheet ${blocked ? 'ui-card--danger' : ''}`}
    >
      <ThoughtTimeline thoughts={thoughts} active={streaming} />

      {blocked && (
        <div role="alert" className="ui-card ui-card--danger">
          <div className="ui-row">
            <WarningIcon />
            <h3>Request blocked by safety policy</h3>
          </div>
          {final?.block_reason && <p>{final.block_reason}</p>}
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
          <div className="ui-card" aria-hidden="true">
            <small className="text-secondary">Synthesizing research brief…</small>
          </div>
        )
      )}

      {status === 'error' && error && (
        <div role="alert" className="ui-card ui-card--danger">
          <div className="ui-row">
            <WarningIcon />
            <h3>Something went wrong</h3>
          </div>
          <p>{error.message}</p>
          <code>{error.code}</code>
        </div>
      )}

      {status === 'cancelled' && <small className="text-secondary">Generation stopped.</small>}

      {final && !blocked && (
        <SourcesPanel messageId={message.id} citations={ordered} highlight={highlight} unresolved={unresolved} />
      )}

      {!streaming && (
        <div
          className="ui-row--between"
          style={{ paddingTop: '12px', borderTop: '1px solid var(--border-subtle)' }}
        >
          <div className="ui-row">
            {final && !blocked && <FactCheckBadge factCheck={final.fact_check} />}
            <LatencyStats server={final?.latency ?? null} client={message.clientLatency} />
          </div>
          {final?.report_id && <FeedbackControls reportId={final.report_id} />}
        </div>
      )}
    </article>
  );
}
