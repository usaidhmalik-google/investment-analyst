import { citationDomId, citationKindLabel, formatAsOf, safeUrl } from '../lib/citations';
import type { Citation } from '../types';
import { ExternalLinkIcon } from './icons';

interface Props {
  messageId: string;
  citations: Citation[];
  /** Citation currently highlighted plus a nonce to retrigger the animation. */
  highlight: { id: string; nonce: number } | null;
  unresolved: string[];
}

export function SourcesPanel({ messageId, citations, highlight, unresolved }: Props) {
  if (citations.length === 0 && unresolved.length === 0) return null;
  const headingId = `${messageId}-sources`;

  return (
    <section aria-labelledby={headingId} className="ui-stack">
      <h3 id={headingId} className="ui-eyebrow">
        Sources ({citations.length})
      </h3>

      <ol className="ui-stack" style={{ listStyle: 'none' }}>
        {citations.map((c, i) => {
          const url = safeUrl(c.url);
          const active = highlight?.id === c.id;
          return (
            <li
              key={active ? `${c.id}-${highlight.nonce}` : c.id}
              id={citationDomId(messageId, c.id)}
              tabIndex={-1}
              className={`ui-card ${active ? 'animate-flash' : ''}`}
            >
              <div className="ui-row--between">
                <div className="ui-row" style={{ flex: 1 }}>
                  <span className="ui-badge ui-badge--primary">{i + 1}</span>
                  {url ? (
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontWeight: 500, color: 'var(--text-primary)', textDecoration: 'underline', textUnderlineOffset: '3px' }}
                    >
                      {c.title}{' '}
                      <ExternalLinkIcon />
                      <span className="sr-only">(opens in a new tab)</span>
                    </a>
                  ) : (
                    <strong>{c.title}</strong>
                  )}
                </div>
                <code>{c.id}</code>
              </div>

              <div className="ui-row text-secondary">
                <small>{c.source}</small>
                {c.as_of && (
                  <small>
                    · as of <time dateTime={c.as_of}>{formatAsOf(c.as_of)}</time>
                  </small>
                )}
                <small>· {citationKindLabel(c.id)}</small>
              </div>
            </li>
          );
        })}
      </ol>

      {unresolved.length > 0 && (
        <small className="text-secondary">
          Referenced without a matching source:{' '}
          {unresolved.map((id) => (
            <code key={id}>{id} </code>
          ))}
        </small>
      )}
    </section>
  );
}
