import { describe, expect, it } from 'vitest';
import type { AssistantMessage, ChatResponse } from '../types';
import { chatReducer, initialChatState, type ChatState } from './chatReducer';

const final = (over: Partial<ChatResponse> = {}): ChatResponse => ({
  report_id: 'r1',
  session_id: 's1',
  response: 'Final [Q:NVDA]',
  citations: [],
  fact_check: null,
  tools_called: [],
  latency: null,
  usage: null,
  blocked: false,
  block_reason: null,
  ...over,
});

const started = (): ChatState =>
  chatReducer(initialChatState, { type: 'start', userId: 'u1', assistantId: 'a1', content: 'hi', strategy: 'value' });

const assistant = (s: ChatState) => s.messages.find((m) => m.role === 'assistant') as AssistantMessage;

describe('chatReducer', () => {
  it('start appends a user and a streaming assistant message', () => {
    const s = started();
    expect(s.pendingId).toBe('a1');
    expect(s.messages.map((m) => m.role)).toEqual(['user', 'assistant']);
    expect(assistant(s).status).toBe('streaming');
  });

  it('records session, thoughts and tokens with first-event latencies', () => {
    let s = started();
    s = chatReducer(s, { type: 'session', sessionId: 's1' });
    s = chatReducer(s, {
      type: 'thought',
      id: 'a1',
      atMs: 100,
      thought: { agent: 'root', kind: 'status', name: 'x', detail: '', elapsed_ms: 90 },
    });
    s = chatReducer(s, {
      type: 'thought',
      id: 'a1',
      atMs: 200,
      thought: { agent: 'root', kind: 'status', name: 'y', detail: '', elapsed_ms: 190 },
    });
    s = chatReducer(s, { type: 'token', id: 'a1', text: 'Hel', atMs: 300 });
    s = chatReducer(s, { type: 'token', id: 'a1', text: 'lo', atMs: 400 });
    const a = assistant(s);
    expect(s.sessionId).toBe('s1');
    expect(a.thoughts).toHaveLength(2);
    expect(a.content).toBe('Hello');
    expect(a.clientLatency).toEqual({ firstThoughtMs: 100, firstTokenMs: 300, totalMs: null });
  });

  it('final replaces streamed content and clears pending', () => {
    let s = started();
    s = chatReducer(s, { type: 'token', id: 'a1', text: 'partial', atMs: 10 });
    s = chatReducer(s, { type: 'final', id: 'a1', response: final(), atMs: 500 });
    const a = assistant(s);
    expect(a.status).toBe('done');
    expect(a.content).toBe('Final [Q:NVDA]');
    expect(a.final?.report_id).toBe('r1');
    expect(a.clientLatency.totalMs).toBe(500);
    expect(s.pendingId).toBeNull();
    expect(s.sessionId).toBe('s1');
  });

  it('ignores tokens after final', () => {
    let s = started();
    s = chatReducer(s, { type: 'final', id: 'a1', response: final(), atMs: 5 });
    s = chatReducer(s, { type: 'token', id: 'a1', text: 'late', atMs: 6 });
    expect(assistant(s).content).toBe('Final [Q:NVDA]');
  });

  it('error keeps partial content and marks error', () => {
    let s = started();
    s = chatReducer(s, { type: 'token', id: 'a1', text: 'partial', atMs: 10 });
    s = chatReducer(s, { type: 'error', id: 'a1', error: { code: 'x', message: 'boom' }, atMs: 20 });
    const a = assistant(s);
    expect(a.status).toBe('error');
    expect(a.content).toBe('partial');
    expect(a.error?.message).toBe('boom');
    expect(s.pendingId).toBeNull();
  });

  it('error after final does not clobber the final answer', () => {
    let s = started();
    s = chatReducer(s, { type: 'final', id: 'a1', response: final(), atMs: 5 });
    s = chatReducer(s, { type: 'error', id: 'a1', error: { code: 'x', message: 'late' }, atMs: 6 });
    expect(assistant(s).status).toBe('done');
  });

  it('end without final flags an incomplete stream', () => {
    let s = started();
    s = chatReducer(s, { type: 'end', id: 'a1', atMs: 50 });
    expect(assistant(s).status).toBe('error');
    expect(assistant(s).error?.code).toBe('stream_incomplete');
  });

  it('end after final is a no-op for the message', () => {
    let s = started();
    s = chatReducer(s, { type: 'final', id: 'a1', response: final(), atMs: 5 });
    s = chatReducer(s, { type: 'end', id: 'a1', atMs: 6 });
    expect(assistant(s).status).toBe('done');
  });

  it('cancel marks the message cancelled', () => {
    let s = started();
    s = chatReducer(s, { type: 'cancel', id: 'a1', atMs: 7 });
    expect(assistant(s).status).toBe('cancelled');
    expect(s.pendingId).toBeNull();
  });

  it('reset clears messages and session', () => {
    let s = started();
    s = chatReducer(s, { type: 'session', sessionId: 's1' });
    s = chatReducer(s, { type: 'reset' });
    expect(s).toEqual(initialChatState);
  });

  it('actions for unknown message ids are ignored', () => {
    const s = started();
    expect(chatReducer(s, { type: 'token', id: 'nope', text: 'x', atMs: 1 }).messages).toBe(s.messages);
  });
});
