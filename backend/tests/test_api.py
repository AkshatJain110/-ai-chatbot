import pytest
from unittest.mock import patch
from litellm.types.utils import ModelResponse, Choices, Message, Usage


def create_mock_model_response(content: str = "Mocked LLM reply", prompt_tokens: int = 15, completion_tokens: int = 25):
    return ModelResponse(
        choices=[Choices(message=Message(content=content, role="assistant"))],
        usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=prompt_tokens + completion_tokens)
    )


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["keys_configured"] == 3
    assert data["cache_enabled"] is True


def test_validation_errors_422(client):
    # Missing session_id
    res = client.post("/chat", json={"message": "hello"})
    assert res.status_code == 422
    assert "detail" in res.json()

    # Empty / whitespace-only session_id
    res = client.post("/chat", json={"session_id": "   ", "message": "hello"})
    assert res.status_code == 422
    assert "detail" in res.json()

    # Missing message
    res = client.post("/chat", json={"session_id": "s1"})
    assert res.status_code == 422
    assert "detail" in res.json()

    # Empty / whitespace-only message
    res = client.post("/chat", json={"session_id": "s1", "message": "   \n\t  "})
    assert res.status_code == 422
    assert "detail" in res.json()

    # Message > 4000 characters
    long_msg = "a" * 4001
    res = client.post("/chat", json={"session_id": "s1", "message": long_msg})
    assert res.status_code == 422
    assert "detail" in res.json()

    # Malformed JSON body
    res = client.post(
        "/chat",
        content="not-json",
        headers={"Content-Type": "application/json"}
    )
    assert res.status_code == 422
    assert "detail" in res.json()


def test_unknown_session_404(client):
    res = client.get("/sessions/unknown_session_id_123/messages")
    assert res.status_code == 404
    assert res.json() == {"detail": "session not found"}


