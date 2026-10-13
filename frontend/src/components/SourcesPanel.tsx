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
    <section aria-labelledby={headingId} className="mt-4 rounded-lg border border-slate-200 dark:border-slate-800">
      <h3
        id={headingId}
        className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:text-slate-400"
      >
        Sources <span className="font-normal normal-case">({citations.length})</span>
      </h3>
      <ol className="divide-y divide-slate-100 dark:divide-slate-800/80">
        {citations.map((c, i) => {
          const url = safeUrl(c.url);
          const active = highlight?.id === c.id;
          return (
            <li
              key={active ? `${c.id}-${highlight.nonce}` : c.id}
              id={citationDomId(messageId, c.id)}
              tabIndex={-1}
              className={[
                'flex scroll-mt-24 gap-3 px-3 py-2 text-xs outline-none',
                active ? 'animate-flash ring-1 ring-inset ring-brand-400/60' : '',
              ].join(' ')}
            >
              <span className="mt-0.5 inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded bg-brand-100 px-1 font-mono text-[10px] font-semibold text-brand-800 dark:bg-brand-500/20 dark:text-brand-200">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  {url ? (
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 font-medium text-slate-900 hover:text-brand-600 hover:underline dark:text-slate-100 dark:hover:text-brand-400"
                    >
                      {c.title}
                      <ExternalLinkIcon className="h-3 w-3 shrink-0" />
                      <span className="sr-only">(opens in a new tab)</span>
                    </a>
                  ) : (
                    <span className="font-medium text-slate-900 dark:text-slate-100">{c.title}</span>
                  )}
                </div>
                <div className="mt-0.5 flex flex-wrap gap-x-2 text-slate-500 dark:text-slate-400">
                  <span>{c.source}</span>
                  {c.as_of && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span>
                        as of <time dateTime={c.as_of}>{formatAsOf(c.as_of)}</time>
                      </span>
                    </>
                  )}
                  <span aria-hidden="true">·</span>
                  <span>{citationKindLabel(c.id)}</span>
                  <code className="font-mono text-[10px] text-slate-400 dark:text-slate-500">{c.id}</code>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
      {unresolved.length > 0 && (
        <p className="border-t border-slate-200 px-3 py-2 text-[11px] text-amber-700 dark:border-slate-800 dark:text-amber-400">
          Referenced without a matching source: {unresolved.map((id) => <code key={id} className="mx-0.5 font-mono">{id}</code>)}
        </p>
      )}
    </section>
  );
}
