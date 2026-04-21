from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    openrouter_api_key: str
    openrouter_model: str
    db_path: str


def load_settings() -> Settings:
    telegram_bot_token = (
        os.environ.get("TELEGRAM_BOT_TOKEN", "")
        or os.environ.get("BOT_TOKEN", "")
    ).strip()
    openrouter_api_key = (
        os.environ.get("OPENROUTER_API_KEY", "")
        or os.environ.get("OPENROUTER_KEY", "")
    ).strip()
    openrouter_model = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()
    db_path = os.environ.get("DEMO_DB_PATH", "./demo-bot.sqlite3").strip()

    missing = []
    if not telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN/BOT_TOKEN")
    if not openrouter_api_key:
        missing.append("OPENROUTER_API_KEY/OPENROUTER_KEY")
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(f"Missing required environment variables: {names}")

    return Settings(
        telegram_bot_token=telegram_bot_token,
        openrouter_api_key=openrouter_api_key,
        openrouter_model=openrouter_model,
        db_path=db_path,
    )
