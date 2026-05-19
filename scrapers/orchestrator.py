"""
scrapers/orchestrator.py

Pipeline orchestrator — runs all scraping sources in sequence and persists
results to the SQLite database (tenders.db).

Available source keys (pass in the `sources` list to run_pipeline):
  'cppp'        — Central NIC GePNIC portal (all central-government tenders)
  'states'      — 28 state NIC GePNIC portals
  'gem'         — Government e-Marketplace Bidplus (cross-sector, nationwide)
  'datagov'     — data.gov.in Open Government Data (requires API key)
  'pmgsy'       — PMGSY rural road tenders (CAPTCHA-solved Playwright scraper)
  'cgstate'     — Chhattisgarh CHEPS portal (Java Struts, Playwright)
  'biharv2'     — Bihar EPS v2 (JS hash-tab AJAX, Playwright)
  'up_misc'     — UP custom portals: Jal Nigam, UPEIDA, State Bridge Corp
  'up_sectors'  — UP sectoral portals: Health, MSME, Social Welfare, IT
  'up_power'    — UP power distribution: PVVNL, MVVNL
  'psu_html'    — Central PSU HTML portals: MSEDCL, Chennai Port, BHEL
  'ongc'        — ONGC Current NITs (Liferay portlet, Playwright)
  'nhai'        — NHAI tenders (Angular SPA REST API, no browser needed)
  'coal_india'  — Coal India All Tenders (DataTables, Playwright)

Geocoding runs automatically at the end of every pipeline run:
  1. District coordinate table (instant, no network)
  2. Nominatim OSM geocoder (1 req/sec, network required)
  3. State centre fallback (always available)
"""

import time
import sqlite3
import logging

from config.portals import NIC_PORTALS, GEPNIC_STATES, DATAGOV_BASE
from config.geography import DISTRICT_COORDINATES, STATE_CENTERS
from repository.db import get_db, upsert, log_health

logger = logging.getLogger(__name__)


def geocode_missing_db(conn: sqlite3.Connection):
    """
    Geocode records in DB that have NULL latitude.

    Priority:
      1. DISTRICT_COORDINATES table (instant, no network)
      2. Nominatim OSM geocoder (1 req/sec, network required)
      3. STATE_CENTERS fallback (always available)

    NOTE: Does NOT use geocoder.py — that module appends a Samastipur bias
    to every query and is only suitable for the original Samastipur project.
    """
    import json
    from pathlib import Path
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    from services.aggregator import _district_coords

    CACHE_FILE = Path(__file__).parent.parent / "geocache_v2.json"

    def _load():
        return json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    def _save(c):
        CACHE_FILE.write_text(json.dumps(c, indent=2, ensure_ascii=False))

    import sqlite3 as _sqlite3
    conn.row_factory = _sqlite3.Row
    rows = conn.execute(
        "SELECT tender_id, state, district FROM tenders WHERE latitude IS NULL LIMIT 500"
    ).fetchall()

    if not rows:
        logger.info("[GEO] No missing coordinates.")
        return

    logger.info("[GEO] Geocoding %d records (district-table first, Nominatim fallback)...", len(rows))
    cache = _load()
    geo   = Nominatim(user_agent="divyadrishti_tender_v3")
    updated = 0

    for row in rows:
        state, district = row["state"], row["district"]

        # 1. District coordinate table (case-insensitive, no network)
        c = _district_coords(state, district)
        if c:
            lat, lon = c["lat"], c["lon"]
        else:
            # 2. Nominatim with clean query (no Samastipur suffix)
            if district and district not in ("Unknown", ""):
                loc = f"{district}, {state}, India"
            else:
                loc = f"{state}, India"

            if loc in cache:
                lat, lon = cache[loc]["lat"], cache[loc]["lon"]
            else:
                try:
                    time.sleep(1)
                    result = geo.geocode(loc, exactly_one=True, timeout=10)
                    if result:
                        lat, lon = result.latitude, result.longitude
                    else:
                        # 3. State centre fallback
                        sc = STATE_CENTERS.get(state, {})
                        lat, lon = sc.get("lat", 22.5), sc.get("lon", 82.5)
                except (GeocoderTimedOut, GeocoderServiceError):
                    sc = STATE_CENTERS.get(state, {})
                    lat, lon = sc.get("lat", 22.5), sc.get("lon", 82.5)
                cache[loc] = {"lat": lat, "lon": lon}

        conn.execute(
            "UPDATE tenders SET latitude=?, longitude=? WHERE tender_id=?",
            (lat, lon, row["tender_id"]),
        )
        updated += 1

    conn.commit()
    _save(cache)
    logger.info("[GEO] Geocoding complete — %d records updated.", updated)


