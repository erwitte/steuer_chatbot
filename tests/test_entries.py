from datetime import date
from pathlib import Path

import psycopg
import pytest

from steuer_chatbot.entries import create_entry


def fetch_row(conn: psycopg.Connection, entry_id: int) -> tuple[object, ...] | None:
    return conn.execute(
        "SELECT category, entry_date, tax_year, cost_cents, receipt_path"
        " FROM entries WHERE id = %s",
        (entry_id,),
    ).fetchone()


def test_arbeitsmittel_entry_with_photo_receipt_is_persisted(
    conn: psycopg.Connection, receipts_dir: Path, download_dir: Path
) -> None:
    photo = download_dir / "file_42.jpg"
    photo.write_bytes(b"jpeg-bytes")

    entry = create_entry(
        conn,
        receipts_dir,
        category="arbeitsmittel",
        entry_date=date(2025, 3, 14),
        cost_cents=4999,
        receipt_source_path=photo,
    )

    assert fetch_row(conn, entry.id) == (
        "arbeitsmittel",
        date(2025, 3, 14),
        2025,
        4999,
        f"arbeitsmittel/{entry.id}.jpg",
    )
    assert (receipts_dir / f"arbeitsmittel/{entry.id}.jpg").read_bytes() == b"jpeg-bytes"
    assert not photo.exists()


def test_no_entry_is_persisted_when_the_receipt_cannot_be_stored(
    conn: psycopg.Connection, receipts_dir: Path, download_dir: Path
) -> None:
    missing = download_dir / "vanished.pdf"

    with pytest.raises(FileNotFoundError):
        create_entry(
            conn,
            receipts_dir,
            category="arbeitsmittel",
            entry_date=date(2025, 3, 14),
            cost_cents=4999,
            receipt_source_path=missing,
        )

    assert conn.execute("SELECT count(*) FROM entries").fetchone() == (0,)


def test_arbeitsmittel_entry_requires_a_receipt(
    conn: psycopg.Connection, receipts_dir: Path
) -> None:
    with pytest.raises(ValueError, match="Receipt"):
        create_entry(
            conn,
            receipts_dir,
            category="arbeitsmittel",
            entry_date=date(2025, 3, 14),
            cost_cents=4999,
            receipt_source_path=None,
        )

    assert conn.execute("SELECT count(*) FROM entries").fetchone() == (0,)


def test_arbeitsmittel_entry_requires_a_cost(
    conn: psycopg.Connection, receipts_dir: Path, download_dir: Path
) -> None:
    photo = download_dir / "file_42.jpg"
    photo.write_bytes(b"jpeg-bytes")

    with pytest.raises(ValueError, match="cost"):
        create_entry(
            conn,
            receipts_dir,
            category="arbeitsmittel",
            entry_date=date(2025, 3, 14),
            cost_cents=None,
            receipt_source_path=photo,
        )

    assert conn.execute("SELECT count(*) FROM entries").fetchone() == (0,)
    assert photo.exists()


def test_unknown_category_is_rejected(
    conn: psycopg.Connection, receipts_dir: Path
) -> None:
    with pytest.raises(ValueError, match="Category"):
        create_entry(
            conn,
            receipts_dir,
            category="haushaltsnahe_dienstleistung",
            entry_date=date(2025, 3, 14),
            cost_cents=None,
            receipt_source_path=None,
        )
