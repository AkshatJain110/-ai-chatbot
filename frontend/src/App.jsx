import React, { useState, useEffect, useRef } from 'react';
import './App.css';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function generateRandomSessionId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'sess-' + Date.now() + '-' + Math.random().toString(36).substring(2, 9);
}

export default function App() {
  // New session_id on every page load
  const [sessionId, setSessionId] = useState(() => generateRandomSessionId());
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [theme, setTheme] = useState('light');
  const messagesEndRef = useRef(null);

  // Auto-scroll to latest message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Apply theme to document
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'light' ? 'dark' : 'light'));
  };

  const handleNewChat = () => {
    setSessionId(generateRandomSessionId());
    setMessages([]);
    setInputMessage('');
  };

  const handleSend = async () => {
    const textToSend = inputMessage.trim();
    if (!textToSend || isLoading) return;

    // EXACT requirement: chat-input cleared after send
    setInputMessage('');
    setIsLoading(true);

    // Add user message to UI
    setMessages((prev) => [...prev, { role: 'user', content: textToSend }]);

    // Only call POST /chat (with system_prompt only if the field is non-empty)
    const payload = {
      session_id: sessionId,
      message: textToSend,
    };
    if (systemPrompt && systemPrompt.trim()) {
      payload.system_prompt = systemPrompt.trim();
    }

    try {
      const response = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        let errorMessage = 'An error occurred. Please try again.';
        try {
          const errorData = await response.json();
          if (response.status === 503) {
            // EXACT requirement: for 503 "All providers are unavailable, please try again"
            errorMessage = 'All providers are unavailable, please try again';
          } else if (response.status === 422) {
            // EXACT requirement: for 422 show a friendly message from detail
            if (errorData.detail) {
              if (typeof errorData.detail === 'string') {
                errorMessage = errorData.detail;
              } else if (Array.isArray(errorData.detail)) {
                errorMessage = errorData.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
              } else {
                errorMessage = JSON.stringify(errorData.detail);
              }
            } else {
              errorMessage = 'Validation error: please check your input.';
            }
          } else if (errorData.detail) {
            errorMessage = typeof errorData.detail === 'string' ? errorData.detail : JSON.stringify(errorData.detail);
          }
        } catch {
          if (response.status === 503) {
            errorMessage = 'All providers are unavailable, please try again';
          } else {
            errorMessage = `Server error (${response.status}). Please try again.`;
          }
        }
        setMessages((prev) => [...prev, { role: 'error', content: errorMessage }]);
      } else {
        const data = await response.json();
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: data.reply,
            metadata: data.metadata,
          },
        ]);
      }
    } catch (err) {
      // Network error readable message
      setMessages((prev) => [
        ...prev,
        {
          role: 'error',
          content: 'Network error: Unable to connect to server. Please check your connection and try again.',
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    // Enter sends, Shift+Enter newline
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="chat-app" data-theme={theme}>
      <header className="chat-header">
        <div className="header-main">
          <h1 className="brand-title">AI Chatbot</h1>
          <div className="header-actions">
            <button className="action-btn" onClick={toggleTheme}>
              {theme === 'light' ? '🌙 Dark' : '☀️ Light'}
            </button>
            <button className="action-btn new-chat-btn" onClick={handleNewChat}>
              + New chat
            </button>
          </div>
        </div>
        <div className="system-prompt-container">
          <label htmlFor="sys-prompt" className="system-prompt-label">System Prompt:</label>
          <input
            id="sys-prompt"
            data-testid="system-prompt-input"
            className="system-prompt-field"
            type="text"
            placeholder="Optional custom instructions for assistant..."
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
        </div>
      </header>

      <main className="chat-messages">
        {messages.length === 0 && (
          <div className="welcome-message">
            <h2>Welcome to AI Chatbot</h2>
            <p>Start a conversation by typing below.</p>
          </div>
        )}

        {messages.map((msg, idx) => {
          if (msg.role === 'user') {
            return (
              <div key={idx} className="message-row user">
                <div className="message-bubble">{msg.content}</div>
              </div>
            );
          } else if (msg.role === 'error') {
            return (
              <div key={idx} className="message-row error">
                <div className="error-bubble">{msg.content}</div>
              </div>
            );
          } else {
            // Assistant reply with exact data-testids
            return (
              <div key={idx} className="message-row assistant">
                <div data-testid="assistant-message" className="message-bubble">
                  <div className="message-text">{msg.content}</div>
                  {msg.metadata && (
                    <div className="metadata-bar">
                      <span className="meta-badge">
                        <span className="meta-label">Source:</span>
                        <span data-testid="meta-source">{msg.metadata.resolution_source}</span>
                      </span>
                      <span className="meta-badge">
                        <span className="meta-label">Model:</span>
                        <span data-testid="meta-model">{msg.metadata.model}</span>
                      </span>
                      <span className="meta-badge">
                        <span className="meta-label">Latency:</span>
                        <span data-testid="meta-latency">{`${msg.metadata.latency_ms} ms`}</span>
                      </span>
                      <span className="meta-badge">
                        <span className="meta-label">Input Tokens:</span>
                        <span data-testid="meta-input-tokens">{msg.metadata.input_tokens}</span>
                      </span>
                      <span className="meta-badge">
                        <span className="meta-label">Output Tokens:</span>
                        <span data-testid="meta-output-tokens">{msg.metadata.output_tokens}</span>
                      </span>
                    </div>
                  )}
                </div>
              </div>
            );
          }
        })}

        {isLoading && (
          <div className="message-row assistant">
            <div className="message-bubble typing-bubble">
              <div className="typing-dots">
                <span></span>
                <span></span>
                <span></span>
              </div>
              <span className="typing-text">AI is typing...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </main>

      <footer className="chat-footer">
        <div className="input-container">
          <textarea
            data-testid="chat-input"
            className="chat-input"
            placeholder="Type a message... (Press Enter to send, Shift+Enter for newline)"
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={isLoading}
          />
          <button
            data-testid="send-button"
            className="send-button"
            onClick={handleSend}
            disabled={isLoading || !inputMessage.trim()}
          >
            Send
          </button>
        </div>
      </footer>
    </div>
  );
}
