import { useCallback, useEffect, useState } from 'react';
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

      <div className="ui-shell">
        <main className="ui-canvas">
          <MessageList messages={messages} onExample={onExample} />
        </main>

        <div id="composer" className="ui-composer-dock">
          <Composer
            onSend={(m, s) => void send(m, s)}
            onStop={stop}
            isStreaming={isStreaming}
            strategies={config?.strategies}
            draft={draft}
          />
          <footer style={{ marginTop: '10px', textAlign: 'center' }}>
            <Disclaimer />
          </footer>
        </div>
      </div>
    </>
  );
}
