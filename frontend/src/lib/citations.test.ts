import { describe, expect, it } from 'vitest';
import {
  citationDomId,
  citationKindLabel,
  extractInlineCitationIds,
  findUnresolvedCitations,
  formatAsOf,
  orderCitations,
  parseCitationHref,
  safeUrl,
} from './citations';
import { formatAccuracy, formatMs, humanize, localId } from './format';

describe('citations and format helpers', () => {
  it('extracts inline citation ids ignoring code spans and orders citations', () => {
    const md = 'Price is $180 [Q:NVDA] and `[Q:IGNORED]` plus [H:NVDA:5d] and [N:NVDA:1].';
    expect(extractInlineCitationIds(md)).toEqual(['Q:NVDA', 'H:NVDA:5d', 'N:NVDA:1']);

    const ordered = orderCitations(
      [
        { id: 'H:NVDA:5d', type: 'history', title: 'Hist', source: 'Yahoo', url: null, as_of: '2026-09-15' },
        { id: 'Q:NVDA', type: 'quote', title: 'Quote', source: 'Yahoo', url: null, as_of: '2026-09-15' },
      ],
      md,
    );
    expect(ordered.map((c) => c.id)).toEqual(['Q:NVDA', 'H:NVDA:5d']);
    expect(findUnresolvedCitations(md, ordered)).toEqual(['N:NVDA:1']);
  });

  it('validates safe urls and formats labels', () => {
    expect(safeUrl('https://sec.gov/edgar')).toBe('https://sec.gov/edgar');
    expect(safeUrl('javascript:alert(1)')).toBeNull();
    expect(parseCitationHref('cite:Q:NVDA')).toBe('Q:NVDA');
    expect(parseCitationHref('https://sec.gov')).toBeNull();
    expect(citationDomId('m1', 'Q:NVDA')).toBe('src-m1-Q_NVDA');
    expect(citationKindLabel('XBRL:NVDA')).toBe('SEC XBRL');
    expect(formatAsOf('2026-09-15')).toBe('2026-09-15');
  });

  it('formats latency, accuracy, and humanized strings', () => {
    expect(formatMs(null)).toBe('—');
    expect(formatMs(420)).toBe('420 ms');
    expect(formatMs(2450)).toBe('2.5 s');
    expect(formatAccuracy(1)).toBe('100%');
    expect(formatAccuracy(0.6667)).toBe('66.7%');
    expect(humanize('sec_filing_parser')).toBe('Sec Filing Parser');
    expect(localId('u')).toMatch(/^u-\d+-/);
  });
});
