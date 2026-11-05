import { formatAccuracy } from '../lib/format';
import type { FactCheck } from '../types';
import { CheckCircleIcon, WarningIcon } from './icons';

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

  const badgeClass = ok
    ? 'ui-badge ui-badge--success'
    : factCheck.accuracy < 0.8
      ? 'ui-badge ui-badge--danger'
      : 'ui-badge ui-badge--warning';

  return (
    <span role="status" title={details} className={badgeClass}>
      {ok ? <CheckCircleIcon /> : <WarningIcon />}
      <span>{ok ? 'Fact-checked' : `${unverified} unverified number${unverified === 1 ? '' : 's'}`}</span>
      <span>
        · {formatAccuracy(factCheck.accuracy)} accuracy ({factCheck.matched_numbers}/{factCheck.checked_numbers})
      </span>
    </span>
  );
}
