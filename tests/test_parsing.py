from datetime import date

import pytest

from steuer_chatbot.parsing import parse_commute_distance_km, parse_cost_cents, parse_entry_date


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("49.99", 4999),
        ("49,99", 4999),
        ("49", 4900),
        ("0,5", 50),
        (" 12,30 € ", 1230),
    ],
)
def test_cost_is_parsed_to_cents(text: str, cents: int) -> None:
    assert parse_cost_cents(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "-5", "0", "1,234", "1.234,56", "nan", "inf"])
def test_invalid_cost_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_cost_cents(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2025-03-14", date(2025, 3, 14)),
        ("14.03.2025", date(2025, 3, 14)),
        (" 2024-12-31 ", date(2024, 12, 31)),
    ],
)
def test_entry_date_is_parsed(text: str, expected: date) -> None:
    assert parse_entry_date(text) == expected


@pytest.mark.parametrize("text", ["", "gestern", "2025-02-30", "03/14/2025"])
def test_invalid_entry_date_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_entry_date(text)


@pytest.mark.parametrize(
    ("text", "km"),
    [("42", 42.0), ("42,5", 42.5), ("42.5", 42.5), (" 12 km ", 12.0), ("7KM", 7.0)],
)
def test_commute_distance_is_parsed_to_km(text: str, km: float) -> None:
    assert parse_commute_distance_km(text) == km


@pytest.mark.parametrize("text", ["", "abc", "-5", "0", "0,0", "1e3", "nan", "inf", "42 meilen"])
def test_invalid_commute_distance_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_commute_distance_km(text)
