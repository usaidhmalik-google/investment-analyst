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
    <button
      type="button"
      onClick={() => onClick(id)}
      title={entry ? `${entry.citation.title} — ${entry.citation.source} [${id}]` : id}
      aria-label={label}
      data-citation-id={id}
      className="ui-btn ui-cite-chip"
    >
      {entry ? entry.n : id}
    </button>
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
        return <table>{children}</table>;
      },
      img() {
        return null;
      },
    }),
    [citationIndex, onCitationClick],
  );

  return (
    <div className={`ui-markdown ${streaming ? 'streaming-caret' : ''}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkCitations]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

export const MarkdownAnswer = memo(MarkdownAnswerImpl);
