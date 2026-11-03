/**
 * Shared types mirroring docs/API_CONTRACT.md (V1).
 * Any change to the contract must be reflected here.
 */

export const STRATEGIES = ['momentum', 'value', 'swing', 'income'] as const;
export type Strategy = (typeof STRATEGIES)[number];

export interface ChatRequest {
  message: string;
  session_id?: string;
  strategy: Strategy | null;
}

export type CitationType =
  | 'quote'
  | 'history'
  | 'metrics'
  | 'news'
  | 'sec_filing'
  | 'sec_financials'
  | 'strategy';

export interface Citation {
  id: string;
  type: CitationType | string;
  title: string;
  source: string;
  url: string | null;
  as_of: string;
}

export interface FactCheck {
  verified: boolean;
  checked_numbers: number;
  matched_numbers: number;
  unverified_numbers: Array<string | number>;
  accuracy: number;
}

export interface ToolCall {
  agent: string;
  tool: string;
  args: Record<string, unknown>;
}

export interface Latency {
  time_to_first_thought_ms: number | null;
  time_to_first_token_ms: number | null;
  total_ms: number | null;
}

export interface Usage {
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface ChatResponse {
  report_id: string;
  session_id: string;
  response: string;
  citations: Citation[];
  fact_check: FactCheck | null;
  tools_called: ToolCall[];
  latency: Latency | null;
  usage: Usage | null;
  blocked: boolean;
  block_reason: string | null;
}

export type FeedbackRating = 'up' | 'down';

export interface FeedbackRequest {
  report_id: string;
  rating: FeedbackRating;
  comment?: string;
}

export interface ConfigResponse {
  strategies: string[];
  models: Record<string, string>;
  offline_mode: boolean;
  prompt_version: string;
}

// ---------------------------------------------------------------------------
// Streaming events (POST /api/chat/stream)
// ---------------------------------------------------------------------------

export type ThoughtKind = 'tool_call' | 'tool_result' | 'agent_transfer' | 'status';

export interface SessionEventData {
  session_id: string;
}

export interface ThoughtEventData {
  agent: string;
  kind: ThoughtKind | string;
  name: string;
  detail: string;
  elapsed_ms: number;
}

export interface TokenEventData {
  agent: string;
  text: string;
}

export interface ErrorEventData {
  code: string;
  message: string;
}

export type StreamEvent =
  | { type: 'session'; data: SessionEventData }
  | { type: 'thought'; data: ThoughtEventData }
  | { type: 'token'; data: TokenEventData }
  | { type: 'final'; data: ChatResponse }
  | { type: 'error'; data: ErrorEventData };

/** A raw SSE frame before JSON decoding / validation. */
export interface RawSseEvent {
  event: string;
  data: string;
  id?: string;
}

// ---------------------------------------------------------------------------
// UI state
// ---------------------------------------------------------------------------

export type AssistantStatus = 'streaming' | 'done' | 'error' | 'cancelled';

export interface ClientLatency {
  firstThoughtMs: number | null;
  firstTokenMs: number | null;
  totalMs: number | null;
}

export interface UserMessage {
  role: 'user';
  id: string;
  content: string;
  strategy: Strategy | null;
}

export interface AssistantMessage {
  role: 'assistant';
  id: string;
  status: AssistantStatus;
  /** Streamed markdown (replaced by `final.response` once available). */
  content: string;
  thoughts: ThoughtEventData[];
  final: ChatResponse | null;
  error: ErrorEventData | null;
  clientLatency: ClientLatency;
}

export type Message = UserMessage | AssistantMessage;
