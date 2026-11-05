import { useCallback, useEffect, useState } from 'react';
import { Composer } from './components/Composer';
import { Disclaimer } from './components/Disclaimer';
import { Header } from './components/Header';
import { EditIcon } from './components/icons';
import { MessageList } from './components/MessageList';
import { useChat } from './state/useChat';
import { useConfig, useTheme } from './state/useConfig';
import { EXAMPLE_PROMPTS } from './types';

export default function App() {
  const config = useConfig();
  const [dark, toggleTheme] = useTheme();
  const { messages, isStreaming, send, stop, newChat } = useChat();
  const [draft, setDraft] = useState<{ text: string; nonce: number } | null>(null);

  useEffect(() => {
    try {
      window.parent?.postMessage({ jsonrpc: '2.0', method: 'ui/notifications/initialized', params: {} }, '*');
    } catch {
      // Ignore cross-origin frame errors when running standalone
    }
  }, []);

  const onExample = useCallback((text: string) => {
    setDraft((d) => ({ text, nonce: (d?.nonce ?? 0) + 1 }));
  }, []);

  return (
    <>
      <a href="#composer" className="sr-only">
        Skip to message input
      </a>
      <Header
        config={config}
        dark={dark}
        onToggleTheme={toggleTheme}
        onNewChat={newChat}
        canReset={messages.length > 0}
      />

      <div className="ui-workspace">
        <aside id="composer" className="ui-sidebar" aria-label="Research mandate & controls">
          <Composer
            onSend={(m, s) => void send(m, s)}
            onStop={stop}
            isStreaming={isStreaming}
            strategies={config?.strategies}
            draft={draft}
          />

          <div className="ui-card">
            <span className="ui-eyebrow">Standard Research Mandates</span>
            <div className="ui-stack">
              {EXAMPLE_PROMPTS.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => onExample(item.prompt)}
                  className="ui-btn"
                  title={item.prompt}
                >
                  <EditIcon />
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          </div>

          <footer className="ui-card">
            <Disclaimer />
          </footer>
        </aside>

        <main className="ui-canvas">
          <MessageList messages={messages} onExample={onExample} />
        </main>
      </div>
    </>
  );
}
