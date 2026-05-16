"""
scraper_v3.py — Enterprise Multi-Source Government Tender Scraper

Sources:
  1. CPPP  (eprocure.gov.in)            — Playwright (headless Chromium)
  2. GeM   (bidplus.gem.gov.in)         — Playwright (headless Chromium)
  3. 15 NIC State Portals               — Playwright (headless Chromium)
  4. data.gov.in OGD API                — REST (API key required)

Storage: SQLite  →  tenders.db

Usage:
  python3 scraper_v3.py                              # all sources
  python3 scraper_v3.py --sources cppp gem           # CPPP + GeM only
  python3 scraper_v3.py --sources states             # all state NIC portals
  python3 scraper_v3.py --sources datagov --api-key YOUR_KEY
  python3 scraper_v3.py --pages 5                    # 5 pages per portal
  python3 scraper_v3.py --headless false             # show browser (debug)

Get free data.gov.in API key: https://data.gov.in/user/register
"""

import re
import json
import time
import sqlite3
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("scraper_v3")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH  = BASE_DIR / "tenders.db"

PAGE_DELAY    = 2.0   # seconds between page turns (polite crawl)
NAV_TIMEOUT   = 30_000  # ms for Playwright navigation
ACTION_TIMEOUT = 10_000  # ms for Playwright element waits

# ─── Portal Configs ────────────────────────────────────────────────────────────

NIC_PORTALS = {
    "Central (CPPP)":  "https://eprocure.gov.in/eprocure/app",
    "Bihar":           "https://eproc.bihar.gov.in/BSWAN_NEW/app",
    "Uttar Pradesh":   "https://etender.up.nic.in/nicgep/app",
    "Maharashtra":     "https://mahatenders.gov.in/nicgep/app",
    "Karnataka":       "https://eproc.karnataka.gov.in/app",
    "Rajasthan":       "https://sppp.raj.nic.in/nicgep/app",
    "West Bengal":     "https://wbtenders.gov.in/nicgep/app",
    "Tamil Nadu":      "https://tntenders.gov.in/nicgep/app",
    "Gujarat":         "https://nprocure.com/nicgep/app",
    "Andhra Pradesh":  "https://tender.apeprocurement.gov.in/nicgep/app",
    "Telangana":       "https://tender.telangana.gov.in/nicgep/app",
    "Madhya Pradesh":  "https://mptenders.gov.in/nicgep/app",
    "Odisha":          "https://tendersodisha.gov.in/nicgep/app",
    "Punjab":          "https://eproc.punjab.gov.in/EPROC/app",
    "Haryana":         "https://etenders.hry.nic.in/nicgep/app",
    "Delhi":           "https://govtprocurement.delhi.gov.in/nicgep/app",
}

GEM_URL      = "https://bidplus.gem.gov.in/all-bids"
DATAGOV_BASE = "https://api.data.gov.in"

# data.gov.in dataset resource IDs for procurement/tender data
DATAGOV_RESOURCES = [
    # Central procurement notices (update IDs from data.gov.in as new datasets are published)
    "6176ee09-3d56-4a3b-8115-21841dde0418",  # NIC tender notices
    "9dc9c5c3-4b5e-4b5e-8b5e-4b5e8b5e4b5e",  # placeholder — search for current IDs
]

# ─── SQLite Setup ──────────────────────────────────────────────────────────────

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


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
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


