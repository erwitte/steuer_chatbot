"""Parsing of the free-text answers the user types during the guided flow."""

import re
from datetime import date, datetime

_COST = re.compile(r"(\d+)(?:[.,](\d{1,2}))?")
_COMMUTE_DISTANCE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:km)?", re.IGNORECASE)
_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y")


def parse_cost_cents(text: str) -> int:
    """Parse a euro amount like "49,99", "49.99" or "49 €" into integer cents."""
    match = _COST.fullmatch(text.replace("€", "").strip())
    if match is None:
        raise ValueError(f"Not a valid cost: {text!r}")
    euros, cents = match.groups()
    total = int(euros) * 100 + int((cents or "0").ljust(2, "0"))
    if total <= 0:
        raise ValueError(f"Cost must be positive: {text!r}")
    return total


def parse_entry_date(text: str) -> date:
    """Parse a date given as YYYY-MM-DD or DD.MM.YYYY."""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Not a valid date: {text!r}")


def parse_commute_distance_km(text: str) -> float:
    """Parse a distance like "42", "42,5" or "42 km" into km."""
    match = _COMMUTE_DISTANCE.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"Not a valid distance: {text!r}")
    km = float(match.group(1).replace(",", "."))
    if km <= 0:
        raise ValueError(f"Distance must be positive: {text!r}")
    return km
