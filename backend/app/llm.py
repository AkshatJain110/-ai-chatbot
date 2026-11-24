import os
import time
from typing import List, Dict, Any, Optional, Tuple
from fastapi import HTTPException
import httpx
import litellm
from litellm.caching.caching import Cache
from litellm.exceptions import (
    RateLimitError,
    InternalServerError,
    ServiceUnavailableError,
    APIConnectionError,
    Timeout,
    AuthenticationError,
    PermissionDeniedError,
    BadRequestError,
)
from .config import settings

# In-memory prompt cache
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
litellm.cache = Cache(type="local")
litellm.suppress_debug_info = True


def parse_simulate_failure(header_val: Optional[str]) -> Dict[str, int]:
    # Parse header e.g. 'key_1=429,key_2=500' or '*=429'
    if not settings.enable_failure_simulation or not header_val:
        return {}
    mapping = {}
    for part in header_val.split(","):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            if v.strip().isdigit():
                mapping[k.strip()] = int(v.strip())
    return mapping


def raise_simulated_error(code: int, model: str) -> None:
    msg = f"Simulated error {code}"
    if code == 401:
        raise AuthenticationError(message=msg, llm_provider="gemini", model=model)
    elif code == 403:
        resp = httpx.Response(status_code=403, request=httpx.Request("POST", "https://generativelanguage.googleapis.com"))
        raise PermissionDeniedError(message=msg, llm_provider="gemini", model=model, response=resp)
    elif code == 429:
        raise RateLimitError(message=msg, llm_provider="gemini", model=model)
    elif code in (408, 504):
        raise Timeout(message=msg, model=model, llm_provider="gemini")
    elif code == 502:
        raise APIConnectionError(message=msg, llm_provider="gemini", model=model)
    elif code == 503:
        raise ServiceUnavailableError(message=msg, llm_provider="gemini", model=model)
    raise InternalServerError(message=msg, llm_provider="gemini", model=model)


def is_retryable(exc: Exception) -> bool:
    # Fail over on rate limits, server errors, auth errors, and expired keys
    if isinstance(exc, (RateLimitError, InternalServerError, ServiceUnavailableError, APIConnectionError, Timeout, AuthenticationError, PermissionDeniedError)):
        return True
    code = getattr(exc, "status_code", None)
    if code in (401, 403, 429) or (code and code >= 500):
        return True
    msg = str(exc).lower()
    if any(q in msg for q in ("quota", "resource exhausted", "rate limit", "too many requests")):
        return True
    if code == 400 or isinstance(exc, BadRequestError):
        has_key = any(k in msg for k in ("api key", "api_key", "apikey"))
        has_issue = any(p in msg for p in ("invalid", "expired", "not valid", "unauthorized", "auth", "permission", "not found"))
        return has_key and has_issue
    return False


async def execute_chat_completion(
    messages: List[Dict[str, str]],
    simulate_header: Optional[str] = None
) -> Tuple[str, Dict[str, Any]]:
    start_time = time.perf_counter()
    model = settings.llm_model
    key_pool = settings.key_pool

    if not key_pool:
        raise HTTPException(status_code=503, detail="all providers unavailable")

    sim_map = parse_simulate_failure(simulate_header)
    is_simulated = len(sim_map) > 0
    fallback_attempts = 0

    # Failover loop across configured keys
    for key_id, api_key in key_pool:
        try:
            # Check for simulated error for this key
            sim_code = sim_map.get(key_id) if key_id in sim_map else sim_map.get("*")
            if sim_code is not None:
                raise_simulated_error(sim_code, model)

            # Simulated requests bypass caching
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                api_key=api_key,
                caching=(not is_simulated),
                timeout=settings.llm_timeout_seconds,
            )

            # Check if reply came from in-memory cache
            is_cache = bool(getattr(response, "_hidden_params", {}).get("cache_hit") is True)
            latency_ms = int(round((time.perf_counter() - start_time) * 1000))

            usage = getattr(response, "usage", None)
            in_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            out_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

            reply = ""
            if hasattr(response, "choices") and response.choices:
                choice = response.choices[0]
                if hasattr(choice, "message") and hasattr(choice.message, "content"):
                    reply = choice.message.content or ""

            metadata = {
                "resolution_source": "LLM_CACHE" if is_cache else "LIVE_INFERENCE",
                "model": model,
                "latency_ms": latency_ms,
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "key_id": None if is_cache else key_id,
                "fallback_attempts": 0 if is_cache else fallback_attempts,
            }
            return reply, metadata

        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            if is_retryable(exc):
                fallback_attempts += 1
                continue
            code = getattr(exc, "status_code", None)
            if code and 400 <= code < 500:
                raise HTTPException(status_code=code, detail=str(exc))
            raise HTTPException(status_code=500, detail="LLM provider error")

    # All keys exhausted
    raise HTTPException(status_code=503, detail="all providers unavailable")
