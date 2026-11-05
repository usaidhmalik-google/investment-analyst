import type { ConfigResponse } from '../types';
import { RefreshIcon } from './icons';

interface Props {
  config: ConfigResponse | null;
  dark: boolean;
  onToggleTheme: () => void;
  onNewChat: () => void;
  canReset: boolean;
}

export function Header({ config, dark, onToggleTheme, onNewChat, canReset }: Props) {
  const modelLabel = config?.models?.reasoning ?? 'gemini-3.8-flash';

  return (
    <header className="ui-topbar">
      <div className="ui-brand">
        <span className="ui-brand-dot" aria-hidden="true" />
        <h1>MALIK Research</h1>
        <span
          className="ui-badge"
          title={`Router: ${config?.models?.router ?? 'gemini-3.5-flash'} · Synthesis: ${modelLabel}`}
        >
          {config?.offline_mode ? 'Offline Fixtures' : modelLabel}
        </span>
      </div>

      <div className="ui-row">
        <div className="ui-segmented" role="group" aria-label="Appearance mode">
          <button
            type="button"
            onClick={() => {
              if (dark) onToggleTheme();
            }}
            aria-pressed={!dark}
            className={`ui-btn ${!dark ? 'is-active' : ''}`}
            aria-label="Switch to light theme"
          >
            Light
          </button>
          <button
            type="button"
            onClick={() => {
              if (!dark) onToggleTheme();
            }}
            aria-pressed={dark}
            className={`ui-btn ${dark ? 'is-active' : ''}`}
            aria-label="Switch to dark theme"
          >
            Dark
          </button>
        </div>

        <button
          type="button"
          onClick={onNewChat}
          disabled={!canReset}
          className="ui-btn"
          title="Start a new research session"
        >
          <RefreshIcon />
          <span>New chat</span>
        </button>
      </div>
    </header>
  );
}
