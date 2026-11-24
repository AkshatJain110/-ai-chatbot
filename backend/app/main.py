from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import (
    init_db,
    check_db_health,
    get_connection,
    get_effective_system_prompt,
    get_conversation_history,
    get_session_messages_for_api,
    persist_turn,
)
from .schemas import (
    HealthResponse,
    ChatRequest,
    ChatResponse,
    SessionMessagesResponse,
)
from .llm import execute_chat_completion


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB directory and tables on startup
    init_db()
    yield


app = FastAPI(title="AI Chatbot Backend", lifespan=lifespan)

# CORS Configuration
origins = settings.allowed_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global Exception Handlers ensuring JSON responses with "detail", never stack traces
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(exc.errors())},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# EXACTLY 3 ENDPOINTS:

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    1. GET /health -> 200 {"status":"ok","keys_configured":<n>,"cache_enabled":true}
    Only succeeds after DB is reachable and key pool is loaded.
    """
    if not check_db_health():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable"
        )

    return HealthResponse(
        status="ok",
        keys_configured=settings.keys_configured,
        cache_enabled=True,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    x_simulate_failure: Optional[str] = Header(None, alias="X-Simulate-Failure"),
):
    """
    2. POST /chat
    Multi-turn conversation with key-pool failover, caching, and persistence.
    """
    with get_connection() as conn:
        # Determine effective system prompt without saving yet
        active_system_prompt = get_effective_system_prompt(
            conn, request.session_id, request.system_prompt
        )

        # Retrieve prior history (chronological user and assistant messages)
        history = get_conversation_history(conn, request.session_id)

        # Build full message list: [system] + history + [new user message]
        llm_messages = [{"role": "system", "content": active_system_prompt}]
        llm_messages.extend(history)
        llm_messages.append({"role": "user", "content": request.message})

        # Execute completion through LiteLLM with fallback and caching
        reply, metadata = await execute_chat_completion(
            messages=llm_messages,
            simulate_header=x_simulate_failure,
        )

        # Persist session & messages ONLY AFTER a successful reply
        persist_turn(
            conn=conn,
            session_id=request.session_id,
            system_prompt=active_system_prompt,
            user_content=request.message,
            assistant_content=reply,
            assistant_metadata=metadata,
        )

        return ChatResponse(
            session_id=request.session_id,
            reply=reply,
            metadata=metadata,
        )


@app.get("/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
async def get_session_messages(session_id: str):
    """
    3. GET /sessions/{session_id}/messages
    Returns oldest-first messages with assistant metadata, NO system prompt.
    404 if session does not exist.
    """
    with get_connection() as conn:
        messages = get_session_messages_for_api(conn, session_id)
        if messages is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="session not found"
            )

        return SessionMessagesResponse(
            session_id=session_id,
            messages=messages,
        )
