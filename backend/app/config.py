import os
from pathlib import Path
from dotenv import load_dotenv

# Load root .env if present
root_env = Path(__file__).resolve().parent.parent.parent / ".env"
if root_env.is_file():
    load_dotenv(dotenv_path=root_env)
load_dotenv()


class Settings:
    @property
    def key_pool(self):
        raw = os.getenv("LLM_API_KEYS", "").strip()
        if not raw:
            return []
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        return [(f"key_{i + 1}", key) for i, key in enumerate(keys)]

    @property
    def keys_configured(self):
        return len(self.key_pool)

    @property
    def database_url(self):
        return os.getenv("DATABASE_URL", "sqlite:///./app.db")

    @property
    def db_path(self):
        url = self.database_url
        return url[len("sqlite:///"):] if url.startswith("sqlite:///") else url

    @property
    def allowed_origins(self):
        raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,*")
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def enable_failure_simulation(self):
        val = os.getenv("ENABLE_FAILURE_SIMULATION", "false")
        return val.strip().lower() in ("true", "1", "yes")

    @property
    def llm_model(self):
        return os.getenv("LLM_MODEL", "gemini/gemini-3.5-flash-lite")

    @property
    def llm_timeout_seconds(self):
        try:
            return int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
        except (ValueError, TypeError):
            return 60

    @property
    def default_system_prompt(self):
        return os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful and concise AI assistant.")


settings = Settings()
