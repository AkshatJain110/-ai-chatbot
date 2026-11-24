import React from 'react';

// Render **bold** markdown tags without external libraries
function renderFormatted(text) {
  if (!text) return null;
  const parts = text.split(/(\*\*.*?\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

export default function Message({ message }) {
  const { role, content, metadata } = message;

  if (role === 'user') {
    return (
      <div className="message-row user">
        <div className="message-bubble user-bubble">{content}</div>
      </div>
    );
  }

  if (role === 'error') {
    return (
      <div className="message-row error">
        <div className="error-card">{content}</div>
      </div>
    );
  }

  const isCache = metadata?.resolution_source === 'LLM_CACHE';

  return (
    <div className="message-row assistant">
      <div data-testid="assistant-message" className="message-bubble assistant-card">
        <div className="message-text">{renderFormatted(content)}</div>

        {metadata && (
          <div className="meta-row">
            <span className={`pill ${isCache ? 'pill-cache' : 'pill-live'}`}>
              <span data-testid="meta-source">{metadata.resolution_source}</span>
            </span>

            <span className="meta-item">
              <span className="meta-label">Model:</span>
              <span data-testid="meta-model">{metadata.model}</span>
            </span>

            <span className="meta-item">
              <span className="meta-label">Latency:</span>
              <span data-testid="meta-latency">{`${metadata.latency_ms} ms`}</span>
            </span>

            <span className="meta-item">
              <span className="meta-label">Input:</span>
              <span data-testid="meta-input-tokens">{metadata.input_tokens}</span>
            </span>

            <span className="meta-item">
              <span className="meta-label">Output:</span>
              <span data-testid="meta-output-tokens">{metadata.output_tokens}</span>
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
