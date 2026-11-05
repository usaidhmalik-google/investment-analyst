import { useId, useState, type FormEvent } from 'react';
import { describeError, sendFeedback } from '../api/client';
import type { FeedbackRating } from '../types';
import { CheckIcon, CloseIcon } from './icons';

type Phase = 'idle' | 'editing' | 'sending' | 'sent' | 'error';

export function FeedbackControls({ reportId }: { reportId: string }) {
  const [rating, setRating] = useState<FeedbackRating | null>(null);
  const [comment, setComment] = useState('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const commentId = useId();

  if (phase === 'sent') {
    return (
      <small role="status" className="text-secondary">
        Thanks — your feedback was recorded.
      </small>
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

  return (
    <div className="ui-stack">
      <div className="ui-row--between">
        <small className="text-secondary">Was this helpful?</small>
        <div className="ui-card-actions" style={{ maxWidth: '240px' }}>
          <button
            type="button"
            onClick={() => choose('up')}
            aria-pressed={rating === 'up'}
            aria-label="Helpful"
            title="Helpful"
            disabled={phase === 'sending'}
            className={`ui-btn ${rating === 'up' ? 'ui-btn--primary' : ''}`}
          >
            <CheckIcon />
            <span>Approve</span>
          </button>
          <button
            type="button"
            onClick={() => choose('down')}
            aria-pressed={rating === 'down'}
            aria-label="Not helpful"
            title="Not helpful"
            disabled={phase === 'sending'}
            className={`ui-btn ${rating === 'down' ? 'ui-btn--danger' : ''}`}
          >
            <CloseIcon />
            <span>Flag Issue</span>
          </button>
        </div>
      </div>

      {phase !== 'idle' && rating && (
        <form onSubmit={submit} className="ui-stack">
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
          />
          <div className="ui-row">
            <button type="submit" className="ui-btn ui-btn--primary" disabled={phase === 'sending'}>
              {phase === 'sending' ? 'Sending…' : 'Submit feedback'}
            </button>
          </div>
        </form>
      )}
      {error && (
        <small role="alert" className="text-secondary">
          Could not send feedback: {error}
        </small>
      )}
    </div>
  );
}
