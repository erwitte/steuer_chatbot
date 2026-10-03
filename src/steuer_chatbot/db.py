import psycopg

# entries.id is a SERIAL (Postgres INTEGER), so no Entry can have a larger id.
MAX_ENTRY_ID = 2**31 - 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL CHECK (category IN ('homeoffice_pauschale', 'pendlerpauschale', 'weiterbildung', 'arbeitsmittel')),
    entry_date DATE NOT NULL,
    tax_year INTEGER NOT NULL,
    cost_cents INTEGER,       -- NULL for homeoffice_pauschale / pendlerpauschale
    receipt_path TEXT,        -- NULL for homeoffice_pauschale / pendlerpauschale; relative path under RECEIPTS_DIR
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def migrate(conn: psycopg.Connection) -> None:
    """Create the schema if it doesn't exist yet. Safe to run on every startup."""
    with conn.transaction():
        conn.execute(SCHEMA)
