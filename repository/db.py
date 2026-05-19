"""
repository/db.py

Database access layer — all SQLite read/write operations go through here.

Database: tenders.db  (SQLite, single file, sits at the project root)

Tables
──────
  tenders              — one row per tender (unique on tender_id).
                         Schema defined in models/tender.py::SCHEMA.
                         Upserted via INSERT OR REPLACE so re-scraping a
                         tender overwrites the old row rather than duplicating.

  scraping_health_log  — one row per scraping run, recording source, domain,
                         status ('ok' / 'failed' / 'blocked'), error details,
                         and records_fetched count.  Used by the dashboard to
                         show last-scraped timestamps and failure indicators.

Key functions (module-level wrappers around TenderRepository)
─────────────────────────────────────────────────────────────
  get_db()        → sqlite3.Connection  (schema auto-migrated on every open)
  upsert(conn, records)  → int  (records inserted/replaced)
  log_health(conn, ...)  → None (one log row per scraping session)

Schema migration
────────────────
  When new columns are added to models/tender.py::_MIGRATION_COLUMNS, they are
  added with ALTER TABLE on every DB open.  This is idempotent — SQLite raises
  OperationalError if the column already exists, which we silently swallow.
  This means no migration scripts are needed for additive schema changes.
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path

from models.tender import SCHEMA, _MIGRATION_COLUMNS, TENDER_FIELDS

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH  = BASE_DIR / "tenders.db"


class TenderRepository:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        """Open a connection and ensure schema is current."""
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SCHEMA)
        # Idempotent migration for existing DBs created before v4.0
        for col, sql_type in _MIGRATION_COLUMNS:
            try:
                conn.execute(f"ALTER TABLE tenders ADD COLUMN {col} {sql_type}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.row_factory = sqlite3.Row
        return conn

    def upsert(self, conn: sqlite3.Connection, records: list) -> int:
        """Insert or replace tender records. Returns count inserted."""
        if not records:
            return 0
        conn.executemany(
            """INSERT OR REPLACE INTO tenders
               (tender_id, title, sector, department, state, district, block,
                allocated_amount, latitude, longitude, status, source, source_url,
                contractor_name, start_date, end_date, scraped_at)
               VALUES
               (:tender_id, :title, :sector, :department, :state, :district, :block,
                :allocated_amount, :latitude, :longitude, :status, :source, :source_url,
                :contractor_name, :start_date, :end_date, :scraped_at)
            """,
            records,
        )
        conn.commit()
        return len(records)

    def log_health(
        self,
        conn: sqlite3.Connection,
        source: str,
        domain: str,
        status: str,
        error_code: str = "",
        error_msg: str = "",
        records_fetched: int = 0,
    ):
        """Record one scraping attempt to scraping_health_log."""
        conn.execute(
            """INSERT INTO scraping_health_log
               (source, domain, status, error_code, error_msg, records_fetched, logged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (source, domain, status, error_code, (error_msg or "")[:500], records_fetched,
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()


# Module-level convenience functions for backward compatibility
_repo = TenderRepository()


def get_db() -> sqlite3.Connection:
    return _repo.connect()


def upsert(conn: sqlite3.Connection, records: list) -> int:
    return _repo.upsert(conn, records)


def log_health(conn: sqlite3.Connection, source: str, domain: str, status: str,
               error_code: str = "", error_msg: str = "", records_fetched: int = 0):
    return _repo.log_health(conn, source, domain, status,
                            error_code=error_code, error_msg=error_msg,
                            records_fetched=records_fetched)