def log_health(
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
        (source, domain, status, error_code, error_msg[:500], records_fetched,
         datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def upsert(conn: sqlite3.Connection, records: list[dict]) -> int:
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


# ─── Text Classifiers ──────────────────────────────────────────────────────────

_SECTOR_RULES = [
    ("Infrastructure",     ["road", "bridge", "highway", "flyover", "nhai", "pwd", "airport", "railway", "metro", "tunnel"]),
    ("Health",             ["health", "hospital", "medical", "nhm", "aiims", "phc", "chc", "ambulance", "dispensary", "vaccine"]),
    ("Education",          ["school", "college", "university", "education", "vidyalaya", "ugc", "navodaya", "library", "hostel"]),
    ("Agriculture",        ["farm", "agriculture", "crop", "irrigation", "soil", "fishery", "horticulture", "kisan", "mandi"]),
    ("MSME",               ["msme", "small industry", "khadi", "handicraft", "cottage", "nsic", "sidbi", "artisan"]),
    ("Energy",             ["solar", "power", "electricity", "energy", "ntpc", "wind", "renewable", "substation", "transformer"]),
    ("Water & Sanitation", ["water", "sanitation", "sewage", "drain", "toilet", "swachh", "jal", "borewell", "pipeline", "odf"]),
    ("Urban Development",  ["smart city", "amrut", "municipal", "pmay urban", "metro", "bus terminal", "parking", "footpath"]),
    ("Rural Development",  ["pmgsy", "mnrega", "gram", "panchayat", "pmay gramin", "rural road", "village", "drda"]),
    ("Minority Affairs",   ["minority", "waqf", "msdp", "madrasa", "haj", "urdu"]),
    ("Social Welfare",     ["welfare", "social justice", "tribal", "sc/st", "women", "child", "anganwadi", "crèche", "creche"]),
    ("Digital & IT",       ["digital", " it ", "software", "meity", "bharatnet", "csc", "data centre", "cyber", "e-governance"]),
]

def classify_sector(title: str, department: str = "") -> str:
    text = (title + " " + department).lower()
    for sector, keywords in _SECTOR_RULES:
        if any(kw in text for kw in keywords):
            return sector
    return "Other"


def parse_amount(text: str) -> float:
    """Parse Indian-format amount strings → float in Crores."""
    if not text:
        return 0.0
    raw = text.replace(",", "").replace("₹", "").replace("Rs", "").strip().lower()
    m = re.search(r"(\d+(?:\.\d+)?)", raw)
    if not m:
        return 0.0
    value = float(m.group(1))
    if "crore" in raw or "cr." in raw:
        return round(value, 4)
    if "lakh" in raw or "lac" in raw:
        return round(value / 100, 4)
    if value > 1_00_000:          # raw rupees
        return round(value / 1_00_00_000, 4)
    return round(value, 4)


def extract_state_from_org(org: str) -> str:
    """Best-effort: pull state name from organisation chain."""
    from pipeline import STATES_DATA
    for state in STATES_DATA:
        if state.lower() in org.lower():
            return state
    return "Unknown"


_DATE_RE = re.compile(r"\b(\d{1,2})[\-/](\d{1,2})[\-/](\d{2,4})\b")


def extract_date(text: str) -> Optional[str]:
    """Pull first DD/MM/YYYY or DD-MM-YYYY date → ISO 'YYYY-MM-DD'. None if absent."""
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    d, mo, y = m.groups()
    if len(y) == 2:
        y = "20" + y
    try:
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    except ValueError:
        return None


def make_record(
    tender_id: str,
    title: str,
    department: str,
    amount_str: str,
    state: str,
    source: str,
    source_url: str = "",
    contractor_name: str = "",
    start_date: str = "",
    end_date: str = "",
    status: str = "Active",
) -> dict:
    return {
        "tender_id":        tender_id.strip() or f"AUTO-{hash(title+source)}",
        "title":            title.strip(),
        "sector":           classify_sector(title, department),
        "department":       department.strip(),
        "state":            state,
        "district":         "Unknown",
        "block":            "Unknown",
        "allocated_amount": parse_amount(amount_str),
        "latitude":         None,
        "longitude":        None,
        "status":           status,
        "source":           source,
        "source_url":       source_url,
        "contractor_name":  contractor_name.strip() or None,
        "start_date":       start_date or None,
        "end_date":         end_date or None,
        "scraped_at":       datetime.now().isoformat(timespec="seconds"),
    }


# ─── Playwright: NIC Portal Scraper ───────────────────────────────────────────

def scrape_nic_portal(state_label: str, base_url: str, max_pages: int, headless: bool, conn: sqlite3.Connection = None) -> list[dict]:
    """
    Scrape a NIC eProcurement portal (CPPP or state variant).
    NIC portals all share the same HTML structure:
      page=FrontEndLatestActiveTender&service=page
    Table columns (0-indexed): Sl | Published | Closing | Opening | Title+RefNo | Organisation | Value
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    records = []
    tender_url = f"{base_url}?page=FrontEndLatestActiveTender&service=page"

    logger.info("[NIC] %s — starting (max %d pages)", state_label, max_pages)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx     = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()
        page.set_default_timeout(NAV_TIMEOUT)

        try:
            page.goto(tender_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            page.wait_for_timeout(2000)   # let JS settle

            for pg_num in range(1, max_pages + 1):
                # Locate the tender table — NIC uses class "list_table" or "table_list"
                try:
                    page.wait_for_selector("table", timeout=ACTION_TIMEOUT)
                except PWTimeout:
                    logger.warning("[NIC] %s page %d — no table found, stopping", state_label, pg_num)
                    break

                rows = page.query_selector_all("table tr")
                page_count = 0

                for row in rows[1:]:   # skip header
                    cells = row.query_selector_all("td")
                    if len(cells) < 5:
                        continue

                    # Column positions vary slightly across NIC portals — use flexible extraction
                    texts = [c.inner_text().strip() for c in cells]

                    # Find title cell (longest text usually)
                    title_text = max(texts, key=len)
                    # Ref number — first cell that looks like NIT/ref
                    ref = next((t for t in texts if re.search(r"NIT|/\d{4}|T-\d|BID", t, re.I)), texts[0])
                    # Organisation — cell containing state/ministry keywords
                    org = next((t for t in texts if any(
                        kw in t.lower() for kw in ["ministry", "department", "division", "circle", "board"]
                    )), state_label)
                    # Amount — cell with ₹ or numeric-looking value
                    amount_raw = next((t for t in texts if re.search(r"₹|lakh|crore|\d{5,}", t, re.I)), "0")

                    st = extract_state_from_org(org) if state_label == "Central (CPPP)" else state_label

                    # Try to pull dates from the row (Published/Closing date cells)
                    date_cells = [t for t in texts if _DATE_RE.search(t)]
                    start_iso  = extract_date(date_cells[0]) if date_cells else ""
                    end_iso    = extract_date(date_cells[-1]) if len(date_cells) > 1 else ""

                    records.append(make_record(
                        tender_id       = ref[:120],
                        title           = title_text[:300],
                        department      = org[:200],
                        amount_str      = amount_raw,
                        state           = st,
                        source          = f"NIC/{state_label}",
                        source_url      = page.url,
                        contractor_name = "",   # not present in active listings
                        start_date      = start_iso,
                        end_date        = end_iso,
                    ))
                    page_count += 1

                logger.info("[NIC] %s page %d → %d tenders", state_label, pg_num, page_count)

                # Pagination: look for "Next" link
                next_btn = page.query_selector("a:has-text('Next'), a:has-text('>')")
                if not next_btn:
                    logger.info("[NIC] %s — no Next button, done at page %d", state_label, pg_num)
                    break

                try:
                    next_btn.click()
                    page.wait_for_load_state("domcontentloaded")
                    time.sleep(PAGE_DELAY)
                except PWTimeout:
                    logger.warning("[NIC] %s — Next click timeout at page %d", state_label, pg_num)
                    break

            # Health log: success
            if conn is not None:
                log_health(conn, f"NIC/{state_label}", base_url, "success",
                           records_fetched=len(records))

        except PWTimeout as e:
            logger.warning("[NIC] %s — navigation timeout (portal may be down)", state_label)
            if conn is not None:
                log_health(conn, f"NIC/{state_label}", base_url, "failed",
                           error_code="TIMEOUT", error_msg=str(e))
        except Exception as e:
            logger.warning("[NIC] %s — error: %s", state_label, e)
            if conn is not None:
                log_health(conn, f"NIC/{state_label}", base_url, "failed",
                           error_code=type(e).__name__, error_msg=str(e))
        finally:
            browser.close()

    logger.info("[NIC] %s — total scraped: %d", state_label, len(records))
    return records


# ─── Playwright: GeM Bidplus Scraper ──────────────────────────────────────────

def scrape_gem(max_pages: int, headless: bool, conn: sqlite3.Connection = None) -> list[dict]:
    """
    Scrape Government e-Marketplace bid listings.
    URL: https://bidplus.gem.gov.in/all-bids
    GeM bid cards contain: Bid No, Items, Ministry, Department, Estimated Value, Dates.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    records = []
    logger.info("[GEM] Starting (max %d pages)", max_pages)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.set_default_timeout(NAV_TIMEOUT)

        try:
            page.goto(GEM_URL, wait_until="networkidle", timeout=NAV_TIMEOUT)
            page.wait_for_timeout(3000)

            for pg_num in range(1, max_pages + 1):
                # GeM renders bid cards — each card is a div.bid-list-card or similar
                try:
                    page.wait_for_selector("[class*='bid'], [class*='card'], table", timeout=ACTION_TIMEOUT)
                except PWTimeout:
                    logger.warning("[GEM] page %d — no bid elements found", pg_num)
                    break

                # Try cards first
                cards = page.query_selector_all("[class*='bid-list'], [class*='bidCard'], .card")
                if cards:
                    for card in cards:
                        text = card.inner_text()
                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        if len(lines) < 3:
                            continue

                        bid_no    = next((l for l in lines if re.match(r"GEM/\d{4}/", l)), lines[0])
                        title     = next((l for l in lines if len(l) > 20), lines[1])
                        ministry  = next((l for l in lines if any(
                            kw in l.lower() for kw in ["ministry", "department", "govt"]
                        )), "Government of India")
                        amount_raw = next((l for l in lines if re.search(r"₹|lakh|crore|\d+\.\d+", l, re.I)), "0")

                        records.append(make_record(
                            tender_id  = bid_no[:120],
                            title      = title[:300],
                            department = ministry[:200],
                            amount_str = amount_raw,
                            state      = "Central (GeM)",
                            source     = "GEM Bidplus",
                            status     = "Active",
                        ))
                else:
                    # Fallback: try table rows
                    rows = page.query_selector_all("table tr")[1:]
                    for row in rows:
                        cells = [c.inner_text().strip() for c in row.query_selector_all("td")]
                        if len(cells) < 3:
                            continue
                        records.append(make_record(
                            tender_id  = cells[0][:120],
                            title      = cells[1][:300] if len(cells) > 1 else "GeM Bid",
                            department = cells[2][:200] if len(cells) > 2 else "Government of India",
                            amount_str = cells[-1],
                            state      = "Central (GeM)",
                            source     = "GEM Bidplus",
                        ))

                logger.info("[GEM] page %d → %d bids so far", pg_num, len(records))

                # Pagination
                next_btn = page.query_selector("a:has-text('Next'), button:has-text('Next'), [aria-label='Next']")
                if not next_btn:
                    break
                try:
                    next_btn.click()
                    page.wait_for_load_state("networkidle")
                    time.sleep(PAGE_DELAY)
                except PWTimeout:
                    break

            if conn is not None:
                log_health(conn, "GEM Bidplus", GEM_URL, "success",
                           records_fetched=len(records))

        except PWTimeout as e:
            logger.warning("[GEM] Navigation timeout")
            if conn is not None:
                log_health(conn, "GEM Bidplus", GEM_URL, "failed",
                           error_code="TIMEOUT", error_msg=str(e))
        except Exception as e:
            logger.warning("[GEM] Error: %s", e)
            if conn is not None:
                log_health(conn, "GEM Bidplus", GEM_URL, "failed",
                           error_code=type(e).__name__, error_msg=str(e))
        finally:
            browser.close()

    logger.info("[GEM] Total scraped: %d", len(records))
    return records


# ─── data.gov.in OGD REST API ─────────────────────────────────────────────────

# Known procurement/tender dataset resource IDs on data.gov.in
# Visit https://data.gov.in and search "tender" or "procurement" for current IDs
DATAGOV_DATASETS = {
    "central_procurement": "6176ee09-3d56-4a3b-8115-21841dde0418",
    "niti_expenditure":    "c2948e4d-2c3e-4b5e-8b5e-4b5e8b5e4b5e",
}

# Column name synonyms across different OGD datasets
_OGD_TITLE_COLS   = ["tender_title", "work_name", "subject", "description", "name_of_work", "title"]
_OGD_DEPT_COLS    = ["department", "organisation", "ministry", "org_name", "dept_name"]
_OGD_AMOUNT_COLS  = ["tender_value", "estimated_value", "value", "amount", "cost", "budget"]
_OGD_STATE_COLS   = ["state", "state_name", "location"]
_OGD_ID_COLS      = ["tender_id", "nit_number", "ref_no", "bid_number", "id"]
_OGD_STATUS_COLS  = ["status", "bid_status", "tender_status"]


def _pick(row: dict, candidates: list) -> str:
    for k in candidates:
        if k in row and row[k]:
            return str(row[k]).strip()
    return ""


def scrape_datagov(api_key: str, limit: int = 100, max_records: int = 10_000) -> list[dict]:
    """
    Pull procurement datasets from data.gov.in OGD API.
    api_key: free key from https://data.gov.in/user/register
    """
    records = []

    # Step 1: search catalog for tender/procurement datasets
    logger.info("[OGD] Searching data.gov.in catalog for tender datasets…")
    search_terms = ["tender", "procurement", "NIT", "public procurement"]

    found_resources = []
    for term in search_terms:
        try:
            resp = requests.get(
                f"{DATAGOV_BASE}/catalog/resources",
                params={"q": term, "api-key": api_key, "format": "json", "count": 20},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("records", []):
                rid = item.get("id") or item.get("resource_id")
                if rid and rid not in found_resources:
                    found_resources.append(rid)
                    logger.info("[OGD] Found dataset: %s — %s", rid, item.get("title", "")[:60])
        except Exception as e:
            logger.warning("[OGD] Catalog search error for '%s': %s", term, e)

    # Also try hardcoded known IDs
    found_resources = list(set(found_resources + list(DATAGOV_DATASETS.values())))
    logger.info("[OGD] Total datasets to pull: %d", len(found_resources))

    # Step 2: fetch each dataset
    for resource_id in found_resources:
        offset = 0
        dataset_count = 0

        while dataset_count < max_records:
            try:
                resp = requests.get(
                    f"{DATAGOV_BASE}/resource/{resource_id}",
                    params={
                        "api-key": api_key,
                        "format":  "json",
                        "limit":   limit,
                        "offset":  offset,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                payload = resp.json()

                rows = payload.get("records", payload.get("fields", []))
                if not rows:
                    break

                for row in rows:
                    title  = _pick(row, _OGD_TITLE_COLS)
                    dept   = _pick(row, _OGD_DEPT_COLS)
                    amount = _pick(row, _OGD_AMOUNT_COLS)
                    state  = _pick(row, _OGD_STATE_COLS) or "Unknown"
                    tid    = _pick(row, _OGD_ID_COLS) or f"OGD-{resource_id[:8]}-{offset+dataset_count}"
                    status = _pick(row, _OGD_STATUS_COLS) or "Active"

                    if not title:
                        continue

                    records.append(make_record(
                        tender_id  = tid[:120],
                        title      = title[:300],
                        department = dept[:200],
                        amount_str = amount,
                        state      = state,
                        source     = f"data.gov.in/{resource_id[:8]}",
                        status     = status,
                    ))
                    dataset_count += 1

                total_available = payload.get("total", payload.get("count", 0))
                logger.info("[OGD] %s offset=%d — fetched %d / %d", resource_id[:12], offset, dataset_count, total_available)

                if offset + limit >= int(total_available):
                    break
                offset += limit
                time.sleep(0.5)   # polite delay

            except requests.exceptions.HTTPError as e:
                if e.response.status_code in (401, 403):
                    logger.error("[OGD] Invalid API key or access denied for %s", resource_id[:12])
                else:
                    logger.warning("[OGD] HTTP %s for %s", e.response.status_code, resource_id[:12])
                break
            except Exception as e:
                logger.warning("[OGD] Error for %s: %s", resource_id[:12], e)
                break

    logger.info("[OGD] Total records fetched: %d", len(records))
    return records


# ─── Geocoding pass ────────────────────────────────────────────────────────────

def geocode_missing_db(conn: sqlite3.Connection):
    """Geocode records in DB that have NULL latitude."""
    from geocoder import geocode_location, _load_cache, _save_cache
    from geopy.geocoders import Nominatim

    rows = conn.execute(
        "SELECT tender_id, state, district FROM tenders WHERE latitude IS NULL LIMIT 500"
    ).fetchall()

    if not rows:
        logger.info("[GEO] No missing coordinates.")
        return

    logger.info("[GEO] Geocoding %d records…", len(rows))
    cache = _load_cache()
    geo   = Nominatim(user_agent="india_tender_tracker_v3")

    for row in rows:
        loc = f"{row['district']}, {row['state']}, India" if row["district"] != "Unknown" else f"{row['state']}, India"
        lat, lon = geocode_location(loc, geo, cache)
        conn.execute(
            "UPDATE tenders SET latitude=?, longitude=? WHERE tender_id=?",
            (lat, lon, row["tender_id"]),
        )

    conn.commit()
    _save_cache(cache)
    logger.info("[GEO] Geocoding complete.")


# ─── Pipeline Orchestrator ─────────────────────────────────────────────────────

def run_pipeline(
    sources: list,
    max_pages: int = 20,
    headless: bool = True,
    api_key: str = "",
    states_filter: list = None,
):
    """
    Runs selected scraping sources, saves all results to tenders.db.

    sources: list of strings — any combination of: 'cppp', 'gem', 'states', 'datagov'
    """
    conn = get_db()
    summary = {}

    # 1. CPPP (Central NIC portal)
    if "cppp" in sources:
        recs = scrape_nic_portal("Central (CPPP)", NIC_PORTALS["Central (CPPP)"], max_pages, headless, conn=conn)
        n = upsert(conn, recs)
        summary["CPPP"] = n
        logger.info("CPPP: %d records saved", n)

    # 2. State NIC portals
    if "states" in sources:
        portals = {k: v for k, v in NIC_PORTALS.items() if k != "Central (CPPP)"}
        if states_filter:
            portals = {k: v for k, v in portals.items() if k in states_filter}
        for state_label, url in portals.items():
            recs = scrape_nic_portal(state_label, url, max_pages, headless, conn=conn)
            n = upsert(conn, recs)
            summary[state_label] = n
            logger.info("%s: %d records saved", state_label, n)

    # 3. GeM Bidplus
    if "gem" in sources:
        recs = scrape_gem(max_pages, headless, conn=conn)
        n = upsert(conn, recs)
        summary["GeM"] = n
        logger.info("GeM: %d records saved", n)

    # 4. data.gov.in OGD
    if "datagov" in sources:
        if not api_key:
            logger.error("[OGD] --api-key required for data.gov.in source. Get free key: https://data.gov.in/user/register")
            log_health(conn, "data.gov.in", DATAGOV_BASE, "failed",
                       error_code="NO_API_KEY", error_msg="API key not supplied")
        else:
            try:
                recs = scrape_datagov(api_key)
                n = upsert(conn, recs)
                summary["data.gov.in"] = n
                logger.info("data.gov.in: %d records saved", n)
                log_health(conn, "data.gov.in", DATAGOV_BASE, "success", records_fetched=n)
            except Exception as e:
                log_health(conn, "data.gov.in", DATAGOV_BASE, "failed",
                           error_code=type(e).__name__, error_msg=str(e))
                logger.error("[OGD] Pipeline failed: %s", e)

    # 5. Geocode any missing coordinates
    geocode_missing_db(conn)

    total = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    conn.close()

    return summary, total


# ─── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="India Government Tender Scraper v3")
    parser.add_argument(
        "--sources", nargs="+",
        default=["cppp", "gem", "states", "datagov"],
        choices=["cppp", "gem", "states", "datagov"],
        help="Which sources to scrape",
    )
    parser.add_argument("--pages",    type=int, default=20,  help="Max pages per portal")
    parser.add_argument("--headless", type=str, default="true", choices=["true", "false"],
                        help="Run browser headless (true) or visible (false)")
    parser.add_argument("--api-key",  type=str, default="",
                        help="data.gov.in API key (required for --sources datagov)")
    parser.add_argument("--states",   nargs="+", default=None,
                        help="Limit state portals (e.g. --states Bihar 'Uttar Pradesh')")
    args = parser.parse_args()

    headless = args.headless.lower() == "true"

    print(f"\n{'─'*60}")
    print(f"  India Tender Scraper v3.0")
    print(f"  Sources : {args.sources}")
    print(f"  Max pages: {args.pages} per portal")
    print(f"  Headless : {headless}")
    print(f"  DB       : {DB_PATH}")
    print(f"{'─'*60}\n")

    summary, total = run_pipeline(
        sources       = args.sources,
        max_pages     = args.pages,
        headless      = headless,
        api_key       = args.api_key,
        states_filter = args.states,
    )

    print(f"\n{'─'*60}")
    print(f"  Scraping complete — {total:,} total tenders in DB")
    print(f"{'─'*60}")
    for source, count in summary.items():
        print(f"  {source:<30} {count:>6,} records")
    print()
