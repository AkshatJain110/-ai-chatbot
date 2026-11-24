const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function sendChatMessage(sessionId, message) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message }),
  });

  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      if (res.status === 503) {
        detail = 'All providers are unavailable, please try again';
      } else if (res.status === 422) {
        if (typeof data.detail === 'string') {
          detail = data.detail;
        } else if (Array.isArray(data.detail)) {
          detail = data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
        } else {
          detail = JSON.stringify(data.detail);
        }
      } else if (data.detail) {
        detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      detail = res.status === 503
        ? 'All providers are unavailable, please try again'
        : `Server error (${res.status})`;
    }
    throw new Error(detail || 'Request failed');
  }

  return res.json();
}
