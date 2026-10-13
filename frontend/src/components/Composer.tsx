import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import type { Strategy } from '../types';
import { SendIcon, StopIcon } from './icons';
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

  // Auto-grow textarea.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
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
    <form onSubmit={onSubmit} className="space-y-2" aria-label="Ask the analyst">
      <StrategySelector value={strategy} onChange={setStrategy} available={strategies} disabled={isStreaming} />
      <div className="flex items-end gap-2 rounded-xl border border-slate-300 bg-white p-2 shadow-sm focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-500/30 dark:border-slate-700 dark:bg-slate-900">
        <label htmlFor={inputId} className="sr-only">
          Your request
        </label>
        <textarea
          id={inputId}
          ref={ref}
          rows={1}
          value={text}
          maxLength={MAX_LEN}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          aria-describedby={hintId}
          placeholder="e.g. Give me a brief on NVIDIA's performance this week and summarize the latest news on their new chips"
          className="max-h-56 min-h-[2.5rem] flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-6 outline-none placeholder:text-slate-400 dark:placeholder:text-slate-500"
        />
        {isStreaming ? (
          <button type="button" onClick={onStop} className="btn-danger" aria-label="Stop generating">
            <StopIcon />
            <span className="hidden sm:inline">Stop</span>
          </button>
        ) : (
          <button type="submit" disabled={!canSend} className="btn-primary" aria-label="Send request">
            <SendIcon />
            <span className="hidden sm:inline">Send</span>
          </button>
        )}
      </div>
      <p id={hintId} className="px-1 text-[11px] text-slate-500 dark:text-slate-400">
        <kbd className="kbd">Enter</kbd> to send · <kbd className="kbd">Shift</kbd>+<kbd className="kbd">Enter</kbd> for a
        new line
      </p>
    </form>
  );
}
