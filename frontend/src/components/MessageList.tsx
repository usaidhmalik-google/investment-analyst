import { useEffect, useRef } from 'react';
import { humanize } from '../lib/format';
import type { Message } from '../types';
import { AssistantMessage } from './AssistantMessage';

interface Props {
  messages: Message[];
  onExample: (text: string) => void;
}

const EXAMPLE_PROMPTS = [
  "Give me a brief on NVIDIA's performance this week and summarize the latest news regarding their new chips",
  'Compare AAPL and MSFT fundamentals from their latest 10-K filings',
  'Is AMD showing momentum right now? Evaluate it with the momentum strategy',
  'What is the dividend yield and payout history for JNJ?',
];

function EmptyState({ onExample }: { onExample: (t: string) => void }) {
  return (
    <div className="mx-auto max-w-2xl py-12 text-center">
      <h2 className="text-xl font-semibold tracking-tight">What would you like to research?</h2>
      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
        Ask about a ticker&apos;s price action, fundamentals, SEC filings or news. Every figure in the brief is cited
        and fact-checked against the source data.
      </p>
      <ul className="mt-6 grid gap-2 text-left sm:grid-cols-2">
        {EXAMPLE_PROMPTS.map((p) => (
          <li key={p}>
            <button
              type="button"
              onClick={() => onExample(p)}
              className="h-full w-full rounded-lg border border-slate-200 bg-white p-3 text-left text-xs text-slate-700 transition hover:border-brand-400 hover:bg-brand-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500/60 dark:hover:bg-slate-800"
            >
              {p}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function MessageList({ messages, onExample }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const last = messages[messages.length - 1];
  const lastLen = last ? (last.role === 'assistant' ? last.content.length + last.thoughts.length : 0) : 0;

  // Keep the newest content in view while the user is near the bottom.
  useEffect(() => {
    const el = endRef.current;
    if (!el) return;
    const nearBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 240;
    if (nearBottom || last?.role === 'user' || (last?.role === 'assistant' && lastLen === 0)) {
      el.scrollIntoView?.({ block: 'end' });
    }
  }, [messages.length, lastLen, last?.role]);

  if (messages.length === 0) return <EmptyState onExample={onExample} />;

  return (
    <div role="log" aria-label="Conversation" className="space-y-4 py-6">
      {messages.map((m) =>
        m.role === 'user' ? (
          <div key={m.id} className="flex justify-end">
            <div className="max-w-[85%] rounded-xl rounded-br-sm bg-brand-600 px-4 py-2.5 text-sm text-white shadow-sm">
              <p className="whitespace-pre-wrap break-words">{m.content}</p>
              {m.strategy && (
                <p className="mt-1 text-[11px] text-brand-100">Strategy lens: {humanize(m.strategy)}</p>
              )}
            </div>
          </div>
        ) : (
          <AssistantMessage key={m.id} message={m} />
        ),
      )}
      <div ref={endRef} />
    </div>
  );
}
