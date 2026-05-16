"""
Module: scraper.py
Scrapes government tender data for Samastipur / Bihar from two sources:
  1. Bihar State e-Procurement Portal  (https://eproc.bihar.gov.in)
  2. Central Public Procurement Portal (https://eprocure.gov.in)  ← publicly accessible fallback

Run standalone:
    python scraper.py              # scrape + geocode → tenders.json
    python scraper.py --mock       # skip network, load mock data only
    python scraper.py --no-geo     # scrape only, skip geocoding step
"""

import re
import csv
import json
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

OUTPUT_FILE = Path(__file__).parent / "tenders.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.7",
}

REQUEST_TIMEOUT = 20        # seconds per HTTP request
PAGE_DELAY      = 1.5       # polite crawl delay between pages (seconds)
MAX_PAGES       = 5         # safety cap — increase for deeper crawl

# Keywords used to filter tenders relevant to Samastipur
SAMASTIPUR_KEYWORDS = [
    "samastipur", "samast", "patori", "rosera", "dalsinghsarai",
    "warisnagar", "kalyanpur", "tajpur", "bibhutipur", "singhia",
    "morwa", "ujiyarpur", "hasanpur",
]

# Recognised infrastructure categories
CATEGORY_MAP = {
    "road":    "Road",
    "bridge":  "Bridge",
    "pul":     "Bridge",   # Hindi "pul" = bridge
    "water":   "Water",
    "jal":     "Water",
    "phed":    "Water",
    "build":   "Building",
    "school":  "Building",
    "hospital":"Building",
    "chc":     "Building",
    "phc":     "Building",
}


# ── Helper utilities ────────────────────────────────────────────────────────

def _get(session: requests.Session, url: str, params: dict = None) -> Optional[BeautifulSoup]:
    """GET with retries; returns BeautifulSoup or None on failure."""
    for attempt in range(1, 4):
        try:
            resp = session.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except requests.exceptions.HTTPError as e:
            logger.warning("HTTP %s for %s (attempt %d)", e.response.status_code, url, attempt)
            if e.response.status_code in (403, 429):
                time.sleep(5 * attempt)
        except requests.exceptions.RequestException as e:
            logger.warning("Request error for %s (attempt %d): %s", url, attempt, e)
            time.sleep(3 * attempt)
    return None


def _infer_category(text: str) -> str:
    """Guess infrastructure category from tender title/description text."""
    text_lower = text.lower()
    for keyword, category in CATEGORY_MAP.items():
        if keyword in text_lower:
            return category
    return "Other"


def _parse_amount(text: str) -> float:
    """
    Extract a numeric amount from strings like:
      '₹ 2,45,000', '24.5 lakh', '2.45 crore', '24500000'
    Returns value in Crores (float); 0.0 if unparseable.
    """
    if not text:
        return 0.0
    text = text.replace(",", "").replace("₹", "").strip().lower()

    # Match a leading float/int
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return 0.0

    value = float(match.group(1))

    if "crore" in text or "cr" in text:
        return round(value, 4)
    if "lakh" in text or "lac" in text:
        return round(value / 100, 4)
    # Assume raw rupees if value > 10_000 (threshold heuristic)
    if value > 10_000:
        return round(value / 1_00_00_000, 4)   # paise → Crores
    return round(value, 4)


def _is_samastipur_related(title: str, location: str = "") -> bool:
    combined = (title + " " + location).lower()
    return any(kw in combined for kw in SAMASTIPUR_KEYWORDS)


def _build_record(
    tender_id: str,
    title: str,
    category: str,
    allocated_amount: float,
    location_raw: str,
    status: str,
    department: str,
    source: str,
) -> dict:
    return {
        "tender_id":        tender_id.strip() or "N/A",
        "title":            title.strip(),
        "category":         category,
        "allocated_amount": allocated_amount,
        "location_raw":     location_raw.strip() or "Samastipur, Bihar",
        "status":           status,
        "department":       department.strip() or "Government of Bihar",
        "source":           source,
        "scraped_at":       datetime.now().isoformat(timespec="seconds"),
        "latitude":         None,
        "longitude":        None,
    }


# ── Source 1: Bihar e-Procurement Portal ───────────────────────────────────

BIHAR_BASE = "https://eproc.bihar.gov.in"

# The portal lists active NITs at this path (adjust if the portal restructures)
BIHAR_NIT_PATH = "/BSWAN_NEW/app?page=FrontEndAdvanceSearchTender&service=page"