def run_entity_enrichment(limit: int = 500) -> int:
    """
    Real-world entity geocoding pass (slow — Nominatim 1 req/sec).
    Pulls real lat/lon by parsing each tender title for hospitals, schools,
    roads (A→B), etc., and replacing the district-centre approximation.
    """
    from services.enricher import enrich_db_geocode
    from repository.db import DB_PATH
    return enrich_db_geocode(str(DB_PATH), limit=limit)


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
    from scrapers.nic import scrape_nic_portal, scrape_gepnic_state
    from scrapers.gem import scrape_gem
    from scrapers.api_sources import scrape_datagov, scrape_pmgsy
    from scrapers.states.chhattisgarh import scrape_cgstate_cheps
    from scrapers.states.bihar import scrape_bihar_epsv2
    from scrapers.states.up import (
        scrape_upjalNigam, scrape_upeida_archive, scrape_upsbc,
        scrape_etender_up_orgs, scrape_upmsc, scrape_pvvnl, scrape_mvvnl,
    )
    # JS-rendered PSU portals: ONGC (Liferay), NHAI (REST API), Coal India (DataTables)
    from scrapers.js_portals import scrape_ongc, scrape_nhai, scrape_coal_india
    # Static HTML PSU portals: MSEDCL (WordPress), Chennai Port, BHEL
    from scrapers.central_psu import scrape_all_psu

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
            logger.error("[OGD] --api-key required for data.gov.in source.")
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

    # 5. PMGSY — gram-panchayat rural road tenders (block level)
    if "pmgsy" in sources:
        recs = scrape_pmgsy(max_pages, headless, conn=conn)
        n = upsert(conn, recs)
        summary["PMGSY"] = n
        logger.info("PMGSY: %d records saved", n)

    # 6. Chhattisgarh CHEPS — Java Struts RFQ portal (not NIC GePNIC)
    if "cgstate" in sources:
        recs = scrape_cgstate_cheps(max_pages, headless, conn=conn)
        n = upsert(conn, recs)
        summary["CHEPS/Chhattisgarh"] = n
        logger.info("CHEPS/Chhattisgarh: %d records saved", n)

    # 7. Bihar EPS v2 — JS hash-tab portal with AJAX pagination
    if "biharv2" in sources:
        recs = scrape_bihar_epsv2(max_pages, headless, conn=conn)
        n = upsert(conn, recs)
        summary["EPSV2/Bihar"] = n
        logger.info("EPSV2/Bihar: %d records saved", n)

    # 8. UP custom portals: Jal Nigam (7,500+), UPEIDA archive, State Bridge Corp
    if "up_misc" in sources:
        recs = scrape_upjalNigam(max_pages, conn=conn)
        n = upsert(conn, recs)
        summary["Jal Nigam/UP"] = n
        logger.info("Jal Nigam/UP: %d records saved", n)

        recs = scrape_upeida_archive(conn=conn)
        n = upsert(conn, recs)
        summary["UPEIDA/UP"] = n
        logger.info("UPEIDA/UP: %d records saved", n)

        recs = scrape_upsbc(conn=conn)
        n = upsert(conn, recs)
        summary["UPSBC/UP"] = n
        logger.info("UPSBC/UP: %d records saved", n)

    # 9b. UP sector-specific portals — Health, MSME, Social Welfare, Digital & IT
    if "up_sectors" in sources:
        recs = scrape_etender_up_orgs(conn=conn)
        for src in set(r["source"] for r in recs):
            n = upsert(conn, [r for r in recs if r["source"] == src])
            summary[src] = n
            logger.info("%s: %d records saved", src, n)

        recs = scrape_upmsc(conn=conn)
        n = upsert(conn, recs)
        summary["UPMSC/UP"] = n
        logger.info("UPMSC/UP: %d records saved", n)

    # 9a. UP power distribution companies — Energy sector diversity
    if "up_power" in sources:
        recs = scrape_pvvnl(conn=conn)
        n = upsert(conn, recs)
        summary["PVVNL/UP"] = n
        logger.info("PVVNL/UP: %d records saved", n)

        recs = scrape_mvvnl(years=4, max_pages=max_pages, conn=conn)
        n = upsert(conn, recs)
        summary["MVVNL/UP"] = n
        logger.info("MVVNL/UP: %d records saved", n)

    # 10. Central PSU portals — HTML-rendered (MSEDCL, Chennai Port, BHEL)
    if "psu_html" in sources:
        psu_result = scrape_all_psu(conn=conn)
        summary.update(psu_result)

    # 11. JS-rendered PSU portals — ONGC (Liferay portlet), NHAI (REST API), Coal India (DataTables)
    if "ongc" in sources:
        recs = scrape_ongc(conn=conn)
        n = upsert(conn, recs)
        summary["ONGC"] = n
        logger.info("ONGC: %d records saved", n)

    if "nhai" in sources:
        recs = scrape_nhai(conn=conn)
        n = upsert(conn, recs)
        summary["NHAI"] = n
        logger.info("NHAI: %d records saved", n)

    if "coal_india" in sources:
        recs = scrape_coal_india(conn=conn)
        n = upsert(conn, recs)
        summary["Coal-India"] = n
        logger.info("Coal India: %d records saved", n)

    # Geocode any missing coordinates (fast — district-level only)
    geocode_missing_db(conn)

    total = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
    conn.close()

    return summary, total
