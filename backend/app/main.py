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
    init_db()
    yield


app = FastAPI(title="AI Chatbot Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Always return JSON with a "detail" key, never HTML or tracebacks
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(exc.errors())},
    )


@app.exception_handler(HTTPException)
async def http_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    if not check_db_health():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable")
    return HealthResponse(status="ok", keys_configured=settings.keys_configured, cache_enabled=True)


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    x_simulate_failure: Optional[str] = Header(None, alias="X-Simulate-Failure"),
):
    with get_connection() as conn:
        active_system_prompt = get_effective_system_prompt(conn, request.session_id, request.system_prompt)
        history = get_conversation_history(conn, request.session_id)

        # Assemble prompt: system prompt, history, then new user message
        llm_messages = [{"role": "system", "content": active_system_prompt}]
        llm_messages.extend(history)
        llm_messages.append({"role": "user", "content": request.message})

        reply, metadata = await execute_chat_completion(
            messages=llm_messages,
            simulate_header=x_simulate_failure,
        )

        # Persist conversation turn only after successful completion
        persist_turn(
            conn=conn,
            session_id=request.session_id,
            system_prompt=active_system_prompt,
            user_msg=request.message,
            assistant_reply=reply,
            metadata=metadata,
        )

        return ChatResponse(session_id=request.session_id, reply=reply, metadata=metadata)


@app.get("/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
async def get_session_messages(session_id: str):
    with get_connection() as conn:
        messages = get_session_messages_for_api(conn, session_id)
        if messages is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        return SessionMessagesResponse(session_id=session_id, messages=messages)