def scrape_bihar_portal(session: requests.Session) -> list[dict]:
    """
    Scrapes NIT listings from the Bihar State e-Procurement Portal.
    Returns a list of tender dicts (may be empty if site is unreachable).

    Portal table columns (observed structure):
      NIT No. | Work Description | Dept | Value of Work | Last Date | Status
    """
    records = []
    logger.info("Attempting Bihar portal: %s", BIHAR_BASE)

    for page_num in range(1, MAX_PAGES + 1):
        params = {
            "page":    "FrontEndAdvanceSearchTender",
            "service": "page",
            "state":   "Bihar",
            "pageNum": page_num,
        }
        soup = _get(session, BIHAR_BASE + BIHAR_NIT_PATH, params=params)
        if soup is None:
            logger.warning("Bihar portal unreachable at page %d — stopping", page_num)
            break

        # The portal renders tenders in a <table> with class 'list_table' or similar
        table = (
            soup.find("table", {"class": re.compile(r"list|tender|nit", re.I)})
            or soup.find("table")
        )
        if not table:
            logger.warning("No table found on Bihar portal page %d", page_num)
            break

        rows = table.find_all("tr")[1:]   # skip header row
        if not rows:
            break

        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 4:
                continue

            # Best-effort column mapping (portal may vary)
            nit_no   = cells[0] if len(cells) > 0 else ""
            work_desc= cells[1] if len(cells) > 1 else ""
            dept     = cells[2] if len(cells) > 2 else ""
            amount   = cells[3] if len(cells) > 3 else "0"
            status   = cells[5] if len(cells) > 5 else "Active"

            if not _is_samastipur_related(work_desc):
                continue

            records.append(_build_record(
                tender_id        = nit_no,
                title            = work_desc,
                category         = _infer_category(work_desc),
                allocated_amount = _parse_amount(amount),
                location_raw     = _extract_location_from_title(work_desc),
                status           = _normalise_status(status),
                department       = dept,
                source           = "Bihar e-Procurement Portal",
            ))

        logger.info("Bihar portal page %d: found %d Samastipur tenders so far", page_num, len(records))
        time.sleep(PAGE_DELAY)

    return records


# ── Source 2: Central Public Procurement Portal (CPPP) ─────────────────────

CPPP_SEARCH = "https://eprocure.gov.in/eprocure/app"


def scrape_cppp(session: requests.Session) -> list[dict]:
    """
    Scrapes Bihar/Samastipur tenders from the Central Public Procurement Portal.
    CPPP is publicly accessible without login for active NIT listings.

    Endpoint: /eprocure/app?page=FrontEndAdvanceSearchTender&service=page
    Filter params: stateName=Bihar, keyword=samastipur
    """
    records = []
    logger.info("Attempting CPPP: %s", CPPP_SEARCH)

    for page_num in range(1, MAX_PAGES + 1):
        params = {
            "page":      "FrontEndAdvanceSearchTender",
            "service":   "page",
            "stateName": "Bihar",
            "keyword":   "samastipur",
            "pageNum":   page_num,
        }
        soup = _get(session, CPPP_SEARCH, params=params)
        if soup is None:
            logger.warning("CPPP unreachable at page %d", page_num)
            break

        # CPPP renders a <table id="table"> with standard columns
        table = (
            soup.find("table", {"id": "table"})
            or soup.find("table", {"class": re.compile(r"list|tender", re.I)})
            or soup.find("table")
        )
        if not table:
            logger.info("CPPP page %d: no table found — possibly last page", page_num)
            break

        rows = table.find_all("tr")[1:]
        if not rows:
            break

        for row in rows:
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if len(cells) < 4:
                continue

            # CPPP typical columns:
            # 0: Sr | 1: NIT/Ref No | 2: Name of Work | 3: Organization | 4: Bid Submission Date | 5: Amount
            nit_no    = cells[1] if len(cells) > 1 else ""
            work_desc = cells[2] if len(cells) > 2 else ""
            org       = cells[3] if len(cells) > 3 else ""
            amount    = cells[5] if len(cells) > 5 else "0"

            if not work_desc:
                continue

            records.append(_build_record(
                tender_id        = nit_no,
                title            = work_desc,
                category         = _infer_category(work_desc),
                allocated_amount = _parse_amount(amount),
                location_raw     = _extract_location_from_title(work_desc),
                status           = "Active",
                department       = org,
                source           = "CPPP (eprocure.gov.in)",
            ))

        logger.info("CPPP page %d: %d records collected", page_num, len(records))
        time.sleep(PAGE_DELAY)

    return records


# ── Location extraction ─────────────────────────────────────────────────────

