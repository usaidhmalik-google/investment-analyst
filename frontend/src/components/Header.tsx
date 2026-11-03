import type { ConfigResponse } from '../types';
import { LogoIcon, MoonIcon, PlusIcon, SunIcon } from './icons';

interface Props {
  config: ConfigResponse | null;
  dark: boolean;
  onToggleTheme: () => void;
  onNewChat: () => void;
  canReset: boolean;
}

export function Header({ config, dark, onToggleTheme, onNewChat, canReset }: Props) {
  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/85 backdrop-blur dark:border-slate-800 dark:bg-slate-950/85">
      <div className="mx-auto flex h-14 max-w-5xl items-center gap-3 px-4">
        <LogoIcon className="h-8 w-8 text-brand-600" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold tracking-tight">Investment Analyst</h1>
          <p className="truncate text-xs text-slate-500 dark:text-slate-400">MALIK LLC · Research Desk</p>
        </div>

        {config?.offline_mode && (
          <span
            className="hidden rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 sm:inline dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-300"
            title="The backend is serving bundled fixture data instead of live market data."
          >
            Offline demo data
          </span>
        )}
        {config && (
          <span
            className="hidden font-mono text-[11px] text-slate-400 md:inline"
            title={Object.entries(config.models)
              .map(([k, v]) => `${k}: ${v}`)
              .join('\n')}
          >
            prompts {config.prompt_version}
          </span>
        )}

        <button
          type="button"
          onClick={onToggleTheme}
          className="btn-ghost"
          aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
          title={dark ? 'Light theme' : 'Dark theme'}
        >
          {dark ? <SunIcon /> : <MoonIcon />}
        </button>
        <button
          type="button"
          onClick={onNewChat}
          disabled={!canReset}
          className="btn-secondary"
          title="Start a new conversation"
        >
          <PlusIcon />
          <span>New chat</span>
        </button>
      </div>
    </header>
  );
}
