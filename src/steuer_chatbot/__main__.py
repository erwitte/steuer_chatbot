import logging
import shutil
import time

import psycopg
from telegram import Update

from steuer_chatbot.bot import INCOMING_DIRNAME, build_application
from steuer_chatbot.config import Config
from steuer_chatbot.db import migrate

log = logging.getLogger("steuer_chatbot")


def _migrate_when_ready(database_url: str, attempts: int = 30) -> None:
    for attempt in range(1, attempts + 1):
        try:
            with psycopg.connect(database_url) as conn:
                migrate(conn)
            return
        except psycopg.OperationalError:
            if attempt == attempts:
                raise
            log.info("Database not ready yet, retrying (%d/%d)", attempt, attempts)
            time.sleep(2)


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    # httpx logs request URLs at INFO, and those contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = Config.from_env()
    config.receipts_dir.mkdir(parents=True, exist_ok=True)
    # Receipts staged by flows that never finished before the last shutdown are abandoned.
    shutil.rmtree(config.receipts_dir / INCOMING_DIRNAME, ignore_errors=True)
    _migrate_when_ready(config.database_url)

    build_application(config).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
