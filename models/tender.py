"""Tender data model and DB schema. Also provides geometry helpers."""

import math
import hashlib
from dataclasses import dataclass
from typing import Optional, Tuple

from config.geography import LINEAR_KEYWORDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenders (
    tender_id        TEXT PRIMARY KEY,
    title            TEXT,
    sector           TEXT,
    department       TEXT,
    state            TEXT,
    district         TEXT,
    block            TEXT,
    allocated_amount REAL,
    latitude         REAL,
    longitude        REAL,
    status           TEXT DEFAULT 'Active',
    source           TEXT,
    source_url       TEXT,
    contractor_name  TEXT,
    start_date       TEXT,
    end_date         TEXT,
    scraped_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_state  ON tenders(state);
CREATE INDEX IF NOT EXISTS idx_sector ON tenders(sector);
CREATE INDEX IF NOT EXISTS idx_dept   ON tenders(department);
CREATE INDEX IF NOT EXISTS idx_status ON tenders(status);

CREATE TABLE IF NOT EXISTS scraping_health_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT,
    domain          TEXT,
    status          TEXT,
    error_code      TEXT,
    error_msg       TEXT,
    records_fetched INTEGER DEFAULT 0,
    logged_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_health_source ON scraping_health_log(source);
"""

_MIGRATION_COLUMNS = [
    ("contractor_name", "TEXT"),
    ("start_date",      "TEXT"),
    ("end_date",        "TEXT"),
    ("source_url",      "TEXT"),
    ("latitude2",       "REAL"),
    ("longitude2",      "REAL"),
]

TENDER_FIELDS = [
    "tender_id", "title", "sector", "department", "state", "district",
    "block", "allocated_amount", "latitude", "longitude", "status",
    "source", "source_url", "contractor_name", "start_date", "end_date", "scraped_at"
]


@dataclass
class TenderRecord:
    tender_id: str
    title: str = ""
    sector: str = "Other"
    department: str = ""
    state: str = ""
    district: str = ""
    block: str = ""
    allocated_amount: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    status: str = "Active"
    source: str = ""
    source_url: str = ""
    contractor_name: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    scraped_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in TENDER_FIELDS}


# ── Geometry helpers (moved from pipeline.py) ─────────────────────────────────

def _stable_hash(s: str) -> int:
    """Process-stable hash (Python's built-in hash() is randomised per-run)."""
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


def is_linear_title(title: str) -> bool:
    """True if the tender title describes linear infrastructure (line on map)."""
    if not title:
        return False
    t = title.lower()
    return any(kw in t for kw in LINEAR_KEYWORDS)


def linear_endpoints(
    start_lat: float, start_lon: float, tender_id: str,
    min_km: float = 1.5, max_km: float = 8.0,
) -> Tuple[float, float]:
    """
    Deterministically derive a line endpoint from a start coord + tender_id.
    Same tender_id always produces the same endpoint across runs.
    """
    h = _stable_hash(tender_id)
    angle = (h % 360) * math.pi / 180
    length_km = min_km + ((h >> 8) & 0xFF) / 255.0 * (max_km - min_km)
    lat_off = (length_km / 111.0) * math.sin(angle)
    lon_factor = max(0.5, math.cos(math.radians(start_lat)))
    lon_off = (length_km / (111.0 * lon_factor)) * math.cos(angle)
    return round(start_lat + lat_off, 6), round(start_lon + lon_off, 6)
