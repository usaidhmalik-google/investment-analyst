import type {
  ChatRequest,
  ChatResponse,
  ConfigResponse,
  FeedbackRequest,
  StreamEvent,
} from '../types';
import { normalizeChatResponse, readSseStream } from './sse';

/** Base URL for API calls. Empty = same origin (nginx / Vite proxy). */
const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code = 'http_error') {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

/** Extract a human-readable message from a FastAPI error body. */
async function errorFromResponse(res: Response): Promise<ApiError> {
  let detail = `${res.status} ${res.statusText}`.trim();
  try {
    const text = await res.text();
    if (text) {
      try {
        const body = JSON.parse(text) as { detail?: unknown; message?: unknown; code?: unknown };
        if (typeof body.detail === 'string') detail = body.detail;
        else if (typeof body.message === 'string') detail = body.message;
        else if (Array.isArray(body.detail)) detail = 'The request was rejected as invalid.';
        if (typeof body.code === 'string') return new ApiError(detail, res.status, body.code);
      } catch {
        detail = text.slice(0, 300);
      }
    }
  } catch {
    /* ignore body read errors */
  }
  if (res.status === 401 || res.status === 403) {
    return new ApiError(
      'You are not authorized to use the Investment Analyst. Please sign in again.',
      res.status,
      'unauthorized',
    );
  }
  if (res.status === 429) {
    return new ApiError('Too many requests. Please wait a moment and try again.', res.status, 'rate_limited');
  }
  return new ApiError(detail, res.status);
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
    signal,
  });
  if (!res.ok) throw await errorFromResponse(res);
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw await errorFromResponse(res);
  return (await res.json()) as T;
}

/** Strip undefined/empty optional fields so the request matches the contract. */
export function buildChatRequest(
  message: string,
  sessionId: string | null,
  strategy: ChatRequest['strategy'],
): ChatRequest {
  const req: ChatRequest = { message: message.trim(), strategy };
  if (sessionId) req.session_id = sessionId;
  return req;
}

export function getConfig(signal?: AbortSignal): Promise<ConfigResponse> {
  return getJson<ConfigResponse>('/api/config', signal);
}

export async function chat(req: ChatRequest, signal?: AbortSignal): Promise<ChatResponse> {
  const data = await postJson<Record<string, unknown>>('/api/chat', req, signal);
  return normalizeChatResponse(data);
}

export function sendFeedback(req: FeedbackRequest, signal?: AbortSignal): Promise<{ status: string }> {
  const body: FeedbackRequest = { report_id: req.report_id, rating: req.rating };
  const comment = req.comment?.trim();
  if (comment) body.comment = comment;
  return postJson<{ status: string }>('/api/feedback', body, signal);
}

/**
 * POST /api/chat/stream and dispatch each SSE event to `onEvent`.
 * Resolves when the server closes the stream; rejects on HTTP / network
 * failure or abort (`DOMException` with name `AbortError`).
 */
export async function streamChat(
  req: ChatRequest,
  onEvent: (ev: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    credentials: 'same-origin',
    cache: 'no-store',
    body: JSON.stringify(req),
    signal,
  });
  if (!res.ok) throw await errorFromResponse(res);
  if (!res.body) throw new ApiError('Streaming is not supported by this browser.', 0, 'no_stream');
  await readSseStream(res.body, onEvent);
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError';
}

/** Map any thrown value to a user-facing message. */
export function describeError(err: unknown): { code: string; message: string } {
  if (err instanceof ApiError) return { code: err.code, message: err.message };
  if (err instanceof TypeError) {
    return {
      code: 'network_error',
      message: 'Could not reach the analyst service. Check your connection and try again.',
    };
  }
  if (err instanceof Error) return { code: 'client_error', message: err.message };
  return { code: 'client_error', message: 'An unexpected error occurred.' };
}
