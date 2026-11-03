import { formatAccuracy } from '../lib/format';
import type { FactCheck } from '../types';
import { AlertIcon, CheckCircleIcon } from './icons';

export function FactCheckBadge({ factCheck }: { factCheck: FactCheck | null }) {
  if (!factCheck) return null;
  const unverified = factCheck.unverified_numbers.length;
  const ok = factCheck.verified && unverified === 0;
  const details = [
    `${factCheck.matched_numbers}/${factCheck.checked_numbers} figures matched tool data`,
    unverified ? `Unverified: ${factCheck.unverified_numbers.join(', ')}` : '',
  ]
    .filter(Boolean)
    .join('\n');

  return (
    <span
      role="status"
      title={details}
      className={[
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium',
        ok
          ? 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-300'
          : 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-300',
      ].join(' ')}
    >
      {ok ? <CheckCircleIcon className="h-3.5 w-3.5" /> : <AlertIcon className="h-3.5 w-3.5" />}
      {ok ? 'Fact-checked' : `${unverified} unverified number${unverified === 1 ? '' : 's'}`}
      <span className="font-normal opacity-80">
        · {formatAccuracy(factCheck.accuracy)} accuracy ({factCheck.matched_numbers}/{factCheck.checked_numbers})
      </span>
    </span>
  );
}
