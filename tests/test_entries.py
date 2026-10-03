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


@pytest.mark.parametrize(
    ("category", "receipt_name", "receipt_bytes", "entry_date", "tax_year", "cost_cents", "stored_as"),
    [
        ("arbeitsmittel", "file_42.jpg", b"jpeg-bytes", date(2025, 3, 14), 2025, 4999, "arbeitsmittel/{id}.jpg"),
        ("weiterbildung", "rechnung.pdf", b"%PDF-1.7", date(2024, 12, 31), 2024, 89000, "weiterbildung/{id}.pdf"),
    ],
)
def test_entry_with_receipt_is_persisted(
    conn: psycopg.Connection,
    receipts_dir: Path,
    download_dir: Path,
    category: str,
    receipt_name: str,
    receipt_bytes: bytes,
    entry_date: date,
    tax_year: int,
    cost_cents: int,
    stored_as: str,
) -> None:
    receipt = download_dir / receipt_name
    receipt.write_bytes(receipt_bytes)

    entry = create_entry(
        conn,
        receipts_dir,
        category=category,
        entry_date=entry_date,
        cost_cents=cost_cents,
        receipt_source_path=receipt,
    )

    receipt_path = stored_as.format(id=entry.id)
    assert fetch_row(conn, entry.id) == (category, entry_date, tax_year, cost_cents, receipt_path)
    assert (receipts_dir / receipt_path).read_bytes() == receipt_bytes
    assert not receipt.exists()


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
