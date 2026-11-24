# Full-Stack AI Chatbot

A production-ready full-stack AI chatbot with multi-turn conversation memory, automatic API key failover, response caching, and a responsive React frontend.

---

## 1. Live URLs

- **Frontend Application**: `http://localhost:3000` *(Placeholder / Deployed URL)*
- **Backend API**: `http://localhost:8000` *(Placeholder / Deployed URL)*
- **Health Check Endpoint**: `http://localhost:8000/health`
- **Interactive API Documentation**: `http://localhost:8000/docs`

---

## 2. Run locally: with Docker and without

### Prerequisites
- Python 3.12+ (or 3.13+)
- Node.js 18+ and npm
- Docker and Docker Compose (for containerized execution)
- At least one Google Gemini API key (two or more recommended to exercise key failover)

### Environment Configuration
Create a `.env` file in the project root by copying `.env.example`:
```bash
cp .env.example .env
```
Edit `.env` to supply your Gemini API keys:
```env
LLM_API_KEYS=your_first_gemini_key,your_second_gemini_key
LLM_MODEL=gemini/gemini-3.5-flash
LLM_TIMEOUT_SECONDS=60
DEFAULT_SYSTEM_PROMPT=You are a helpful and concise AI assistant.
ENABLE_FAILURE_SIMULATION=true
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
DATABASE_URL=sqlite:///./app.db
```

---

### Option A: Run with Docker Compose (Recommended)

1. **Start all services in background**:
   ```bash
   make up
   ```
   *(Or run `docker compose up --build -d` directly)*

2. **Access the application**:
   - Frontend: Open `http://localhost:3000` in your browser.
   - Backend API: `http://localhost:8000` (Health: `http://localhost:8000/health`).

3. **Stop the services**:
   ```bash
   make down
   ```
   *(Or run `docker compose down`)*. Note that conversation history persists across container restarts thanks to the named volume `chatbot_data` mounted at `/data`.

---

### Option B: Run without Docker

#### 1. Backend Setup
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
The backend server runs on `http://127.0.0.1:8000`.

To run backend tests:
```bash
PYTHONPATH=. pytest -v tests
```

#### 2. Frontend Setup
In a new terminal:
```bash
cd frontend
npm install
npm run dev
```
The frontend Vite development server runs on `http://localhost:3000` and communicates with the backend on `http://localhost:8000`.

---

## 3. Design decisions: key fallback, caching, SQLite session storage

### Key Fallback Mechanism
- **Ordered Key Pool**: Configured keys are parsed from `LLM_API_KEYS` into an ordered sequence `[key_1, key_2, ...]`.
- **Targeted Failover**: Requests start on `key_1`. If a retryable failure occurs (HTTP 429 quota exhaustion, 5xx server errors, 401/403 authentication/permission errors, request timeouts via `LLM_TIMEOUT_SECONDS`, or 400 with invalid API key), the system seamlessly catches the error, increments `fallback_attempts`, and retries the exact prompt on `key_2`.
- **Non-retryable Error Guard**: Client-side syntax errors (general 400 Bad Request) are immediately propagated to avoid useless retries.
- **503 Exhaustion**: If every key in the pool is exhausted, the endpoint returns an HTTP 503 `{"detail": "all providers unavailable"}` without persisting failed messages.

### Exact Caching
- **LiteLLM Local Cache**: An in-memory cache (`Cache(type="local")`) caches prompt completions keyed on model and message payload.
- **Cross-Session Optimization**: When a user in session `B` sends an identical query previously answered in session `A`, it returns `LLM_CACHE` in ~100 ms instead of 10-20 seconds of live inference.
- **Cache Hit Metadata**: Cache hits report `resolution_source: "LLM_CACHE"`, `key_id: null`, and `fallback_attempts: 0`, while preserving token metrics and response text.
- **Simulation Bypass**: When failure simulation headers (`X-Simulate-Failure`) are present, caching is completely bypassed (`caching=False`) so simulated faults hit provider logic directly.

### SQLite Session Storage
- **Built-in `sqlite3`**: Standard library `sqlite3` with WAL (`Write-Ahead Logging`) mode for fast concurrent reads and writes without heavy ORM overhead.
- **Atomic Turn Persistence**: Both user and assistant turns are stored within an atomic transaction only after a successful LLM completion. If an LLM call fails, no orphaned user message or session row is written.
- **System Prompt Statefulness**: An initial `system_prompt` provided on turn 1 is persisted on the session row and automatically prepended to LLM context on all subsequent turns without requiring the client to retransmit it.
- **Session Isolation**: Messages are strictly scoped by `session_id`. Querying unknown sessions returns HTTP 404 `{"detail": "session not found"}`.

