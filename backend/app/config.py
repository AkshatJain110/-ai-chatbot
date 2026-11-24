import os
from typing import List, Tuple
from pathlib import Path
from dotenv import load_dotenv

# Load .env from root directory or working directory
root_env = Path(__file__).resolve().parent.parent.parent / ".env"
if root_env.is_file():
    load_dotenv(dotenv_path=root_env)
load_dotenv()

def get_env_bool(var_name: str, default: bool = False) -> bool:
    val = os.getenv(var_name)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes")

class Settings:
    @property
    def raw_api_keys(self) -> str:
        return os.getenv("LLM_API_KEYS", "")

    @property
    def key_pool(self) -> List[Tuple[str, str]]:
        """
        Returns list of (key_id, api_key) pairs, where key_ids are
        key_1, key_2, ... in order.
        """
        raw = self.raw_api_keys.strip()
        if not raw:
            return []
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        return [(f"key_{i + 1}", key) for i, key in enumerate(keys)]

    @property
    def keys_configured(self) -> int:
        return len(self.key_pool)

    @property
    def database_url(self) -> str:
        return os.getenv("DATABASE_URL", "sqlite:///./app.db")

    @property
    def db_path(self) -> str:
        url = self.database_url
        if url.startswith("sqlite:///"):
            path = url[len("sqlite:///"):]
            return path
        return url

    @property
    def allowed_origins(self) -> List[str]:
        raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,*")
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def enable_failure_simulation(self) -> bool:
        return get_env_bool("ENABLE_FAILURE_SIMULATION", False)

    @property
    def llm_model(self) -> str:
        return os.getenv("LLM_MODEL", "gemini/gemini-2.0-flash")

    @property
    def default_system_prompt(self) -> str:
        return os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful and concise AI assistant.")

settings = Settings()
