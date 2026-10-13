import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, buildChatRequest, describeError, sendFeedback, streamChat } from './client';
import type { StreamEvent } from '../types';

function sseResponse(body: string, init: ResponseInit = {}): Response {
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
    ...init,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('buildChatRequest', () => {
  it('omits session_id when starting a new conversation', () => {
    expect(buildChatRequest('  hi  ', null, null)).toEqual({ message: 'hi', strategy: null });
  });

  it('includes session_id and strategy when present', () => {
    expect(buildChatRequest('hi', 's1', 'momentum')).toEqual({
      message: 'hi',
      session_id: 's1',
      strategy: 'momentum',
    });
  });
});

describe('streamChat', () => {
  it('POSTs the request and dispatches decoded events', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse(
        'event: session\ndata: {"session_id":"s1"}\n\n' +
          'event: thought\ndata: {"agent":"root","kind":"status","name":"routing","detail":"","elapsed_ms":5}\n\n' +
          'event: token\ndata: {"agent":"financial_analyst","text":"NVDA"}\n\n' +
          'event: final\ndata: {"report_id":"r1","session_id":"s1","response":"NVDA [Q:NVDA]"}\n\n',
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const events: StreamEvent[] = [];
    await streamChat({ message: 'hi', strategy: 'value' }, (e) => events.push(e));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/chat/stream');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ message: 'hi', strategy: 'value' });
    expect((init.headers as Record<string, string>).Accept).toBe('text/event-stream');
    expect(events.map((e) => e.type)).toEqual(['session', 'thought', 'token', 'final']);
  });

  it('throws ApiError with the FastAPI detail on HTTP errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Message too long' }), {
          status: 422,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );
    await expect(streamChat({ message: 'x', strategy: null }, () => {})).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
      message: 'Message too long',
    });
  });

  it('maps 403 to an authorization message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 403 })));
    const err = await streamChat({ message: 'x', strategy: null }, () => {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe('unauthorized');
  });
});

describe('sendFeedback', () => {
  it('trims and omits empty comments', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response('{"status":"ok"}', { status: 200 })));
    vi.stubGlobal('fetch', fetchMock);
    await sendFeedback({ report_id: 'r1', rating: 'up', comment: '   ' });
    await sendFeedback({ report_id: 'r1', rating: 'down', comment: ' wrong EPS ' });
    const bodies = fetchMock.mock.calls.map((c) => JSON.parse((c[1] as RequestInit).body as string) as unknown);
    expect(bodies).toEqual([
      { report_id: 'r1', rating: 'up' },
      { report_id: 'r1', rating: 'down', comment: 'wrong EPS' },
    ]);
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/feedback');
  });
});

describe('describeError', () => {
  it('maps fetch TypeErrors to a network error', () => {
    expect(describeError(new TypeError('Failed to fetch')).code).toBe('network_error');
  });
  it('passes ApiError through', () => {
    expect(describeError(new ApiError('nope', 500, 'internal'))).toEqual({ code: 'internal', message: 'nope' });
  });
});
