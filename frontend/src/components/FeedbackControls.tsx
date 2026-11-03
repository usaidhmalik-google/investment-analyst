import { useId, useState, type FormEvent } from 'react';
import { describeError, sendFeedback } from '../api/client';
import type { FeedbackRating } from '../types';
import { ThumbDownIcon, ThumbUpIcon } from './icons';

type Phase = 'idle' | 'editing' | 'sending' | 'sent' | 'error';

export function FeedbackControls({ reportId }: { reportId: string }) {
  const [rating, setRating] = useState<FeedbackRating | null>(null);
  const [comment, setComment] = useState('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const commentId = useId();

  if (phase === 'sent') {
    return (
      <p role="status" className="text-[11px] text-slate-500 dark:text-slate-400">
        Thanks — your feedback was recorded.
      </p>
    );
  }

  const choose = (r: FeedbackRating) => {
    setRating(r);
    setPhase('editing');
    setError(null);
  };

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!rating) return;
    setPhase('sending');
    setError(null);
    try {
      await sendFeedback({ report_id: reportId, rating, comment });
      setPhase('sent');
    } catch (err) {
      setError(describeError(err).message);
      setPhase('error');
    }
  };

  const thumb = (r: FeedbackRating) => {
    const active = rating === r;
    const Icon = r === 'up' ? ThumbUpIcon : ThumbDownIcon;
    return (
      <button
        type="button"
        onClick={() => choose(r)}
        aria-pressed={active}
        aria-label={r === 'up' ? 'Helpful' : 'Not helpful'}
        title={r === 'up' ? 'Helpful' : 'Not helpful'}
        disabled={phase === 'sending'}
        className={[
          'rounded-md p-1.5 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500',
          active
            ? r === 'up'
              ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
              : 'bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300'
            : 'text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200',
        ].join(' ')}
      >
        <Icon className="h-4 w-4" />
      </button>
    );
  };

  return (
    <div className="w-full">
      <div className="flex items-center gap-1">
        <span className="mr-1 text-[11px] text-slate-500 dark:text-slate-400">Was this helpful?</span>
        {thumb('up')}
        {thumb('down')}
      </div>
      {phase !== 'idle' && rating && (
        <form onSubmit={submit} className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-start">
          <label htmlFor={commentId} className="sr-only">
            Optional feedback comment
          </label>
          <textarea
            id={commentId}
            rows={2}
            maxLength={2000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder={rating === 'up' ? 'What was useful? (optional)' : 'What was wrong or missing? (optional)'}
            className="min-h-[2.5rem] flex-1 resize-y rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/30 dark:border-slate-700 dark:bg-slate-900"
          />
          <button type="submit" className="btn-primary !py-1.5 text-xs" disabled={phase === 'sending'}>
            {phase === 'sending' ? 'Sending…' : 'Submit feedback'}
          </button>
        </form>
      )}
      {error && (
        <p role="alert" className="mt-1 text-[11px] text-rose-600 dark:text-rose-400">
          Could not send feedback: {error}
        </p>
      )}
    </div>
  );
}
