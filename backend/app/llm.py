import os
import time
from typing import List, Dict, Any, Optional, Tuple
from fastapi import HTTPException

# Silence LiteLLM remote cost map fetching
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import litellm
from litellm.caching.caching import Cache
from litellm.exceptions import (
    RateLimitError,
    InternalServerError,
    ServiceUnavailableError,
    APIConnectionError,
    Timeout,
    APIError,
    AuthenticationError,
    PermissionDeniedError,
    BadRequestError,
)

from .config import settings

# Initialize in-memory local cache on startup
litellm.cache = Cache(type="local")
litellm.suppress_debug_info = True


def parse_simulate_failure_header(header_value: Optional[str]) -> Dict[str, int]:
    """
    Parses comma-separated key_id=status pairs, e.g.:
    'key_1=429,key_2=500' or '*=429'
    Returns dict mapping key_id -> status_code.
    Active ONLY if settings.enable_failure_simulation is True.
    """
    if not settings.enable_failure_simulation or not header_value:
        return {}

    mapping: Dict[str, int] = {}
    tokens = [t.strip() for t in header_value.split(",") if t.strip()]
    for token in tokens:
        if "=" in token:
            k, v = token.split("=", 1)
            k = k.strip()
            v = v.strip()
            if v.isdigit():
                mapping[k] = int(v)
    return mapping


import httpx

def raise_simulated_exception(status_code: int, model: str) -> None:
    """
    Raises the equivalent LiteLLM exception for simulated statuses
    to exercise the real fallback code paths.
    """
    msg = f"Simulated provider failure with HTTP {status_code}"
    provider = "gemini"

    if status_code == 401:
        raise AuthenticationError(message=msg, llm_provider=provider, model=model)
    elif status_code == 403:
        dummy_resp = httpx.Response(status_code=403, request=httpx.Request("POST", "https://generativelanguage.googleapis.com"))
        raise PermissionDeniedError(message=msg, llm_provider=provider, model=model, response=dummy_resp)
    elif status_code == 429:
        raise RateLimitError(message=msg, llm_provider=provider, model=model)
    elif status_code == 408:
        raise Timeout(message=msg, model=model, llm_provider=provider)
    elif status_code == 500:
        raise InternalServerError(message=msg, llm_provider=provider, model=model)
    elif status_code == 502:
        raise APIConnectionError(message=msg, llm_provider=provider, model=model)
    elif status_code == 503:
        raise ServiceUnavailableError(message=msg, llm_provider=provider, model=model)
    elif status_code == 504:
        raise Timeout(message=msg, model=model, llm_provider=provider)
    else:
        # Default 5xx simulation
        raise InternalServerError(message=msg, llm_provider=provider, model=model)


def is_retryable_error(exc: Exception) -> bool:
    """
    Determines if an error warrants failing over to the next key.
    Fails over on:
    - 429, quota errors, resource exhaustion
    - 5xx errors, timeouts, connection errors
    - 401, 403 (authentication/permission errors)
    - 400 where the error message indicates the API key is invalid or expired
    Does NOT fail over on other 4xx client errors (e.g. general 400 bad request).
    """
    if isinstance(exc, (RateLimitError, InternalServerError, ServiceUnavailableError, APIConnectionError, Timeout, AuthenticationError, PermissionDeniedError)):
        return True

    status_code = getattr(exc, "status_code", None)
    if status_code in (401, 403, 429) or (status_code and status_code >= 500):
        return True

    err_msg = str(exc).lower()

    # Quota / rate limit errors
    if any(q in err_msg for q in ("quota", "resource exhausted", "rate limit", "too many requests")):
        return True

    # 400 where message says API key is invalid or expired
    if status_code == 400 or isinstance(exc, BadRequestError):
        key_indicators = ("api key", "api_key", "apikey")
        problem_indicators = ("invalid", "expired", "not valid", "unauthorized", "auth", "permission", "not found")
        if any(k in err_msg for k in key_indicators) and any(p in err_msg for p in problem_indicators):
            return True
        return False

    return False


async def execute_chat_completion(
    messages: List[Dict[str, str]],
    simulate_header: Optional[str] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    Executes chat completion across key pool with fallback logic and caching.
    Returns (reply_text, metadata_dict).
    Raises HTTPException(503, detail="all providers unavailable") if all keys fail.
    """
    start_time = time.perf_counter()
    model = settings.llm_model
    key_pool = settings.key_pool

    if not key_pool:
        raise HTTPException(status_code=503, detail="all providers unavailable")

    simulation_map = parse_simulate_failure_header(simulate_header)
    is_simulated = len(simulation_map) > 0

    fallback_attempts = 0

    for key_id, api_key in key_pool:
        try:
            # Check for simulated failure for this key
            simulated_status: Optional[int] = None
            if is_simulated:
                if key_id in simulation_map:
                    simulated_status = simulation_map[key_id]
                elif "*" in simulation_map:
                    simulated_status = simulation_map["*"]

            if simulated_status is not None:
                raise_simulated_exception(simulated_status, model)

            # Call LiteLLM completion
            # When simulation header is active, bypass cache completely
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                api_key=api_key,
                caching=(not is_simulated),
                timeout=settings.llm_timeout_seconds,
            )

            # Check if this was a cache hit
            is_cache_hit = bool(getattr(response, "_hidden_params", {}).get("cache_hit") is True)

            end_time = time.perf_counter()
            latency_ms = int(round((end_time - start_time) * 1000))

            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

            reply = ""
            if hasattr(response, "choices") and response.choices:
                choice = response.choices[0]
                if hasattr(choice, "message") and hasattr(choice.message, "content"):
                    reply = choice.message.content or ""

            if is_cache_hit:
                metadata = {
                    "resolution_source": "LLM_CACHE",
                    "model": model,
                    "latency_ms": latency_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "key_id": None,
                    "fallback_attempts": 0,
                }
            else:
                metadata = {
                    "resolution_source": "LIVE_INFERENCE",
                    "model": model,
                    "latency_ms": latency_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "key_id": key_id,
                    "fallback_attempts": fallback_attempts,
                }

            return reply, metadata

        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            if is_retryable_error(exc):
                fallback_attempts += 1
                continue
            # Non-retryable error (e.g. invalid request format, 400)
            status_code = getattr(exc, "status_code", None)
            if status_code and 400 <= status_code < 500:
                raise HTTPException(status_code=status_code, detail=str(exc))
            raise HTTPException(status_code=500, detail="LLM provider error")

    # All keys in pool exhausted
    raise HTTPException(status_code=503, detail="all providers unavailable")
