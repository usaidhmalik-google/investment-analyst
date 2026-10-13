import type {
  ChatResponse,
  Citation,
  FactCheck,
  Latency,
  RawSseEvent,
  StreamEvent,
  ToolCall,
  Usage,
} from '../types';

/**
 * Incremental Server-Sent Events parser (WHATWG "event stream" interpretation).
 *
 * `EventSource` cannot be used because `/api/chat/stream` is a POST, so the
 * response body is read with `fetch` + `ReadableStream` and fed here chunk by
 * chunk. Chunks may split anywhere (mid-line, mid-CRLF, mid-event).
 */
export class SseParser {
  private buffer = '';
  private eventType = '';
  private dataLines: string[] = [];
  private lastEventId: string | undefined;

  /** Feed a decoded text chunk; returns every event completed by it. */
  push(chunk: string): RawSseEvent[] {
    this.buffer += chunk;
    const out: RawSseEvent[] = [];

    for (;;) {
      const match = /\r\n|\r|\n/.exec(this.buffer);
      if (!match) break;
      // A trailing lone "\r" may be the first half of a "\r\n" split across chunks.
      if (match[0] === '\r' && match.index === this.buffer.length - 1) break;
      const line = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      const ev = this.processLine(line);
      if (ev) out.push(ev);
    }
    return out;
  }

  /** Signal end-of-stream; dispatches a final event lacking a trailing blank line. */
  flush(): RawSseEvent[] {
    const out: RawSseEvent[] = [];
    if (this.buffer.length > 0) {
      const rest = this.buffer.replace(/\r$/, '');
      this.buffer = '';
      const ev = this.processLine(rest);
      if (ev) out.push(ev);
    }
    const ev = this.dispatch();
    if (ev) out.push(ev);
    return out;
  }

  private processLine(line: string): RawSseEvent | null {
    if (line === '') return this.dispatch();
    if (line.startsWith(':')) return null; // comment / keep-alive

    const colon = line.indexOf(':');
    let field: string;
    let value: string;
    if (colon === -1) {
      field = line;
      value = '';
    } else {
      field = line.slice(0, colon);
      value = line.slice(colon + 1);
      if (value.startsWith(' ')) value = value.slice(1);
    }

    switch (field) {
      case 'event':
        this.eventType = value;
        break;
      case 'data':
        this.dataLines.push(value);
        break;
      case 'id':
        if (!value.includes('\0')) this.lastEventId = value;
        break;
      default:
        // `retry` and unknown fields are ignored.
        break;
    }
    return null;
  }

  private dispatch(): RawSseEvent | null {
    if (this.dataLines.length === 0) {
      this.eventType = '';
      return null;
    }
    const ev: RawSseEvent = {
      event: this.eventType || 'message',
      data: this.dataLines.join('\n'),
    };
    if (this.lastEventId !== undefined) ev.id = this.lastEventId;
    this.eventType = '';
    this.dataLines = [];
    return ev;
  }
}

/** Convenience: parse a complete SSE payload in one go. */
export function parseSse(text: string): RawSseEvent[] {
  const p = new SseParser();
  return [...p.push(text), ...p.flush()];
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/**
 * Decode a raw SSE frame into a typed contract event. Returns `null` for
 * unknown event types or malformed payloads (forward-compatible: the backend
 * may add new event types without breaking older clients).
 */
export function decodeStreamEvent(raw: RawSseEvent): StreamEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw.data);
  } catch {
    return null;
  }
  if (!isObject(data)) return null;

  switch (raw.event) {
    case 'session':
      return typeof data.session_id === 'string'
        ? { type: 'session', data: { session_id: data.session_id } }
        : null;
    case 'thought':
      return {
        type: 'thought',
        data: {
          agent: String(data.agent ?? ''),
          kind: String(data.kind ?? 'status'),
          name: String(data.name ?? ''),
          detail: data.detail == null ? '' : String(data.detail),
          elapsed_ms: typeof data.elapsed_ms === 'number' ? data.elapsed_ms : 0,
        },
      };
    case 'token':
      return typeof data.text === 'string'
        ? { type: 'token', data: { agent: String(data.agent ?? ''), text: data.text } }
        : null;
    case 'final':
      return typeof data.response === 'string' && typeof data.report_id === 'string'
        ? { type: 'final', data: normalizeChatResponse(data) }
        : null;
    case 'error':
      return {
        type: 'error',
        data: {
          code: String(data.code ?? 'unknown_error'),
          message: String(data.message ?? 'The analyst service reported an error.'),
        },
      };
    default:
      return null;
  }
}

/** Fill defaults so the UI never has to defend against missing optional fields. */
export function normalizeChatResponse(d: Record<string, unknown>): ChatResponse {
  return {
    report_id: String(d.report_id ?? ''),
    session_id: String(d.session_id ?? ''),
    response: String(d.response ?? ''),
    citations: Array.isArray(d.citations) ? (d.citations as Citation[]) : [],
    fact_check: isObject(d.fact_check) ? (d.fact_check as unknown as FactCheck) : null,
    tools_called: Array.isArray(d.tools_called) ? (d.tools_called as ToolCall[]) : [],
    latency: isObject(d.latency) ? (d.latency as unknown as Latency) : null,
    usage: isObject(d.usage) ? (d.usage as unknown as Usage) : null,
    blocked: d.blocked === true,
    block_reason: typeof d.block_reason === 'string' ? d.block_reason : null,
  };
}

/**
 * Read an SSE `ReadableStream` to completion, invoking `onEvent` for each
 * decoded contract event. Resolves when the stream ends.
 */
export async function readSseStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (ev: StreamEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8');
  const parser = new SseParser();
  const emit = (raws: RawSseEvent[]) => {
    for (const raw of raws) {
      const ev = decodeStreamEvent(raw);
      if (ev) onEvent(ev);
    }
  };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      emit(parser.push(decoder.decode(value, { stream: true })));
    }
    emit(parser.push(decoder.decode()));
    emit(parser.flush());
  } finally {
    reader.releaseLock();
  }
}
