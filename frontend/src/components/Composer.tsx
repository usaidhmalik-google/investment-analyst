import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import type { Strategy } from '../types';
import { CheckIcon, CloseIcon } from './icons';
import { StrategySelector } from './StrategySelector';

interface Props {
  onSend: (message: string, strategy: Strategy | null) => void;
  onStop: () => void;
  isStreaming: boolean;
  strategies?: readonly string[];
  /** Text injected from outside (e.g. example prompt click). */
  draft?: { text: string; nonce: number } | null;
}

const MAX_LEN = 4000;

export function Composer({ onSend, onStop, isStreaming, strategies, draft }: Props) {
  const [text, setText] = useState('');
  const [strategy, setStrategy] = useState<Strategy | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);
  const inputId = useId();
  const hintId = useId();

  useEffect(() => {
    if (draft) {
      setText(draft.text);
      ref.current?.focus();
    }
  }, [draft]);

  const canSend = !isStreaming && text.trim().length > 0;

  const submit = () => {
    if (!canSend) return;
    onSend(text, strategy);
    setText('');
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={onSubmit} className="ui-card" aria-label="Ask the analyst">
      <StrategySelector value={strategy} onChange={setStrategy} available={strategies} disabled={isStreaming} />

      <div className="ui-stack">
        <label htmlFor={inputId} className="ui-eyebrow">
          Your request
        </label>
        <textarea
          id={inputId}
          ref={ref}
          rows={4}
          value={text}
          maxLength={MAX_LEN}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          aria-describedby={hintId}
          placeholder="Enter ticker(s) and research mandate (e.g. NVDA weekly brief, AAPL vs MSFT 10-K comparison)..."
        />
      </div>

      <div className="ui-card-actions">
        {isStreaming ? (
          <button type="button" onClick={onStop} className="ui-btn ui-btn--danger" aria-label="Stop generating">
            <CloseIcon />
            <span>Stop</span>
          </button>
        ) : (
          <button type="submit" disabled={!canSend} className="ui-btn ui-btn--primary" aria-label="Send request">
            <CheckIcon />
            <span>Run Analysis</span>
          </button>
        )}
        <button
          type="button"
          className="ui-btn"
          disabled={isStreaming || text.length === 0}
          onClick={() => setText('')}
        >
          Clear
        </button>
      </div>

      <small id={hintId} className="text-secondary">
        Press Enter to submit or Shift+Enter for a newline.
      </small>
    </form>
  );
}
