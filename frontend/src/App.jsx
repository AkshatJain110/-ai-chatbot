import React, { useState, useEffect, useRef } from 'react';
import { sendChatMessage } from './api';
import Message from './components/Message';
import ChatInput from './components/ChatInput';

function generateSessionId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'sess-' + Date.now() + '-' + Math.random().toString(36).substring(2, 9);
}

function getInitialTheme() {
  const saved = localStorage.getItem('theme');
  if (saved === 'light' || saved === 'dark') return saved;
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
}

export default function App() {
  const [sessionId, setSessionId] = useState(generateSessionId);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [theme, setTheme] = useState(getInitialTheme);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleNewChat = () => {
    setSessionId(generateSessionId());
    setMessages([]);
    setInput('');
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;

    setInput('');
    setLoading(true);
    setMessages((prev) => [...prev, { role: 'user', content: text }]);

    try {
      const data = await sendChatMessage(sessionId, text);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.reply,
          metadata: data.metadata,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'error',
          content: err.message || 'Network error: could not connect to server.',
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <h1 className="app-title">AI Chatbot</h1>
        <div className="header-actions">
          <button
            className="btn-secondary"
            onClick={() => setTheme((t) => (t === 'light' ? 'dark' : 'light'))}
          >
            {theme === 'light' ? '🌙 Dark' : '☀️ Light'}
          </button>
          <button className="btn-primary" onClick={handleNewChat}>
            + New chat
          </button>
        </div>
      </header>

      <main className="chat-window">
        {messages.length === 0 && (
          <div className="empty-state">
            <h2>How can I help you today?</h2>
            <p>Send a message below to start chatting.</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <Message key={i} message={msg} />
        ))}

        {loading && (
          <div className="message-row assistant">
            <div className="message-bubble assistant-card typing-indicator">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </main>

      <footer className="footer-bar">
        <ChatInput
          value={input}
          onChange={setInput}
          onSend={handleSend}
          disabled={loading}
        />
      </footer>
    </div>
  );
}
