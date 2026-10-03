"""Service layer for user settings such as the Commute Distance. No Telegram types in here."""

import math

import psycopg

COMMUTE_DISTANCE_KEY = "commute_distance_km"


def get_commute_distance(conn: psycopg.Connection) -> float | None:
    """The round-trip Commute Distance in km, or None if it was never set."""
    row = conn.execute("SELECT value FROM settings WHERE key = %s", (COMMUTE_DISTANCE_KEY,)).fetchone()
    return None if row is None else float(row[0])


def set_commute_distance(conn: psycopg.Connection, km: float) -> None:
    """Store the round-trip Commute Distance, overwriting any previous value."""
    if not (math.isfinite(km) and km > 0):
        raise ValueError(f"Commute Distance must be a positive number of km, got {km!r}")
    with conn.transaction():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s)"
            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (COMMUTE_DISTANCE_KEY, str(km)),
        )