# Recognisable Samastipur block/town names for location extraction
KNOWN_LOCATIONS = [
    "Kalyanpur", "Rosera", "Patori", "Dalsinghsarai", "Warisnagar",
    "Singhia", "Morwa", "Bibhutipur", "Tajpur", "Ujiyarpur",
    "Hasanpur", "Shivajinagar", "Mohanpur", "Vidyapatinagar",
    "Samastipur",
]

_LOC_RE = re.compile(
    r"\b(" + "|".join(re.escape(loc) for loc in KNOWN_LOCATIONS) + r")\b",
    re.IGNORECASE,
)


def _extract_location_from_title(title: str) -> str:
    """Pull the first recognisable location name from a tender title."""
    match = _LOC_RE.search(title)
    if match:
        return f"{match.group(1)}, Samastipur, Bihar"
    return "Samastipur, Bihar"


def _normalise_status(raw: str) -> str:
    raw_lower = raw.lower()
    if any(w in raw_lower for w in ("active", "open", "live", "invited")):
        return "Active"
    if any(w in raw_lower for w in ("award", "allot", "accept")):
        return "Awarded"
    if any(w in raw_lower for w in ("complet", "finish", "close", "cancel")):
        return "Completed"
    return "Active"


# ── Mock data fallback ──────────────────────────────────────────────────────

def load_mock_data() -> list[dict]:
    """
    Returns mock tender records (same dataset as app.py) as dicts with
    latitude/longitude already populated — used when portals are unreachable.
    """
    from app import load_mock_tender_data
    df = load_mock_tender_data()
    return df.to_dict(orient="records")


# ── Pipeline orchestrator ───────────────────────────────────────────────────

def run_pipeline(use_mock: bool = False, skip_geo: bool = False) -> list[dict]:
    """
    Full pipeline:
      1. Scrape Bihar portal → CPPP → fallback to mock
      2. Deduplicate by tender_id
      3. Geocode missing coordinates
      4. Save to tenders.json

    Returns the final list of tender dicts.
    """
    records: list[dict] = []

    if use_mock:
        logger.info("--mock flag set: loading mock data, skipping network")
        records = load_mock_data()
    else:
        with requests.Session() as session:
            session.headers.update(HEADERS)

            # Try Bihar portal first
            bihar_records = scrape_bihar_portal(session)
            records.extend(bihar_records)
            logger.info("Bihar portal: %d records", len(bihar_records))

            # Supplement with CPPP
            cppp_records = scrape_cppp(session)
            records.extend(cppp_records)
            logger.info("CPPP: %d records", len(cppp_records))

        if not records:
            logger.warning("Both portals returned 0 records — falling back to mock data")
            records = load_mock_data()

    # Deduplication on tender_id (keep first occurrence)
    seen: set[str] = set()
    unique: list[dict] = []
    for rec in records:
        tid = rec.get("tender_id", "").strip()
        key = tid if tid and tid != "N/A" else rec.get("title", "")[:80]
        if key and key not in seen:
            seen.add(key)
            unique.append(rec)
    logger.info("After dedup: %d unique tenders", len(unique))

    # Geocoding
    if not skip_geo:
        from geocoder import geocode_location, _load_cache, _save_cache
        from geopy.geocoders import Nominatim

        cache = _load_cache()
        geo   = Nominatim(user_agent="samastipur_tender_tracker_v1")

        needs_geo = [r for r in unique if r.get("latitude") is None]
        logger.info("Geocoding %d records without coordinates…", len(needs_geo))

        for rec in needs_geo:
            lat, lon = geocode_location(rec["location_raw"], geo, cache)
            rec["latitude"]  = lat
            rec["longitude"] = lon

        _save_cache(cache)

    # Persist to disk
    OUTPUT_FILE.write_text(
        json.dumps(unique, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Saved %d tenders → %s", len(unique), OUTPUT_FILE)
    return unique


# ── CLI entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Samastipur Tender Scraper Pipeline")
    parser.add_argument("--mock",   action="store_true", help="Skip network; use built-in mock data")
    parser.add_argument("--no-geo", action="store_true", help="Skip geocoding step")
    args = parser.parse_args()

    results = run_pipeline(use_mock=args.mock, skip_geo=args.no_geo)

    print(f"\n{'─'*65}")
    print(f"  Pipeline complete — {len(results)} tenders written to tenders.json")
    print(f"{'─'*65}")
    print(f"  {'Tender ID':<30} {'Category':<10} {'Amount':>9}")
    print(f"  {'─'*29} {'─'*9} {'─'*9}")
    for r in results[:10]:
        print(f"  {r['tender_id']:<30} {r['category']:<10} ₹{r['allocated_amount']:>7.2f} Cr")
    if len(results) > 10:
        print(f"  … and {len(results) - 10} more")
    print()
