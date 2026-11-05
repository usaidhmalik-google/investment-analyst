import { useEffect, useRef } from 'react';
import { humanize } from '../lib/format';
import { EXAMPLE_PROMPTS, type Message } from '../types';
import { AssistantMessage } from './AssistantMessage';
import { EditIcon } from './icons';

interface Props {
  messages: Message[];
  onExample: (text: string) => void;
}

function EmptyState({ onExample }: { onExample: (t: string) => void }) {
  return (
    <section className="ui-sheet" aria-label="Research workbench overview">
      <div className="ui-row--between">
        <div>
          <span className="ui-eyebrow">Institutional Equity Research Workbench</span>
          <h2>Select a research mandate or enter a ticker in the left rail</h2>
        </div>
        <span className="ui-badge ui-badge--success">FINRA 2210 Fact-Check Guardrails Active</span>
      </div>

      <p className="text-secondary">
        Every research brief is synthesized by a 5-agent Google ADK hierarchy across live market feeds, SEC EDGAR XBRL
        financials, and hybrid BM25 + vector 10-K retrieval. All numeric claims are verified against tool evidence
        within a 1.5% tolerance.
      </p>

      <table>
        <thead>
          <tr>
            <th>Mandate Template</th>
            <th>Primary Coverage</th>
            <th>Strategy Lens</th>
            <th className="is-num">Action</th>
          </tr>
        </thead>
        <tbody>
          {EXAMPLE_PROMPTS.map((item) => (
            <tr key={item.label}>
              <td>{item.label}</td>
              <td>
                <code>{item.ticker}</code>
              </td>
              <td>{item.strategy}</td>
              <td className="is-num">
                <button type="button" className="ui-btn" onClick={() => onExample(item.prompt)}>
                  <EditIcon />
                  <span>Load</span>
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
          <div key={m.id} className="ui-card is-active">
            <div className="ui-row--between">
              <span className="ui-eyebrow">Analyst Research Mandate</span>
              {m.strategy && <span className="ui-badge ui-badge--primary">Strategy: {humanize(m.strategy)}</span>}
            </div>
            <p>{m.content}</p>
          </div>
        ) : (
          <AssistantMessage key={m.id} message={m} />
        ),
      )}
      <div ref={endRef} />
    </div>
  );
}
