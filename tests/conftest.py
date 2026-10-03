from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

from steuer_chatbot.db import migrate


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:17-alpine", driver=None) as pg:
        url: str = pg.get_connection_url()
        with psycopg.connect(url) as conn:
            migrate(conn)
        yield url


@pytest.fixture
def conn(database_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_url) as conn:
        conn.execute("TRUNCATE entries, settings RESTART IDENTITY")
        conn.commit()
        yield conn


@pytest.fixture
def receipts_dir(tmp_path: Path) -> Path:
    path = tmp_path / "receipts"
    path.mkdir()
    return path


@pytest.fixture
def download_dir(tmp_path: Path) -> Path:
    """Stand-in for wherever the Telegram download placed an incoming Receipt."""
    path = tmp_path / "download"
    path.mkdir()
    return path
