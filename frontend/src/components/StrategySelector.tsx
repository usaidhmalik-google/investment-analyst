import { STRATEGIES, type Strategy } from '../types';
import { humanize } from '../lib/format';

interface Props {
  value: Strategy | null;
  onChange: (s: Strategy | null) => void;
  /** Strategies advertised by /api/config (falls back to the contract list). */
  available?: readonly string[];
  disabled?: boolean;
}

const DESCRIPTIONS: Record<Strategy | 'none', string> = {
  none: 'No strategy lens — general brief',
  momentum: 'Trend & relative strength',
  value: 'Valuation vs. fundamentals',
  swing: 'Short-term price swings',
  income: 'Dividends & yield',
};

function isStrategy(s: string): s is Strategy {
  return (STRATEGIES as readonly string[]).includes(s);
}

export function StrategySelector({ value, onChange, available, disabled }: Props) {
  const advertised: Strategy[] = available?.filter(isStrategy) ?? [];
  const list: Strategy[] = advertised.length ? advertised : [...STRATEGIES];
  const options: Array<Strategy | null> = [null, ...list];

  return (
    <fieldset className="flex flex-wrap items-center gap-2" disabled={disabled}>
      <legend className="sr-only">Investment strategy lens</legend>
      <span aria-hidden="true" className="text-xs font-medium text-slate-500 dark:text-slate-400">
        Strategy
      </span>
      <div className="inline-flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800/70">
        {options.map((opt) => {
          const key = opt ?? 'none';
          const checked = value === opt;
          return (
            <label
              key={key}
              title={DESCRIPTIONS[key]}
              className={[
                'cursor-pointer select-none rounded-md px-2.5 py-1 text-xs font-medium transition',
                'has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-500',
                checked
                  ? 'bg-white text-brand-700 shadow-sm dark:bg-slate-700 dark:text-white'
                  : 'text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100',
                disabled ? 'cursor-not-allowed opacity-60' : '',
              ].join(' ')}
            >
              <input
                type="radio"
                name="strategy"
                value={key}
                checked={checked}
                onChange={() => onChange(opt)}
                className="sr-only"
              />
              {opt ? humanize(opt) : 'None'}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