@pytest.mark.asyncio
async def test_chat_success_and_metadata(client):
    mock_resp = create_mock_model_response("Hello from Gemini!", prompt_tokens=12, completion_tokens=8)

    with patch("litellm.acompletion", return_value=mock_resp):
        res = client.post("/chat", json={"session_id": "test_session_1", "message": "Hello!"})

    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] == "test_session_1"
    assert data["reply"] == "Hello from Gemini!"

    meta = data["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "gemini/gemini-2.0-flash"
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0
    assert meta["input_tokens"] == 12
    assert meta["output_tokens"] == 8
    assert isinstance(meta["latency_ms"], int)


@pytest.mark.asyncio
async def test_failover_429_and_500(client):
    mock_resp = create_mock_model_response("Reply after failover", prompt_tokens=10, completion_tokens=15)

    # key_1 fails with 429 -> should fall over to key_2 with fallback_attempts=1
    with patch("litellm.acompletion", return_value=mock_resp) as mock_call:
        res = client.post(
            "/chat",
            json={"session_id": "failover_sess_1", "message": "test 429"},
            headers={"X-Simulate-Failure": "key_1=429"}
        )
    assert res.status_code == 200
    data = res.json()
    assert data["metadata"]["key_id"] == "key_2"
    assert data["metadata"]["fallback_attempts"] == 1

    # key_1 fails with 500 -> should fall over to key_2 with fallback_attempts=1
    with patch("litellm.acompletion", return_value=mock_resp):
        res = client.post(
            "/chat",
            json={"session_id": "failover_sess_2", "message": "test 500"},
            headers={"X-Simulate-Failure": "key_1=500"}
        )
    assert res.status_code == 200
    data = res.json()
    assert data["metadata"]["key_id"] == "key_2"
    assert data["metadata"]["fallback_attempts"] == 1

    # key_1 fails with 429, key_2 fails with 502 -> should succeed on key_3 with fallback_attempts=2
    with patch("litellm.acompletion", return_value=mock_resp):
        res = client.post(
            "/chat",
            json={"session_id": "failover_sess_3", "message": "test multi failover"},
            headers={"X-Simulate-Failure": "key_1=429,key_2=502"}
        )
    assert res.status_code == 200
    data = res.json()
    assert data["metadata"]["key_id"] == "key_3"
    assert data["metadata"]["fallback_attempts"] == 2


@pytest.mark.asyncio
async def test_all_keys_fail_503_and_no_history_stored(client):
    # *=429 simulates failure across all keys
    res = client.post(
        "/chat",
        json={"session_id": "failed_sess", "message": "Should not be saved"},
        headers={"X-Simulate-Failure": "*=429"}
    )
    assert res.status_code == 503
    assert res.json() == {"detail": "all providers unavailable"}

    # Verify that session history was NOT written (must return 404)
    history_res = client.get("/sessions/failed_sess/messages")
    assert history_res.status_code == 404
    assert history_res.json() == {"detail": "session not found"}


@pytest.mark.asyncio
async def test_cache_hit_behavior(client):
    mock_resp_1 = create_mock_model_response("Cached answer text", prompt_tokens=14, completion_tokens=22)

    # First call: live inference
    with patch("litellm.acompletion", return_value=mock_resp_1):
        res1 = client.post(
            "/chat",
            json={"session_id": "cache_session_1", "message": "What is 2+2?"}
        )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["metadata"]["resolution_source"] == "LIVE_INFERENCE"

    # Mock LiteLLM returning cache hit for the identical message
    mock_resp_cached = create_mock_model_response("Cached answer text", prompt_tokens=14, completion_tokens=22)
    mock_resp_cached._hidden_params = {"cache_hit": True}

    # Second call in a NEW session with identical message -> returns LLM_CACHE
    with patch("litellm.acompletion", return_value=mock_resp_cached):
        res2 = client.post(
            "/chat",
            json={"session_id": "cache_session_2", "message": "What is 2+2?"}
        )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["reply"] == "Cached answer text"
    meta2 = data2["metadata"]
    assert meta2["resolution_source"] == "LLM_CACHE"
    assert meta2["key_id"] is None
    assert meta2["fallback_attempts"] == 0
    assert meta2["input_tokens"] == 14
    assert meta2["output_tokens"] == 22


@pytest.mark.asyncio
async def test_multi_turn_memory_and_system_prompt_persistence(client):
    captured_messages = []

    async def fake_acompletion(**kwargs):
        captured_messages.append(kwargs["messages"])
        return create_mock_model_response(f"Reply #{len(captured_messages)}")

    session_id = "multi_turn_sess"
    custom_sys = "You are a specialized pirate bot."

    # Turn 1
    with patch("litellm.acompletion", side_effect=fake_acompletion):
        res1 = client.post(
            "/chat",
            json={
                "session_id": session_id,
                "message": "Ahoy there!",
                "system_prompt": custom_sys
            }
        )
    assert res1.status_code == 200

    # Verify Turn 1 message structure sent to LLM
    first_call_msgs = captured_messages[0]
    assert first_call_msgs[0] == {"role": "system", "content": custom_sys}
    assert first_call_msgs[1] == {"role": "user", "content": "Ahoy there!"}

    # Turn 2 (no system prompt passed; should retain custom_sys from session)
    with patch("litellm.acompletion", side_effect=fake_acompletion):
        res2 = client.post(
            "/chat",
            json={
                "session_id": session_id,
                "message": "What is my cargo?"
            }
        )
    assert res2.status_code == 200

    # Verify Turn 2 message structure has system prompt + history + new message
    second_call_msgs = captured_messages[1]
    assert len(second_call_msgs) == 4
    assert second_call_msgs[0] == {"role": "system", "content": custom_sys}
    assert second_call_msgs[1] == {"role": "user", "content": "Ahoy there!"}
    assert second_call_msgs[2] == {"role": "assistant", "content": "Reply #1"}
    assert second_call_msgs[3] == {"role": "user", "content": "What is my cargo?"}


@pytest.mark.asyncio
async def test_history_endpoint_shape_and_session_isolation(client):
    mock_resp = create_mock_model_response("Assistant response", prompt_tokens=10, completion_tokens=15)

    with patch("litellm.acompletion", return_value=mock_resp):
        client.post("/chat", json={"session_id": "sess_A", "message": "Message for A"})
        client.post("/chat", json={"session_id": "sess_B", "message": "Message for B"})

    # Check history of sess_A
    res_a = client.get("/sessions/sess_A/messages")
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["session_id"] == "sess_A"
    assert len(data_a["messages"]) == 2

    # Oldest first: user first, assistant second
    user_msg = data_a["messages"][0]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "Message for A"
    assert "metadata" not in user_msg or user_msg.get("metadata") is None

    asst_msg = data_a["messages"][1]
    assert asst_msg["role"] == "assistant"
    assert asst_msg["content"] == "Assistant response"
    assert asst_msg["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert asst_msg["metadata"]["input_tokens"] == 10

    # Verify session isolation: sess_B has only its own message
    res_b = client.get("/sessions/sess_B/messages")
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert len(data_b["messages"]) == 2
    assert data_b["messages"][0]["content"] == "Message for B"


@pytest.mark.asyncio
async def test_per_request_tokens_not_cumulative(client):
    """
    Two equal-length first messages in two new sessions report about the same input_tokens.
    Tokens must be per-request, never running totals.
    """
    mock_resp_1 = create_mock_model_response("Reply 1", prompt_tokens=15, completion_tokens=10)
    mock_resp_2 = create_mock_model_response("Reply 2", prompt_tokens=15, completion_tokens=10)

    with patch("litellm.acompletion", side_effect=[mock_resp_1, mock_resp_2]):
        res1 = client.post("/chat", json={"session_id": "tokens_sess_1", "message": "First prompt message"})
        res2 = client.post("/chat", json={"session_id": "tokens_sess_2", "message": "First prompt message"})

    meta1 = res1.json()["metadata"]
    meta2 = res2.json()["metadata"]
    assert meta1["input_tokens"] == 15
    assert meta2["input_tokens"] == 15
    assert meta1["input_tokens"] == meta2["input_tokens"]


@pytest.mark.asyncio
async def test_non_retryable_400_does_not_failover(client):
    """
    Do not fail over on 4xx client errors like 400 invalid request unless it is 429/quota.
    """
    from litellm.exceptions import BadRequestError

    bad_request_exc = BadRequestError(
        message="Bad request: Invalid argument",
        model="gemini/gemini-2.0-flash",
        llm_provider="gemini"
    )

    call_count = 0

    async def fail_with_bad_request(**kwargs):
        nonlocal call_count
        call_count += 1
        raise bad_request_exc

    with patch("litellm.acompletion", side_effect=fail_with_bad_request):
        res = client.post("/chat", json={"session_id": "sess_400", "message": "Trigger bad request"})

    # Should raise error and NOT iterate through all 3 keys
    assert call_count == 1
    assert res.status_code == 500 or res.status_code == 400
    assert "detail" in res.json()


@pytest.mark.asyncio
async def test_failover_on_401_403_and_invalid_key_400(client):
    """
    Treat HTTP 401/403, and 400 with invalid/expired API key as failover-worthy.
    """
    from litellm.exceptions import AuthenticationError, PermissionDeniedError, BadRequestError

    mock_success = create_mock_model_response("Success reply", prompt_tokens=10, completion_tokens=10)

    # 1. 401 failover: key_1 raises 401, key_2 succeeds
    with patch("litellm.acompletion", side_effect=[
        AuthenticationError("Invalid API key", "gemini", "gemini/gemini-2.0-flash"),
        mock_success
    ]):
        res1 = client.post("/chat", json={"session_id": "auth_sess_1", "message": "hello"})
    assert res1.status_code == 200
    assert res1.json()["metadata"]["key_id"] == "key_2"
    assert res1.json()["metadata"]["fallback_attempts"] == 1

    # 2. 403 failover: key_1 raises 403, key_2 succeeds
    import httpx
    dummy_resp = httpx.Response(status_code=403, request=httpx.Request("POST", "https://api.fake.com"))
    with patch("litellm.acompletion", side_effect=[
        PermissionDeniedError("Permission denied for API key", "gemini", "gemini/gemini-2.0-flash", response=dummy_resp),
        mock_success
    ]):
        res2 = client.post("/chat", json={"session_id": "auth_sess_2", "message": "hello"})
    assert res2.status_code == 200
    assert res2.json()["metadata"]["key_id"] == "key_2"
    assert res2.json()["metadata"]["fallback_attempts"] == 1

    # 3. 400 with invalid API key in message: key_1 fails, key_2 succeeds
    with patch("litellm.acompletion", side_effect=[
        BadRequestError("API_KEY_INVALID: The provided API key is expired or invalid", "gemini/gemini-2.0-flash", "gemini"),
        mock_success
    ]):
        res3 = client.post("/chat", json={"session_id": "auth_sess_3", "message": "hello"})
    assert res3.status_code == 200
    assert res3.json()["metadata"]["key_id"] == "key_2"
    assert res3.json()["metadata"]["fallback_attempts"] == 1


def test_global_exception_handler_returns_json_never_stack_trace():
    """
    Global exception handler returns JSON {"detail": ...} on 500, never HTML or stack trace.
    """
    from backend.app.main import app
    from starlette.testclient import TestClient

    client_no_raise = TestClient(app, raise_server_exceptions=False)
    with patch("backend.app.main.check_db_health", side_effect=RuntimeError("Unexpected database crash")):
        res = client_no_raise.get("/health")
    assert res.status_code == 500
    data = res.json()
    assert "detail" in data
    assert data["detail"] == "Internal server error"

