import { useCallback, useState } from 'react';
import { Composer } from './components/Composer';
import { Disclaimer } from './components/Disclaimer';
import { Header } from './components/Header';
import { MessageList } from './components/MessageList';
import { useChat } from './state/useChat';
import { useConfig, useTheme } from './state/useConfig';

export default function App() {
  const config = useConfig();
  const [dark, toggleTheme] = useTheme();
  const { messages, isStreaming, send, stop, newChat } = useChat();
  const [draft, setDraft] = useState<{ text: string; nonce: number } | null>(null);

  const onExample = useCallback((text: string) => {
    setDraft((d) => ({ text, nonce: (d?.nonce ?? 0) + 1 }));
  }, []);

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#composer" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-sm dark:focus:bg-slate-900">
        Skip to message input
      </a>
      <Header
        config={config}
        dark={dark}
        onToggleTheme={toggleTheme}
        onNewChat={newChat}
        canReset={messages.length > 0}
      />

      <main className="mx-auto w-full max-w-5xl flex-1 px-4">
        <MessageList messages={messages} onExample={onExample} />
      </main>

      <div
        id="composer"
        className="sticky bottom-0 z-10 border-t border-slate-200 bg-slate-50/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90"
      >
        <div className="mx-auto max-w-5xl space-y-2 px-4 pb-3 pt-3">
          <Composer
            onSend={(m, s) => void send(m, s)}
            onStop={stop}
            isStreaming={isStreaming}
            strategies={config?.strategies}
            draft={draft}
          />
          <footer>
            <Disclaimer />
          </footer>
        </div>
      </div>
    </div>
  );
}