---

## 4. Verification: how to see failover, cache hits and per-message token usage (include curl commands with X-Simulate-Failure)

### 1. Live Inference vs. Cache Hit
Send a request to a new session:
```bash
curl -s -X POST http://127.0.0.1:8000/chat   -H "Content-Type: application/json"   -d '{"session_id": "demo-cache-1", "message": "What is the capital of France?"}'
```
**Output**: `resolution_source: "LIVE_INFERENCE"`, `key_id: "key_1"`, latency ~10-15 seconds.

Send the **exact same message** in a completely new session:
```bash
curl -s -X POST http://127.0.0.1:8000/chat   -H "Content-Type: application/json"   -d '{"session_id": "demo-cache-2", "message": "What is the capital of France?"}'
```
**Output**: `resolution_source: "LLM_CACHE"`, `key_id: null`, latency < 100 ms.

---

### 2. Provider Failover via `X-Simulate-Failure`

#### Failover from `key_1` to `key_2` on 429 Rate Limit:
```bash
curl -s -X POST http://127.0.0.1:8000/chat   -H "Content-Type: application/json"   -H "X-Simulate-Failure: key_1=429"   -d '{"session_id": "demo-failover-1", "message": "Tell me a joke about robots."}'
```
**Output**: Status 200, `key_id: "key_2"`, `fallback_attempts: 1`.

#### Failover from `key_1` on 500 Internal Server Error:
```bash
curl -s -X POST http://127.0.0.1:8000/chat   -H "Content-Type: application/json"   -H "X-Simulate-Failure: key_1=500"   -d '{"session_id": "demo-failover-2", "message": "What is the speed of light?"}'
```
**Output**: Status 200, `key_id: "key_2"`, `fallback_attempts: 1`.

#### All Keys Fail (HTTP 503) + History Not Saved:
```bash
curl -s -i -X POST http://127.0.0.1:8000/chat   -H "Content-Type: application/json"   -H "X-Simulate-Failure: *=429"   -d '{"session_id": "demo-exhausted", "message": "This message will fail."}'
```
**Output**: `HTTP/1.1 503 Service Unavailable`, `{"detail": "all providers unavailable"}`.

Check history (must return 404 because no history was stored):
```bash
curl -s -i http://127.0.0.1:8000/sessions/demo-exhausted/messages
```
**Output**: `HTTP/1.1 404 Not Found`, `{"detail": "session not found"}`.

---

### 3. Per-Message Token Verification
Send first turn:
```bash
curl -s -X POST http://127.0.0.1:8000/chat   -H "Content-Type: application/json"   -d '{"session_id": "demo-tokens", "message": "My name is Alice."}'
```
Observe `input_tokens: ~16`.

Send second turn:
```bash
curl -s -X POST http://127.0.0.1:8000/chat   -H "Content-Type: application/json"   -d '{"session_id": "demo-tokens", "message": "What is my name?"}'
```
Observe `input_tokens: ~40`. The input tokens include previous context turns, demonstrating conversational memory while reporting per-request metrics rather than cumulative output counters.

---

## 5. Setup Used: your editor and AI tools (Antigravity, Gemini)

- **AI Pair Programmer**: Antigravity with Google DeepMind agentic coding architecture.
- **Foundation LLM**: Google Gemini 3.5 Flash (`gemini/gemini-3.5-flash`) via LiteLLM for inference, conversational reasoning, and testing.
- **Development Tooling**:
  - Python 3.12/3.13, FastAPI, Uvicorn, SQLite3 (WAL mode)
  - Pytest + Pytest-Asyncio for automated test suites
  - React 18, Vite 5, Plain CSS for responsive, lightweight frontend
  - Docker & Docker Compose for multi-stage containerization
  - Make for unified developer ergonomics (`make up`, `make down`)

---

## 6. Bonus features

- **Light and Dark Theme**: Built-in CSS variables toggle supporting instant theme switching with seamless contrast in both modes.
- **Request Timeout Failover**: Configurable `LLM_TIMEOUT_SECONDS` (default 60s) ensures hanging requests fail over to secondary keys without freezing the user interface.
- **Stateful System Prompts**: Custom assistant persona persists across subsequent turns in the session without needing to resend the prompt.
- **Real-time Typing Animation**: Non-blocking typing indicator with animated pulses and status feedback during LLM inference.
- **Graceful Error Banners**: Contextual, readable in-chat error displays for 422 validation errors, 503 provider outages, and network failures.
- **Zero Heavy Dependencies**: Pure standard library SQLite, LiteLLM, native React state, and pure CSS without bulky ORMs or UI libraries.
