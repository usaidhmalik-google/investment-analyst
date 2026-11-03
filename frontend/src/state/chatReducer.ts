import type {
  AssistantMessage,
  ChatResponse,
  ErrorEventData,
  Message,
  Strategy,
  ThoughtEventData,
} from '../types';

export interface ChatState {
  sessionId: string | null;
  messages: Message[];
  /** Id of the assistant message currently streaming, if any. */
  pendingId: string | null;
}

export const initialChatState: ChatState = { sessionId: null, messages: [], pendingId: null };

export type ChatAction =
  | { type: 'start'; userId: string; assistantId: string; content: string; strategy: Strategy | null }
  | { type: 'session'; sessionId: string }
  | { type: 'thought'; id: string; thought: ThoughtEventData; atMs: number }
  | { type: 'token'; id: string; text: string; atMs: number }
  | { type: 'final'; id: string; response: ChatResponse; atMs: number }
  | { type: 'error'; id: string; error: ErrorEventData; atMs: number }
  | { type: 'end'; id: string; atMs: number }
  | { type: 'cancel'; id: string; atMs: number }
  | { type: 'reset' };

function updateAssistant(
  state: ChatState,
  id: string,
  fn: (m: AssistantMessage) => AssistantMessage,
): ChatState {
  let changed = false;
  const messages = state.messages.map((m) => {
    if (m.role === 'assistant' && m.id === id) {
      changed = true;
      return fn(m);
    }
    return m;
  });
  return changed ? { ...state, messages } : state;
}

const isStreaming = (m: AssistantMessage) => m.status === 'streaming';

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'start': {
      const assistant: AssistantMessage = {
        role: 'assistant',
        id: action.assistantId,
        status: 'streaming',
        content: '',
        thoughts: [],
        final: null,
        error: null,
        clientLatency: { firstThoughtMs: null, firstTokenMs: null, totalMs: null },
      };
      return {
        ...state,
        pendingId: action.assistantId,
        messages: [
          ...state.messages,
          { role: 'user', id: action.userId, content: action.content, strategy: action.strategy },
          assistant,
        ],
      };
    }

    case 'session':
      return state.sessionId === action.sessionId ? state : { ...state, sessionId: action.sessionId };

    case 'thought':
      return updateAssistant(state, action.id, (m) =>
        isStreaming(m)
          ? {
              ...m,
              thoughts: [...m.thoughts, action.thought],
              clientLatency: {
                ...m.clientLatency,
                firstThoughtMs: m.clientLatency.firstThoughtMs ?? action.atMs,
              },
            }
          : m,
      );

    case 'token':
      return updateAssistant(state, action.id, (m) =>
        isStreaming(m)
          ? {
              ...m,
              content: m.content + action.text,
              clientLatency: {
                ...m.clientLatency,
                firstTokenMs: m.clientLatency.firstTokenMs ?? action.atMs,
              },
            }
          : m,
      );

    case 'final': {
      const next = updateAssistant(state, action.id, (m) => ({
        ...m,
        status: 'done',
        content: action.response.response,
        final: action.response,
        error: null,
        clientLatency: { ...m.clientLatency, totalMs: action.atMs },
      }));
      return {
        ...next,
        sessionId: action.response.session_id || next.sessionId,
        pendingId: state.pendingId === action.id ? null : state.pendingId,
      };
    }

    case 'error': {
      const next = updateAssistant(state, action.id, (m) =>
        m.status === 'done' && m.final
          ? m
          : {
              ...m,
              status: 'error',
              error: action.error,
              clientLatency: { ...m.clientLatency, totalMs: m.clientLatency.totalMs ?? action.atMs },
            },
      );
      return { ...next, pendingId: state.pendingId === action.id ? null : state.pendingId };
    }

    case 'end': {
      // Stream closed. If neither `final` nor `error` arrived, flag it.
      const next = updateAssistant(state, action.id, (m) =>
        isStreaming(m)
          ? {
              ...m,
              status: 'error',
              error: {
                code: 'stream_incomplete',
                message: 'The response ended unexpectedly before the analysis was complete.',
              },
              clientLatency: { ...m.clientLatency, totalMs: action.atMs },
            }
          : m,
      );
      return { ...next, pendingId: state.pendingId === action.id ? null : state.pendingId };
    }

    case 'cancel': {
      const next = updateAssistant(state, action.id, (m) =>
        isStreaming(m)
          ? { ...m, status: 'cancelled', clientLatency: { ...m.clientLatency, totalMs: action.atMs } }
          : m,
      );
      return { ...next, pendingId: state.pendingId === action.id ? null : state.pendingId };
    }

    case 'reset':
      return initialChatState;

    default:
      return state;
  }
}
