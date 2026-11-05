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
      <div className="ui-row">
        <h1>Investment Analyst · MALIK LLC</h1>
        {config?.offline_mode ? (
          <span
            className="ui-badge ui-badge--warning"
            title="Serving deterministic offline fixture data"
          >
            Offline Fixture Mode
          </span>
        ) : (
          <span
            className="ui-badge ui-badge--primary"
            title={`Router: ${config?.models?.router ?? 'gemini-3.5-flash'} | Synthesis: ${modelLabel} | Prompts: ${config?.prompt_version ?? 'v1'}`}
          >
            Vertex AI · {modelLabel}
          </span>
        )}
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
          className="ui-btn ui-btn--primary"
          title="Start a new research session"
        >
          <RefreshIcon />
          <span>New session</span>
        </button>
      </div>
    </header>
  );
}
