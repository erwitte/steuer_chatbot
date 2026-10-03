"""Service layer for Entries. No Telegram types in here."""

import shutil
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

import psycopg

from steuer_chatbot.settings import get_commute_distance


class Category(StrEnum):
    HOMEOFFICE_PAUSCHALE = "homeoffice_pauschale"
    PENDLERPAUSCHALE = "pendlerpauschale"
    WEITERBILDUNG = "weiterbildung"
    ARBEITSMITTEL = "arbeitsmittel"

    @property
    def has_cost_and_receipt(self) -> bool:
        """Flat-rate Categories have neither a cost nor a Receipt."""
        return self in (Category.WEITERBILDUNG, Category.ARBEITSMITTEL)

    @property
    def requires_commute_distance(self) -> bool:
        """Pendlerpauschale is calculated against the Commute Distance, so it must be set first."""
        return self is Category.PENDLERPAUSCHALE


@dataclass(frozen=True)
class Entry:
    id: int
    category: Category
    entry_date: date
    tax_year: int
    cost_cents: int | None
    receipt_path: str | None


def create_entry(
    conn: psycopg.Connection,
    receipts_dir: Path,
    *,
    category: Category | str,
    entry_date: date,
    cost_cents: int | None,
    receipt_source_path: Path | None,
) -> Entry:
    try:
        category = Category(category)
    except ValueError:
        raise ValueError(f"Unknown Category: {category!r}") from None
    if category.has_cost_and_receipt:
        if cost_cents is None:
            raise ValueError(f"A {category} Entry requires a cost")
        if receipt_source_path is None:
            raise ValueError(f"A {category} Entry requires a Receipt")
    else:
        if cost_cents is not None:
            raise ValueError(f"A {category} Entry has no cost")
        if receipt_source_path is not None:
            raise ValueError(f"A {category} Entry has no Receipt")

    tax_year = entry_date.year
    moved_receipt: Path | None = None
    try:
        with conn.transaction():
            if category.requires_commute_distance and get_commute_distance(conn) is None:
                raise ValueError(f"A {category} Entry requires the Commute Distance to be set")
            row = conn.execute(
                "INSERT INTO entries (category, entry_date, tax_year, cost_cents)"
                " VALUES (%s, %s, %s, %s) RETURNING id",
                (category, entry_date, tax_year, cost_cents),
            ).fetchone()
            assert row is not None
            entry_id: int = row[0]

            receipt_path = None
            if receipt_source_path is not None:
                receipt_relative_path = Path(category) / f"{entry_id}{receipt_source_path.suffix}"
                destination = receipts_dir / receipt_relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(receipt_source_path, destination)
                moved_receipt = destination
                receipt_path = receipt_relative_path.as_posix()
                conn.execute(
                    "UPDATE entries SET receipt_path = %s WHERE id = %s",
                    (receipt_path, entry_id),
                )
    except BaseException:
        # The row was rolled back; put the Receipt back so no orphan file is left under RECEIPTS_DIR.
        if moved_receipt is not None and receipt_source_path is not None:
            shutil.move(moved_receipt, receipt_source_path)
        raise

    return Entry(entry_id, category, entry_date, tax_year, cost_cents, receipt_path)
