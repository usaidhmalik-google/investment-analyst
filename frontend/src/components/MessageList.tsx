import { useEffect, useRef } from 'react';
import { humanize } from '../lib/format';
import { EXAMPLE_PROMPTS, type Message } from '../types';
import { AssistantMessage } from './AssistantMessage';

interface Props {
  messages: Message[];
  onExample: (text: string) => void;
}

function EmptyState({ onExample }: { onExample: (t: string) => void }) {
  return (
    <section className="ui-hero" aria-label="Research workbench overview">
      <div>
        <h2 className="ui-hero-title">What would you like to research?</h2>
        <p className="ui-hero-subtitle">
          Grounded equity briefs, live SEC 10-K/10-Q filings, and quantitative strategy evaluation—every figure
          verified against primary source data.
        </p>
      </div>

      <div className="ui-prompt-grid">
        {EXAMPLE_PROMPTS.map((item) => (
          <button
            key={item.label}
            type="button"
            onClick={() => onExample(item.prompt)}
            className="ui-prompt-card"
          >
            <div className="ui-row--between" style={{ width: '100%' }}>
              <span className="ui-badge ui-badge--primary">{item.ticker}</span>
              <span className="ui-badge">{item.strategy}</span>
            </div>
            <h3>{item.label}</h3>
            <small className="text-secondary">{item.prompt}</small>
          </button>
        ))}
      </div>
    </section>
  );
}

export function MessageList({ messages, onExample }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const last = messages[messages.length - 1];
  const lastLen = last ? (last.role === 'assistant' ? last.content.length + last.thoughts.length : 0) : 0;

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
    <div role="log" aria-label="Conversation" className="ui-stack--md">
      {messages.map((m) =>
        m.role === 'user' ? (
          <div key={m.id} className="ui-user-bubble">
            <p>{m.content}</p>
            {m.strategy && (
              <div style={{ marginTop: '6px' }}>
                <span className="ui-badge">Strategy: {humanize(m.strategy)}</span>
              </div>
            )}
          </div>
        ) : (
          <AssistantMessage key={m.id} message={m} />
        ),
      )}
      <div ref={endRef} />
    </div>
  );
}
