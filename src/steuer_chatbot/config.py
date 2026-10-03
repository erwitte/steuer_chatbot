import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    allowed_telegram_user_id: int
    database_url: str
    receipts_dir: Path

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
            allowed_telegram_user_id=int(_require("ALLOWED_TELEGRAM_USER_ID")),
            database_url=_require("DATABASE_URL"),
            receipts_dir=Path(_require("RECEIPTS_DIR")),
        )


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} must be set")
    return value
