import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AssistantMessage as AssistantMessageT, ChatResponse } from '../types';
import { AssistantMessage } from './AssistantMessage';

const response: ChatResponse = {
  report_id: 'r1',
  session_id: 's1',
  response:
    '## NVIDIA weekly brief\n\nNVDA closed at **$181.20** [Q:NVDA], up 4.1% over 5 days [H:NVDA:5d]. ' +
    'Blackwell demand remains strong [N:NVDA:2].\n\n`[Q:CODE]` stays literal.',
  citations: [
    { id: 'H:NVDA:5d', type: 'history', title: 'NVDA 5-day history', source: 'Yahoo Finance', url: null, as_of: '2026-10-09' },
    {
      id: 'Q:NVDA',
      type: 'quote',
      title: 'NVIDIA Corporation real-time quote',
      source: 'Yahoo Finance',
      url: 'https://finance.yahoo.com/quote/NVDA',
      as_of: '2026-10-09T20:00:00Z',
    },
  ],
  fact_check: { verified: false, checked_numbers: 3, matched_numbers: 2, unverified_numbers: ['4.1'], accuracy: 0.6667 },
  tools_called: [],
  latency: { time_to_first_thought_ms: 850, time_to_first_token_ms: 3100, total_ms: 7900 },
  usage: null,
  blocked: false,
  block_reason: null,
};

const msg = (over: Partial<AssistantMessageT> = {}): AssistantMessageT => ({
  role: 'assistant',
  id: 'a1',
  status: 'done',
  content: response.response,
  thoughts: [{ agent: 'data_gatherer', kind: 'tool_call', name: 'get_stock_quote', detail: 'NVDA', elapsed_ms: 812 }],
  final: response,
  error: null,
  clientLatency: { firstThoughtMs: 900, firstTokenMs: 3200, totalMs: 8000 },
  ...over,
});

describe('AssistantMessage', () => {
  it('renders citation chips numbered by first appearance and a sources panel', () => {
    render(<AssistantMessage message={msg()} />);
    const chip1 = screen.getByRole('button', { name: /Source 1: NVIDIA Corporation real-time quote/ });
    expect(chip1).toHaveTextContent('1');
    expect(screen.getByRole('button', { name: /Source 2: NVDA 5-day history/ })).toHaveTextContent('2');
    // Unresolved inline id is still rendered as a chip and flagged.
    expect(screen.getByRole('button', { name: /News source N:NVDA:2/ })).toBeInTheDocument();
    expect(screen.getByText(/Referenced without a matching source/)).toBeInTheDocument();
    // Code spans are not converted.
    expect(screen.getByText('[Q:CODE]')).toBeInTheDocument();
    // Sources panel link
    expect(screen.getByRole('link', { name: /NVIDIA Corporation real-time quote/ })).toHaveAttribute(
      'href',
      'https://finance.yahoo.com/quote/NVDA',
    );
  });

  it('scrolls to and highlights the source when a chip is clicked', () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    render(<AssistantMessage message={msg()} />);
    fireEvent.click(screen.getByRole('button', { name: /Source 1:/ }));
    const li = document.getElementById('src-a1-Q_NVDA');
    expect(li).not.toBeNull();
    expect(scrollIntoView).toHaveBeenCalled();
    expect(li?.className).toMatch(/animate-flash/);
    expect(document.activeElement).toBe(li);
  });

  it('shows fact-check and server latency stats', () => {
    render(<AssistantMessage message={msg()} />);
    expect(screen.getByText(/1 unverified number/)).toBeInTheDocument();
    expect(screen.getByText(/66\.7% accuracy/)).toBeInTheDocument();
    expect(screen.getByText('850 ms')).toBeInTheDocument();
    expect(screen.getByText('7.9 s')).toBeInTheDocument();
  });

  it('renders the blocked style without sources or fact-check', () => {
    render(
      <AssistantMessage
        message={msg({
          content: 'I can’t help with that.',
          final: { ...response, response: 'I can’t help with that.', blocked: true, block_reason: 'Prompt injection detected' },
        })}
      />,
    );
    expect(screen.getByText('Request blocked by safety policy')).toBeInTheDocument();
    expect(screen.getByText('Prompt injection detected')).toBeInTheDocument();
    expect(screen.queryByText(/Sources/)).not.toBeInTheDocument();
    expect(screen.queryByText(/accuracy/)).not.toBeInTheDocument();
  });

  it('renders error state with client latency fallback', () => {
    render(
      <AssistantMessage
        message={msg({ status: 'error', final: null, content: '', error: { code: 'network_error', message: 'Could not reach' } })}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Could not reach');
    expect(screen.getByText('8.0 s')).toBeInTheDocument();
    expect(screen.queryByText(/Was this helpful/)).not.toBeInTheDocument();
  });
});
