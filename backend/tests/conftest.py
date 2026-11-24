import os
import pytest
from fastapi.testclient import TestClient

@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    test_db = tmp_path / "test_app.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db}")
    monkeypatch.setenv("LLM_API_KEYS", "mock_key_1,mock_key_2,mock_key_3")
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "true")
    monkeypatch.setenv("LLM_MODEL", "gemini/gemini-2.0-flash")
    monkeypatch.setenv("DEFAULT_SYSTEM_PROMPT", "Test System Prompt")

    from backend.app.config import settings
    from backend.app.db import init_db
    import litellm
    from litellm.caching.caching import Cache

    # Reset cache
    litellm.cache = Cache(type="local")
    init_db(str(test_db))
    yield

@pytest.fixture
def client():
    from backend.app.main import app
    with TestClient(app) as test_client:
        yield test_client
