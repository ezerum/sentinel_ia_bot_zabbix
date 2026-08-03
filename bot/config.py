from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def _getenv(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return v

@dataclass(frozen=True)
class Settings:
    # Telegram
    telegram_bot_token: str
    allowed_chat_ids: set[int]

    # Zabbix
    zabbix_url: str
    zabbix_api_token: str

    # Logging
    log_level: str
    log_dir: str

    # LLM
    llm_enabled: bool
    llm_endpoint: str
    llm_api_key: str
    llm_model: str
    llm_timeout_s: int
    llm_max_output_tokens: int
    llm_max_chars: int

    # Cost controls
    llm_cache_ttl_s: int
    llm_rate_limit_per_min: int

def load_settings() -> Settings:
    allowed = set()
    raw = os.getenv("ALLOWED_CHAT_IDS", "").strip()
    if raw:
        allowed = {int(x.strip()) for x in raw.split(",") if x.strip()}

    return Settings(
        telegram_bot_token=_getenv("TELEGRAM_BOT_TOKEN"),
        allowed_chat_ids=allowed,

        zabbix_url=_getenv("ZABBIX_URL").rstrip("/"),
        zabbix_api_token=_getenv("ZABBIX_API_TOKEN"),

        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_dir=os.getenv("LOG_DIR", "logs"),

        llm_enabled=os.getenv("LLM_ENABLED", "0") == "1",
        llm_endpoint=os.getenv("LLM_ENDPOINT", "https://api.openai.com/v1/chat/completions"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        llm_timeout_s=int(os.getenv("LLM_TIMEOUT_S", "25")),
        llm_max_output_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "350")),
        llm_max_chars=int(os.getenv("LLM_MAX_CHARS", "4500")),

        llm_cache_ttl_s=int(os.getenv("LLM_CACHE_TTL_S", "900")),
        llm_rate_limit_per_min=int(os.getenv("LLM_RATE_LIMIT_PER_MIN", "6")),
    )
