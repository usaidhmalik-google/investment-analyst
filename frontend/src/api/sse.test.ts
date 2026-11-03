import { describe, expect, it } from 'vitest';
import { decodeStreamEvent, parseSse, readSseStream, SseParser } from './sse';
import type { StreamEvent } from '../types';

function streamOf(chunks: Array<string | Uint8Array>): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(typeof c === 'string' ? enc.encode(c) : c);
      controller.close();
    },
  });
}

describe('SseParser', () => {
  it('parses a single complete event', () => {
    expect(parseSse('event: session\ndata: {"session_id":"s1"}\n\n')).toEqual([
      { event: 'session', data: '{"session_id":"s1"}' },
    ]);
  });

  it('parses multiple events in one chunk', () => {
    const evs = parseSse('event: a\ndata: 1\n\nevent: b\ndata: 2\n\n');
    expect(evs.map((e) => [e.event, e.data])).toEqual([
      ['a', '1'],
      ['b', '2'],
    ]);
  });

  it('defaults the event type to "message"', () => {
    expect(parseSse('data: hi\n\n')).toEqual([{ event: 'message', data: 'hi' }]);
  });

  it('joins multi-line data with newlines', () => {
    expect(parseSse('data: line1\ndata: line2\n\n')[0]?.data).toBe('line1\nline2');
  });

  it('strips exactly one leading space from values', () => {
    expect(parseSse('data:  two\n\n')[0]?.data).toBe(' two');
    expect(parseSse('data:none\n\n')[0]?.data).toBe('none');
  });

  it('ignores comments and keep-alives', () => {
    expect(parseSse(': ping\n\n:keepalive\nevent: x\ndata: 1\n\n')).toEqual([{ event: 'x', data: '1' }]);
  });

  it('ignores events without data and resets the type', () => {
    expect(parseSse('event: orphan\n\ndata: 1\n\n')).toEqual([{ event: 'message', data: '1' }]);
  });

  it('handles CRLF and CR line endings', () => {
    expect(parseSse('event: a\r\ndata: 1\r\n\r\n')).toEqual([{ event: 'a', data: '1' }]);
    expect(parseSse('event: b\rdata: 2\r\r')).toEqual([{ event: 'b', data: '2' }]);
  });

  it('handles a CRLF split across chunks without emitting a spurious blank line', () => {
    const p = new SseParser();
    expect(p.push('event: a\r')).toEqual([]);
    expect(p.push('\ndata: 1\r')).toEqual([]);
    expect(p.push('\n\r')).toEqual([]);
    expect(p.push('\n')).toEqual([{ event: 'a', data: '1' }]);
  });

  it('reassembles events split at arbitrary byte boundaries', () => {
    const full =
      'event: session\ndata: {"session_id":"abc"}\n\n' +
      'event: token\ndata: {"agent":"financial_analyst","text":"Hello [Q:NVDA]"}\n\n';
    for (let i = 1; i < full.length; i++) {
      const p = new SseParser();
      const evs = [...p.push(full.slice(0, i)), ...p.push(full.slice(i)), ...p.flush()];
      expect(evs).toHaveLength(2);
      expect(evs[1]?.data).toContain('[Q:NVDA]');
    }
  });

  it('flushes a trailing event with no terminating blank line', () => {
    const p = new SseParser();
    expect(p.push('event: final\ndata: {"x":1}')).toEqual([]);
    expect(p.flush()).toEqual([{ event: 'final', data: '{"x":1}' }]);
  });

  it('tracks the last event id', () => {
    expect(parseSse('id: 7\ndata: x\n\n')[0]).toEqual({ event: 'message', data: 'x', id: '7' });
  });

  it('treats a field with no colon as an empty value', () => {
    expect(parseSse('data\n\n')).toEqual([{ event: 'message', data: '' }]);
  });
});

describe('decodeStreamEvent', () => {
  it('decodes session events', () => {
    expect(decodeStreamEvent({ event: 'session', data: '{"session_id":"s"}' })).toEqual({
      type: 'session',
      data: { session_id: 's' },
    });
  });

  it('decodes thought events with defaults', () => {
    const ev = decodeStreamEvent({
      event: 'thought',
      data: '{"agent":"data_gatherer","kind":"tool_call","name":"get_stock_quote","detail":"NVDA","elapsed_ms":812}',
    });
    expect(ev).toEqual({
      type: 'thought',
      data: { agent: 'data_gatherer', kind: 'tool_call', name: 'get_stock_quote', detail: 'NVDA', elapsed_ms: 812 },
    });
    const sparse = decodeStreamEvent({ event: 'thought', data: '{"agent":"root"}' });
    expect(sparse?.type === 'thought' && sparse.data).toEqual({
      agent: 'root',
      kind: 'status',
      name: '',
      detail: '',
      elapsed_ms: 0,
    });
  });

  it('decodes token events and rejects tokens without text', () => {
    expect(decodeStreamEvent({ event: 'token', data: '{"agent":"a","text":"hi"}' })).toEqual({
      type: 'token',
      data: { agent: 'a', text: 'hi' },
    });
    expect(decodeStreamEvent({ event: 'token', data: '{"agent":"a"}' })).toBeNull();
  });

  it('decodes final events and normalizes missing fields', () => {
    const ev = decodeStreamEvent({
      event: 'final',
      data: JSON.stringify({ report_id: 'r1', session_id: 's1', response: 'ok' }),
    });
    expect(ev?.type).toBe('final');
    if (ev?.type === 'final') {
      expect(ev.data.citations).toEqual([]);
      expect(ev.data.tools_called).toEqual([]);
      expect(ev.data.fact_check).toBeNull();
      expect(ev.data.blocked).toBe(false);
      expect(ev.data.block_reason).toBeNull();
    }
  });

  it('decodes error events with fallbacks', () => {
    expect(decodeStreamEvent({ event: 'error', data: '{"code":"upstream","message":"boom"}' })).toEqual({
      type: 'error',
      data: { code: 'upstream', message: 'boom' },
    });
    const ev = decodeStreamEvent({ event: 'error', data: '{}' });
    expect(ev?.type === 'error' && ev.data.code).toBe('unknown_error');
  });

  it('returns null for malformed JSON, non-objects and unknown events', () => {
    expect(decodeStreamEvent({ event: 'token', data: '{not json' })).toBeNull();
    expect(decodeStreamEvent({ event: 'token', data: '"str"' })).toBeNull();
    expect(decodeStreamEvent({ event: 'heartbeat', data: '{}' })).toBeNull();
  });
});

describe('readSseStream', () => {
  it('decodes a chunked byte stream into typed events, including split UTF-8', async () => {
    const enc = new TextEncoder();
    const payload = enc.encode('event: token\ndata: {"agent":"a","text":"€ up 3%"}\n\n');
    // Split inside the 3-byte "€" sequence.
    const euroAt = payload.indexOf(0xe2);
    const events: StreamEvent[] = [];
    await readSseStream(
      streamOf([
        'event: session\ndata: {"session_id":"s1"}\n\n: ping\n\n',
        payload.slice(0, euroAt + 1),
        payload.slice(euroAt + 1),
        'event: unknown\ndata: {}\n\n',
        'event: final\ndata: {"report_id":"r","session_id":"s1","response":"done"}',
      ]),
      (e) => events.push(e),
    );
    expect(events.map((e) => e.type)).toEqual(['session', 'token', 'final']);
    expect(events[1]?.type === 'token' && events[1].data.text).toBe('€ up 3%');
  });
});
