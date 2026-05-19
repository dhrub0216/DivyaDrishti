"""
models/tender.py — The "shape" of a single government tender record.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT THIS FILE DOES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Think of this file as the "template" for every government tender we collect.
Every scraper — whether it pulls data from Bihar, NHAI, GeM, or Coal India —
must produce records that fit this exact shape before they can be saved.

It defines three things:
  1. SCHEMA       — the SQLite database table structure (what columns exist)
  2. TenderRecord — a Python object with typed fields (validation before saving)
  3. Geometry helpers — math functions to place tenders on the map

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIELD-BY-FIELD EXPLANATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  tender_id       — Unique ID for the tender (usually the portal's own reference
                    number, e.g. "2024_NHAI_123456"). Prevents duplicates if
                    we scrape the same portal twice.

  title           — Full name of the tender, exactly as shown on the portal.
                    e.g. "Construction of road from Samastipur to Darbhanga"

  sector          — Which government programme area this tender serves.
                    Classified by our classifier.py into 12 standard categories:
                    Infrastructure, Health, Education, Agriculture, etc.

  department      — The issuing government office, e.g. "State PWD" or
                    "National Health Mission (NHM)".

  state           — Indian state where the work is located (not where the
                    office is — so a Delhi ministry tendering road work in
                    Jharkhand should say "Jharkhand").

  district        — Administrative district within the state.
  block           — Sub-district administrative unit (most granular level).

  allocated_amount— Budget sanctioned in ₹ Crores for this tender.
                    NULL means the portal didn't publish the amount publicly.

  latitude        — GPS latitude of the work site (or district centre if
  longitude         we couldn't find the exact location).

  latitude2       — Second GPS point — only filled for LINEAR tenders like
  longitude2        road construction, pipeline, or power line projects,
                    which need a START POINT and END POINT to draw a line
                    on the map instead of a dot.

  status          — Current state of the tender:
                      'Active'    — open for bids right now
                      'Awarded'   — a contractor has been selected
                      'Completed' — work is finished

  source          — Which portal/scraper produced this record.
                    e.g. "EPSV2/Bihar", "NHAI", "GEM Bidplus"

  source_url      — The exact web page where this tender lives.
                    Lets users click through to read the original document.

  contractor_name — Name of the company that won the bid (only for Awarded).

  start_date      — When work is scheduled to begin (ISO format YYYY-MM-DD).
  end_date        — Contract completion deadline.
  scraped_at      — Timestamp when our system collected this record.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MIGRATION STRATEGY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When we add a new column (e.g. latitude2 for linear features), we put it in
_MIGRATION_COLUMNS. The database layer (repository/db.py) runs ALTER TABLE
for each migration column every time the app starts — SQLite silently ignores
the command if the column already exists, so this is safe to run repeatedly.
No manual migration scripts needed.
"""

import math
import hashlib
from dataclasses import dataclass
from typing import Optional, Tuple

from config.geography import LINEAR_KEYWORDS


# ── Database schema ────────────────────────────────────────────────────────────
# This SQL is run every time we open the database.
# CREATE TABLE IF NOT EXISTS means it's safe to run on an existing DB.
# The indexes on state/sector/department speed up the dashboard filter queries.

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

# Columns added AFTER the initial schema — run as ALTER TABLE on every DB open.
# SQLite raises OperationalError if the column already exists; we swallow it.
_MIGRATION_COLUMNS = [
    ("contractor_name", "TEXT"),   # added when we started tracking awarded contracts
    ("start_date",      "TEXT"),   # work start date
    ("end_date",        "TEXT"),   # contract deadline
    ("source_url",      "TEXT"),   # direct link back to the original portal page
    ("latitude2",       "REAL"),   # endpoint for linear (road/pipe/line) tenders
    ("longitude2",      "REAL"),
]

# Canonical field order used by upsert() — must match the INSERT statement in db.py
TENDER_FIELDS = [
    "tender_id", "title", "sector", "department", "state", "district",
    "block", "allocated_amount", "latitude", "longitude", "status",
    "source", "source_url", "contractor_name", "start_date", "end_date", "scraped_at"
]


# ── Data class ─────────────────────────────────────────────────────────────────
# TenderRecord acts as a typed "form" — scrapers fill in as many fields as the
# portal provides. Fields left as None/empty are OK; the dashboard handles them.

@dataclass
class TenderRecord:
    """One normalised government tender, ready to be saved to the database."""
    tender_id:        str
    title:            str            = ""
    sector:           str            = "Other"
    department:       str            = ""
    state:            str            = ""
    district:         str            = ""
    block:            str            = ""
    allocated_amount: Optional[float] = None   # ₹ Crores; None if not published
    latitude:         Optional[float] = None   # work site GPS
    longitude:        Optional[float] = None
    status:           str            = "Active"
    source:           str            = ""      # scraper key e.g. "EPSV2/Bihar"
    source_url:       str            = ""      # direct portal URL
    contractor_name:  str            = ""      # only populated when Awarded
    start_date:       Optional[str]  = None    # ISO date YYYY-MM-DD
    end_date:         Optional[str]  = None
    scraped_at:       Optional[str]  = None    # ISO datetime, auto-set by scraper

    def to_dict(self) -> dict:
        """Convert to plain dict keyed by TENDER_FIELDS (for bulk upsert)."""
        return {k: getattr(self, k) for k in TENDER_FIELDS}


# ── Geometry helpers ───────────────────────────────────────────────────────────

def _stable_hash(s: str) -> int:
    """
    A hash that produces the same number every run (Python's built-in hash()
    changes value on every process restart due to hash randomisation).
    Used to deterministically jitter coordinates so the same tender always
    appears at the same spot on the map.
    """
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


def is_linear_title(title: str) -> bool:
    """
    Returns True if the tender title describes linear infrastructure —
    something drawn as a LINE on the map rather than a dot.

    Examples: "Construction of road from A to B",
              "Laying of water pipeline at district X",
              "Overhead power transmission line"

    The keyword list (LINEAR_KEYWORDS) lives in config/geography.py.
    """
    if not title:
        return False
    t = title.lower()
    return any(kw in t for kw in LINEAR_KEYWORDS)


def linear_endpoints(
    start_lat: float,
    start_lon: float,
    tender_id: str,
    min_km: float = 1.5,
    max_km: float = 8.0,
) -> Tuple[float, float]:
    """
    Compute a second GPS point (the far end of a road/pipeline/power line)
    from the start point and the tender_id.

    Why deterministic? So the line stays the same every time the dashboard
    loads — we don't want it "jumping" to a new position on each refresh.

    The direction and length are derived from the tender_id hash:
      - Direction  = hash mod 360 degrees
      - Length     = 1.5–8.0 km (varies with the hash, capped to be realistic)

    Returns (end_lat, end_lon).
    """
    h = _stable_hash(tender_id)
    angle = (h % 360) * math.pi / 180
    length_km = min_km + ((h >> 8) & 0xFF) / 255.0 * (max_km - min_km)

    # 1 degree latitude ≈ 111 km everywhere on Earth
    lat_off = (length_km / 111.0) * math.sin(angle)

    # 1 degree longitude ≈ 111 × cos(latitude) km — shrinks as you go north
    lon_factor = max(0.5, math.cos(math.radians(start_lat)))
    lon_off = (length_km / (111.0 * lon_factor)) * math.cos(angle)

    return round(start_lat + lat_off, 6), round(start_lon + lon_off, 6)
