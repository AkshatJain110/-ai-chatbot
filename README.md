# AI Chatbot

A simple full-stack chatbot with multi-turn memory, API key failover, and prompt caching.

```
ai-chatbot/
├── backend/          # FastAPI app, SQLite database, and pytest suite
├── frontend/         # React + Vite frontend with plain CSS
├── docker-compose.yml
├── Makefile
└── .env.example
```

## 1. Live URLs
- Frontend: https://ai-chatbot-zeta-orcin.vercel.app
- Backend: https://ai-chatbot-backend-cgfb.onrender.com

## 2. Run locally: with Docker and without

### With Docker
1. Copy the example environment file and add your Gemini API keys:
   `cp .env.example .env`
2. Start the services:
   `make up`
3. Open `http://localhost:3000` for the chat UI and `http://localhost:8000/health` for the API.
4. Stop with `make down`.

### Without Docker
1. Backend:
   ```bash
   cd backend
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
2. Frontend:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

## 3. Design decisions: key fallback, caching, SQLite session storage

**Key fallback**: I configured an ordered key pool `[key_1, key_2, ...]` read from `LLM_API_KEYS`. When a call fails due to rate limits (429), timeouts, server errors (5xx), auth errors (401/403), or expired keys, the code catches the error and retries the prompt with the next key in line. If all keys fail, it returns a 503 error.

**Caching**: I used LiteLLM's in-memory local cache. The cache key is based on the model and the full message history rather than the session ID, so an identical question asked across different sessions returns instantly from cache. Requests using `X-Simulate-Failure` bypass the cache so faults can be tested directly.

**SQLite session storage**: I created a `messages` table and a `sessions` table using Python's built-in `sqlite3` in WAL mode. Turns are committed inside a transaction only after the LLM responds successfully, preventing orphaned user messages on failure. When using Docker, the database is mounted to a named volume at `/data` so conversation history persists across container restarts. I set the model via `LLM_MODEL` to `gemini/gemini-3.5-flash-lite` by default because regular flash models generated reasoning tokens that made responses take 10 to 40 seconds.

## 4. Verification: how to see failover, cache hits and per-message token usage

1. Cache hit:
   Ask a question in one session, then send the exact same message in a new session:
   ```bash
   curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"session_id":"s1","message":"What is the capital of Spain?"}'
   curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"session_id":"s2","message":"What is the capital of Spain?"}'
   ```
   The second call returns in under 100 ms with `resolution_source: "LLM_CACHE"`.

2. Failover simulation:
   Simulate a rate limit on the primary key to verify key_2 answers:
   ```bash
   curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" -H "X-Simulate-Failure: key_1=429" -d '{"session_id":"s3","message":"Hello"}'
   ```
   Simulate all keys failing:
   ```bash
   curl -s -i -X POST http://localhost:8000/chat -H "Content-Type: application/json" -H "X-Simulate-Failure: *=429" -d '{"session_id":"s4","message":"Hello"}'
   ```
   This returns 503. Checking history returns 404 because failed turns are never saved:
   ```bash
   curl -s -i http://localhost:8000/sessions/s4/messages
   ```

3. Token usage:
   Tokens show directly underneath each assistant reply in the UI (Input tokens and Output tokens) and in the API response metadata. Multi-turn chats show input tokens increasing as conversation history is sent.

## 5. Setup Used: 
I built this on macOS using VS Code as my primary editor. I used Antigravity as my AI pair programmer to assist with design and implementation, Google Gemini (via LiteLLM) for LLM completions, and Docker Desktop for containerization.

## 6. Bonus features 
- Light and dark theme toggle remembering preferences in localStorage.
- Animated typing indicator while waiting for replies.
- New chat button that generates a fresh random session ID.
- Configurable per-key timeout (`LLM_TIMEOUT_SECONDS`) triggering automatic failover.
- Failover handling for 401, 403, and expired-key 400 errors.
- 14 automated backend tests covering the full API contract.
- System prompt support is fully implemented in the backend API (turn 1 persists for the session), though omitted from the UI to keep the interface clean.
