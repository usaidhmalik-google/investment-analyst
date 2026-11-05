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
  none: 'No strategy lens — general institutional brief',
  momentum: 'Trend & relative strength (RSI, MACD, 20/50/200 SMA)',
  value: 'Valuation vs. fundamentals (P/E, P/B, ROE, FCF)',
  swing: 'Short-term price swings (Bollinger %B, ATR, RSI)',
  income: 'Dividends, yield sustainability & payout coverage',
};

function isStrategy(s: string): s is Strategy {
  return (STRATEGIES as readonly string[]).includes(s);
}

export function StrategySelector({ value, onChange, available, disabled }: Props) {
  const advertised: Strategy[] = available?.filter(isStrategy) ?? [];
  const list: Strategy[] = advertised.length ? advertised : [...STRATEGIES];
  const options: Array<Strategy | null> = [null, ...list];

  return (
    <fieldset className="ui-stack" disabled={disabled} style={{ border: 'none' }}>
      <legend className="ui-eyebrow">Strategy Lens</legend>
      <div className="ui-row">
        {options.map((opt) => {
          const key = opt ?? 'none';
          const checked = value === opt;
          return (
            <label
              key={key}
              title={DESCRIPTIONS[key]}
              className={`ui-btn ${checked ? 'ui-btn--primary' : ''}`}
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
