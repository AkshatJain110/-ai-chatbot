from typing import Optional, List, Literal
from pydantic import BaseModel, field_validator, ConfigDict

class HealthResponse(BaseModel):
    status: str = "ok"
    keys_configured: int
    cache_enabled: bool = True

class ChatRequest(BaseModel):
    session_id: str
    message: str
    system_prompt: Optional[str] = None

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("session_id must be a string")
        s = v.strip()
        if len(s) < 1 or len(s) > 128:
            raise ValueError("session_id must be between 1 and 128 characters")
        return s

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("message must be a string")
        s = v.strip()
        if len(s) < 1:
            raise ValueError("message cannot be empty or whitespace only")
        if len(s) > 4000:
            raise ValueError("message cannot exceed 4000 characters after trimming whitespace")
        return s

class ChatMetadata(BaseModel):
    resolution_source: Literal["LIVE_INFERENCE", "LLM_CACHE"]
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: Optional[str] = None
    fallback_attempts: int

class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata

class MessageItem(BaseModel):
    role: str
    content: str
    metadata: Optional[ChatMetadata] = None

class SessionMessagesResponse(BaseModel):
    session_id: str
    messages: List[MessageItem]
