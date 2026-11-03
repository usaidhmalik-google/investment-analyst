import { memo, useMemo, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { citationKindLabel, parseCitationHref, remarkCitations, safeUrl } from '../lib/citations';
import type { Citation } from '../types';

interface Props {
  content: string;
  /** Citations keyed by id with their 1-based display number. */
  citationIndex: Map<string, { n: number; citation: Citation }>;
  onCitationClick: (id: string) => void;
  streaming?: boolean;
}

interface ChipProps {
  id: string;
  entry: { n: number; citation: Citation } | undefined;
  onClick: (id: string) => void;
}

export function CitationChip({ id, entry, onClick }: ChipProps) {
  const label = entry
    ? `Source ${entry.n}: ${entry.citation.title} (${entry.citation.source})`
    : `${citationKindLabel(id)} source ${id}`;
  return (
    <sup className="mx-[1px]">
      <button
        type="button"
        onClick={() => onClick(id)}
        title={entry ? `${entry.citation.title} — ${entry.citation.source} [${id}]` : id}
        aria-label={label}
        data-citation-id={id}
        className={[
          'inline-flex h-4 min-w-[1rem] items-center justify-center rounded px-1 align-baseline font-mono text-[10px] font-semibold leading-none no-underline transition',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500',
          entry
            ? 'bg-brand-100 text-brand-800 hover:bg-brand-200 dark:bg-brand-500/20 dark:text-brand-200 dark:hover:bg-brand-500/35'
            : 'bg-slate-200 text-slate-600 hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-300',
        ].join(' ')}
      >
        {entry ? entry.n : id}
      </button>
    </sup>
  );
}

function MarkdownAnswerImpl({ content, citationIndex, onCitationClick, streaming }: Props) {
  const components = useMemo<Components>(
    () => ({
      a({ href, children }) {
        const citeId = parseCitationHref(href);
        if (citeId) {
          return <CitationChip id={citeId} entry={citationIndex.get(citeId)} onClick={onCitationClick} />;
        }
        const url = safeUrl(href);
        if (!url) return <span>{children as ReactNode}</span>;
        return (
          <a href={url} target="_blank" rel="noopener noreferrer">
            {children as ReactNode}
          </a>
        );
      },
      table({ children }) {
        return (
          <div className="not-prose my-4 overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
            <table className="w-full border-collapse text-left text-xs tabular-nums [&_td]:border-t [&_td]:border-slate-200 [&_td]:px-3 [&_td]:py-1.5 [&_th]:bg-slate-50 [&_th]:px-3 [&_th]:py-2 [&_th]:font-semibold dark:[&_td]:border-slate-700 dark:[&_th]:bg-slate-800/60">
              {children}
            </table>
          </div>
        );
      },
      img() {
        // Model output should never pull remote images.
        return null;
      },
    }),
    [citationIndex, onCitationClick],
  );

  return (
    <div
      className={[
        'prose prose-sm prose-slate max-w-none dark:prose-invert',
        'prose-headings:font-semibold prose-headings:tracking-tight prose-h2:mt-5 prose-h2:text-base prose-h3:text-sm',
        'prose-a:text-brand-600 dark:prose-a:text-brand-400 prose-strong:font-semibold',
        'prose-li:my-0.5 prose-p:leading-relaxed tabular-nums',
        streaming ? 'streaming-caret' : '',
      ].join(' ')}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkCitations]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

export const MarkdownAnswer = memo(MarkdownAnswerImpl);
