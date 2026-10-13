import { useCallback, useEffect, useReducer, useRef } from 'react';
import { buildChatRequest, describeError, isAbortError, streamChat } from '../api/client';
import { localId } from '../lib/format';
import type { Strategy, StreamEvent } from '../types';
import { chatReducer, initialChatState } from './chatReducer';

export function useChat() {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const controllerRef = useRef<AbortController | null>(null);
  const sessionRef = useRef<string | null>(null);
  sessionRef.current = state.sessionId;

  // Abort any in-flight stream on unmount.
  useEffect(() => () => controllerRef.current?.abort(), []);

  const send = useCallback(async (message: string, strategy: Strategy | null) => {
    const text = message.trim();
    if (!text || controllerRef.current) return;

    const controller = new AbortController();
    controllerRef.current = controller;
    const assistantId = localId('a');
    const started = performance.now();
    const elapsed = () => Math.round(performance.now() - started);

    dispatch({ type: 'start', userId: localId('u'), assistantId, content: text, strategy });

    const onEvent = (ev: StreamEvent) => {
      if (controller.signal.aborted) return; // stale stream (stopped / new chat)
      switch (ev.type) {
        case 'session':
          dispatch({ type: 'session', sessionId: ev.data.session_id });
          break;
        case 'thought':
          dispatch({ type: 'thought', id: assistantId, thought: ev.data, atMs: elapsed() });
          break;
        case 'token':
          dispatch({ type: 'token', id: assistantId, text: ev.data.text, atMs: elapsed() });
          break;
        case 'final':
          dispatch({ type: 'final', id: assistantId, response: ev.data, atMs: elapsed() });
          break;
        case 'error':
          dispatch({ type: 'error', id: assistantId, error: ev.data, atMs: elapsed() });
          break;
      }
    };

    try {
      await streamChat(buildChatRequest(text, sessionRef.current, strategy), onEvent, controller.signal);
      if (!controller.signal.aborted) dispatch({ type: 'end', id: assistantId, atMs: elapsed() });
    } catch (err) {
      if (controller.signal.aborted || isAbortError(err)) {
        dispatch({ type: 'cancel', id: assistantId, atMs: elapsed() });
      } else {
        dispatch({ type: 'error', id: assistantId, error: describeError(err), atMs: elapsed() });
      }
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    controllerRef.current?.abort();
  }, []);

  const newChat = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    dispatch({ type: 'reset' });
  }, []);

  return {
    messages: state.messages,
    sessionId: state.sessionId,
    isStreaming: state.pendingId !== null,
    send,
    stop,
    newChat,
  };
}
