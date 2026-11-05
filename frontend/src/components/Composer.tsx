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

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 48), 200)}px`;
  }, [text]);

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
    <form onSubmit={onSubmit} className="ui-composer-box" aria-label="Ask the analyst">
      <label htmlFor={inputId} className="sr-only">
        Your request
      </label>
      <textarea
        id={inputId}
        ref={ref}
        rows={2}
        value={text}
        maxLength={MAX_LEN}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        aria-describedby={hintId}
        className="ui-composer-textarea"
        placeholder="Ask about a ticker, SEC filing, or investment strategy..."
      />

      <div className="ui-composer-footer">
        <StrategySelector value={strategy} onChange={setStrategy} available={strategies} disabled={isStreaming} />

        <div className="ui-row">
          <span id={hintId} className="sr-only">
            Press Enter to send or Shift+Enter for a newline
          </span>
          {isStreaming ? (
            <button type="button" onClick={onStop} className="ui-btn ui-btn--danger" aria-label="Stop generating">
              <CloseIcon />
              <span>Stop</span>
            </button>
          ) : (
            <button type="submit" disabled={!canSend} className="ui-btn ui-btn--primary" aria-label="Send request">
              <CheckIcon />
              <span>Analyze</span>
            </button>
          )}
        </div>
      </div>
    </form>
  );
}
