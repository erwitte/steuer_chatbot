from datetime import date
from pathlib import Path

import psycopg

from steuer_chatbot.entries import Entry, create_entry, delete_entry


def entry_ids(conn: psycopg.Connection) -> list[int]:
    return [row[0] for row in conn.execute("SELECT id FROM entries ORDER BY id").fetchall()]


def create_arbeitsmittel_entry(
    conn: psycopg.Connection, receipts_dir: Path, download_dir: Path, name: str = "beleg.jpg"
) -> Entry:
    photo = download_dir / name
    photo.write_bytes(b"jpeg-bytes")
    return create_entry(
        conn,
        receipts_dir,
        category="arbeitsmittel",
        entry_date=date(2025, 3, 14),
        cost_cents=4999,
        receipt_source_path=photo,
    )


def test_deleting_an_entry_removes_its_row_and_receipt_file(
    conn: psycopg.Connection, receipts_dir: Path, download_dir: Path
) -> None:
    entry = create_arbeitsmittel_entry(conn, receipts_dir, download_dir)
    assert entry.receipt_path is not None
    receipt_file = receipts_dir / entry.receipt_path

    assert delete_entry(conn, receipts_dir, entry.id) is True

    assert entry_ids(conn) == []
    assert not receipt_file.exists()


def test_deleting_an_entry_without_receipt_leaves_other_receipts_alone(
    conn: psycopg.Connection, receipts_dir: Path, download_dir: Path
) -> None:
    other = create_arbeitsmittel_entry(conn, receipts_dir, download_dir)
    assert other.receipt_path is not None
    homeoffice = create_entry(
        conn,
        receipts_dir,
        category="homeoffice_pauschale",
        entry_date=date(2025, 1, 2),
        cost_cents=None,
        receipt_source_path=None,
    )

    assert delete_entry(conn, receipts_dir, homeoffice.id) is True

    assert entry_ids(conn) == [other.id]
    assert (receipts_dir / other.receipt_path).read_bytes() == b"jpeg-bytes"


def test_deleting_a_nonexistent_entry_changes_nothing(
    conn: psycopg.Connection, receipts_dir: Path, download_dir: Path
) -> None:
    existing = create_arbeitsmittel_entry(conn, receipts_dir, download_dir)
    assert existing.receipt_path is not None

    assert delete_entry(conn, receipts_dir, existing.id + 1) is False

    assert entry_ids(conn) == [existing.id]
    assert (receipts_dir / existing.receipt_path).read_bytes() == b"jpeg-bytes"


def test_entry_is_deleted_even_if_its_receipt_file_cannot_be_removed(
    conn: psycopg.Connection, receipts_dir: Path, download_dir: Path
) -> None:
    entry = create_arbeitsmittel_entry(conn, receipts_dir, download_dir)
    assert entry.receipt_path is not None
    receipt_file = receipts_dir / entry.receipt_path
    receipt_file.unlink()
    receipt_file.mkdir()  # something unremovable where the Receipt file was

    assert delete_entry(conn, receipts_dir, entry.id) is True

    assert entry_ids(conn) == []
