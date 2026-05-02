import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv(override=True)


@dataclass(frozen=True)
class Settings:
    DISCUZ_BASE_URL: str
    DISCUZ_USERNAME: str
    DISCUZ_PASSWORD: str

    DB_PATH: str

    BOT_COOKIE_FILE: str
    BOT_LOCK_FILE: str

    WORKER_SLEEP_SECONDS: int
    MAX_RETRY_COUNT: int

    SCANNER_FORUM_IDS: list[int]
    SCANNER_INTERVAL_SECONDS: int
    SCANNER_PAGE_LIMIT: int
    QUOTE_CHECK_INTERVAL_SECONDS: int

    LLM_BASE_URL: str
    LLM_API_KEY: str
    LLM_MODEL: str
    LLM_SYSTEM_PROMPT: str

'''
this should be rewritten due to the principal of "let it crash"
'''
def _load_settings() -> Settings:
    username = os.getenv("DISCUZ_USERNAME", "bot_user")
    return Settings(
        DISCUZ_BASE_URL=os.getenv("DISCUZ_BASE_URL", "").rstrip("/"),
        DISCUZ_USERNAME=username,
        DISCUZ_PASSWORD=os.getenv("DISCUZ_PASSWORD", ""),
        DB_PATH=os.getenv("DB_PATH", "data/bot.db"),
        BOT_COOKIE_FILE=os.getenv("BOT_COOKIE_FILE", f"cookies/{username}.cookies.json"),
        BOT_LOCK_FILE=os.getenv("BOT_LOCK_FILE", f"{username}.lock"),
        WORKER_SLEEP_SECONDS=int(os.getenv("WORKER_SLEEP_SECONDS", "3")),
        MAX_RETRY_COUNT=int(os.getenv("MAX_RETRY_COUNT", "3")),
        SCANNER_FORUM_IDS=_parse_int_list(os.getenv("SCANNER_FORUM_IDS", "40")),
        SCANNER_INTERVAL_SECONDS=int(os.getenv("SCANNER_INTERVAL_SECONDS", "120")),
        SCANNER_PAGE_LIMIT=int(os.getenv("SCANNER_PAGE_LIMIT", "3")),
        QUOTE_CHECK_INTERVAL_SECONDS=int(os.getenv("QUOTE_CHECK_INTERVAL_SECONDS", "60")),
        LLM_BASE_URL=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        LLM_API_KEY=os.getenv("LLM_API_KEY", ""),
        LLM_MODEL=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        LLM_SYSTEM_PROMPT=os.getenv("LLM_SYSTEM_PROMPT", "你是一个技术论坛用户，回复简短自然，2-4句话，引发讨论。"),
    )


def _parse_int_list(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


settings = _load_settings()
