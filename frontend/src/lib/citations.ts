import type { Citation } from '../types';

export const CITATION_PATTERN = /\[((?:Q|H|M|N|SEC|XBRL|S):[A-Za-z0-9.\-:_]+)\]/g;
const CITE_SCHEME = '#cite:';

const KIND_LABELS: Record<string, string> = {
  Q: 'Quote',
  H: 'Price history',
  M: 'Metrics',
  N: 'News',
  SEC: 'SEC filing',
  XBRL: 'SEC XBRL',
  S: 'Strategy',
};

export function citationKindLabel(id: string): string {
  const prefix = id.split(':', 1)[0] ?? '';
  return KIND_LABELS[prefix] ?? 'Citation';
}

export function citationDomId(messageId: string, citationId: string): string {
  const safe = citationId.replace(/[^A-Za-z0-9_-]/g, '_');
  return `src-${messageId}-${safe}`;
}

function stripCodeFromMarkdown(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`[^`\n]*`/g, '');
}

export function extractInlineCitationIds(markdown: string): string[] {
  const stripped = stripCodeFromMarkdown(markdown);
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const match of stripped.matchAll(CITATION_PATTERN)) {
    const id = match[1];
    if (id && !seen.has(id)) {
      seen.add(id);
      ordered.push(id);
    }
  }
  return ordered;
}

export function orderCitations(citations: Citation[], markdown: string): Citation[] {
  const byId = new Map<string, Citation>();
  for (const c of citations) {
    if (!byId.has(c.id)) byId.set(c.id, c);
  }
  const inlineIds = extractInlineCitationIds(markdown);
  const placed = new Set<string>();
  const result: Citation[] = [];

  for (const id of inlineIds) {
    const found = byId.get(id);
    if (found && !placed.has(id)) {
      placed.add(id);
      result.push(found);
    }
  }
  for (const c of citations) {
    if (!placed.has(c.id)) {
      placed.add(c.id);
      result.push(c);
    }
  }
  return result;
}

export function findUnresolvedCitations(markdown: string, citations: Citation[]): string[] {
  const known = new Set(citations.map((c) => c.id));
  return extractInlineCitationIds(markdown).filter((id) => !known.has(id));
}

export function parseCitationHref(href: string | undefined): string | null {
  if (!href) return null;
  if (href.startsWith('#cite:')) return href.slice('#cite:'.length) || null;
  if (href.startsWith('cite:')) return href.slice('cite:'.length) || null;
  return null;
}

export function safeUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  try {
    const parsed = new URL(raw);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.toString();
    }
    return null;
  } catch {
    return null;
  }
}

export function formatAsOf(asOf: string): string {
  const trimmed = asOf.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return trimmed;
  const dt = new Date(trimmed);
  if (Number.isNaN(dt.getTime())) return trimmed;
  return dt.toISOString().replace('.000Z', 'Z');
}

interface MdastNode {
  type: string;
  value?: string;
  url?: string;
  children?: MdastNode[];
}

function transformNode(node: MdastNode): void {
  if (!node.children || node.type === 'code' || node.type === 'inlineCode' || node.type === 'link') {
    return;
  }
  const nextChildren: MdastNode[] = [];
  for (const child of node.children) {
    if (child.type === 'text' && typeof child.value === 'string') {
      const text = child.value;
      let lastIndex = 0;
      let matched = false;
      for (const match of text.matchAll(CITATION_PATTERN)) {
        const full = match[0];
        const citeId = match[1];
        const idx = match.index ?? 0;
        if (!citeId) continue;
        matched = true;
        if (idx > lastIndex) {
          nextChildren.push({ type: 'text', value: text.slice(lastIndex, idx) });
        }
        nextChildren.push({
          type: 'link',
          url: `${CITE_SCHEME}${citeId}`,
          children: [{ type: 'text', value: full }],
        });
        lastIndex = idx + full.length;
      }
      if (matched) {
        if (lastIndex < text.length) {
          nextChildren.push({ type: 'text', value: text.slice(lastIndex) });
        }
      } else {
        nextChildren.push(child);
      }
    } else {
      transformNode(child);
      nextChildren.push(child);
    }
  }
  node.children = nextChildren;
}

export function remarkCitations() {
  return (tree: MdastNode) => {
    transformNode(tree);
  };
}
