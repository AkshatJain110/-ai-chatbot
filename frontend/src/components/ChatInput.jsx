import React, { useRef, useEffect } from 'react';

export default function ChatInput({ value, onChange, onSend, disabled }) {
  const textareaRef = useRef(null);

  // Auto-grow textarea up to 160px
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }
  }, [value]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!disabled && value.trim()) {
        onSend();
      }
    }
  };

  return (
    <div className="input-bar">
      <textarea
        ref={textareaRef}
        data-testid="chat-input"
        className="chat-textarea"
        placeholder="Type a message... (Enter to send, Shift+Enter for newline)"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        rows={1}
        disabled={disabled}
      />
      <button
        data-testid="send-button"
        className="send-btn"
        onClick={onSend}
        disabled={disabled || !value.trim()}
      >
        Send
      </button>
    </div>
  );
}
