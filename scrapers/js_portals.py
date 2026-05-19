"""
scrapers/js_portals.py

Scrapers for major central-government and PSU portals whose tender pages
are rendered by JavaScript (Liferay portlets, Angular SPA, DataTables).

Portals covered
───────────────
  ONGC      — Liferay portlet (tenders.ongc.co.in)
              Playwright: navigate → click "Current NITs" → parse HTML table.

  NHAI      — Angular SPA (nhai.gov.in)
              REST API: POST /nhai/api/tenderlist — no browser needed.
              Returns all active tenders as JSON in one call.

  Coal India — WordPress + DataTables (coalindia.in)
               Playwright: load /tenders/tenderupload/ → parse expanded table rows.

  NTPC      — ntpctender.ntpc.co.in
               BLOCKED: Google reCAPTCHA v2/v3 on the search form.
               Tender list is not accessible without a valid CAPTCHA token.
               Stub documented here for future implementation.

Why Playwright instead of plain requests?
  ONGC's "Current NITs" link contains a Liferay CSRF token (p_auth=…) that
  changes every session.  Playwright handles the session automatically and lets
  us click the generated link without extracting the token by hand.

  Coal India uses DataTables — the initial HTML has all rows but they are
  hidden by JS; Playwright waits for the JS to render before we scrape.

Author: DivyaDrishti automated pipeline
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

import requests
from playwright.async_api import async_playwright, Page
import asyncio

from services.classifier import classify_sector
from services.block_extractor import extract_block_from_title
from repository.db import get_db, upsert, log_health

logger = logging.getLogger(__name__)

# ── ONGC location → Indian state mapping ────────────────────────────────────
# ONGC operates across multiple basins; the "Location" column in the NIT table
# contains basin/field names rather than administrative state names.
# Partial map — new fields are added as they appear in scraped data.
_ONGC_LOCATION_STATE: dict[str, str] = {
    "Cambay":         "Gujarat",
    "Mumbai":         "Maharashtra",
    "Delhi":          "Delhi",
    "Jorhat":         "Assam",
    "Sibsagar":       "Assam",
    "Agartala":       "Tripura",
    "Rajahmundry":    "Andhra Pradesh",
    "Chennai":        "Tamil Nadu",
    "Kolkata":        "West Bengal",
    "Ankleshwar":     "Gujarat",
    "Vadodara":       "Gujarat",
    "Mehsana":        "Gujarat",
    "Ahmedabad":      "Gujarat",
    "Surat":          "Gujarat",
    "Nazira":         "Assam",
    "Duliajan":       "Assam",
    "Dehradun":       "Uttarakhand",
    "Bokaro":         "Jharkhand",
    "Hazira":         "Gujarat",
    "Kakinada":       "Andhra Pradesh",
    "Hyderabad":      "Telangana",
    "Pune":           "Maharashtra",
    "Tripura":        "Tripura",
    "Rajasthan":      "Rajasthan",
    "HQ":             "Unknown",  # ONGC Delhi HQ — not location-specific
    "Head Office":    "Unknown",
    "Offshore":       "Unknown",  # Offshore platforms — no state
}


# ── Shared record factory ────────────────────────────────────────────────────

def _make_record(
    source: str,
    tender_id: str,
    title: str,
    department: str,
    state: str,
    sector: str = "",
    start_date: str = "",
    end_date: str = "",
    url: str = "",
    district: str = "Unknown",
    amount: float = 0.0,
) -> dict:
    """
    Build a standardised tender dict for upsert into the tenders table.

    All fields match the DB schema defined in repository/db.py.
    tender_id is prefixed with 'source-' before being stored, so duplicates
    across different portals with the same NIT number are avoided.
    """
    sector = sector or classify_sector(title)
    block  = extract_block_from_title(title)
    return {
        "tender_id":        f"{source}-{tender_id}",
        "title":            title,
        "sector":           sector,
        "department":       department,
        "state":            state,
        "district":         district,
        "block":            block or "Unknown",
        "allocated_amount": amount,
        "latitude":         None,
        "longitude":        None,
        "status":           "Active",
        "source":           source,
        "source_url":       url,
        "contractor_name":  "",
        "start_date":       start_date,
        "end_date":         end_date,
        "scraped_at":       time.strftime("%Y-%m-%d"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  ONGC — Liferay portlet (tenders.ongc.co.in/web/tendersweb/home)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Architecture:
#   tenders.ongc.co.in runs Liferay DXP.  All tender actions are served via a
#   single portlet (com_ongc_tender_OngcTenderWebPortlet_INSTANCE_oajq).
#   The portlet URL includes a session-specific CSRF token: p_auth=<8char>.
#   Playwright loads the home page (which triggers Liferay to set the token),
#   then we grab the "Current NITs" link that already contains the fresh token
#   and navigate to it.
#
# Table columns on the Current NITs page:
#   Tender Number | Tender Description | Tender Type | Location | Uploaded Date
#
# Pagination:
#   The table renders all rows on one page (no "Next" button observed).
#   If pagination appears in future, re-check the Liferay portlet parameters
#   (_...._javax.portlet.action=tender-currentNIT&pageNo=2 etc.).

ONGC_HOME = "https://tenders.ongc.co.in/web/tendersweb/home"


async def _scrape_ongc() -> list[dict]:
    """
    Playwright scraper for ONGC "Current NITs" table.

    Steps:
      1. Load home page — Liferay sets the p_auth CSRF token.
      2. Find the link whose href contains 'tender-currentNIT'.
      3. Navigate to that URL (carries valid p_auth).
      4. Parse the HTML table into tender dicts.
    """
    records: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await browser.new_page()

        logger.info("[ONGC] Loading home page to obtain session token...")
        await page.goto(ONGC_HOME, timeout=30_000, wait_until="networkidle")
        await page.wait_for_timeout(3_000)

        # Find the "Current NITs" portlet link — it carries the live p_auth token
        nit_links = await page.eval_on_selector_all(
            "a[href*='tender-currentNIT']",
            "els => els.map(e => e.href)"
        )
        if not nit_links:
            logger.error("[ONGC] 'Current NITs' link not found — page structure may have changed")
            await browser.close()
            return []

        logger.info("[ONGC] Navigating to Current NITs page...")
        await page.goto(nit_links[0], timeout=25_000, wait_until="networkidle")
        await page.wait_for_timeout(3_000)

        # Parse the NIT table.
        # ONGC uses <th class="tno" scope="row"> for the Tender Number column
        # and <td> for the remaining columns.  We must select both th+td to
        # get all 5 columns; querying only "td" returns only 4 cells.
        rows = await page.query_selector_all("table tr")
        for row in rows:
            # Select th AND td — the tender number is in a <th scope="row">
            cells_el = await row.query_selector_all("th, td")
            if len(cells_el) < 4:
                continue  # skip rows with too few cells (separators, etc.)

            cells = [await c.inner_text() for c in cells_el]

            tender_no   = cells[0].strip()
            description = cells[1].strip()
            tender_type = cells[2].strip() if len(cells) > 2 else ""
            location    = cells[3].strip() if len(cells) > 3 else ""
            upload_date = cells[4].strip() if len(cells) > 4 else ""

            # Skip the column-header row ("Tender Number", "Tender Description", …)
            if "tender number" in tender_no.lower() or not tender_no:
                continue

            # Clean up tender_no — sometimes spaces are inserted mid-number
            tender_no_clean = re.sub(r"\s+", "", tender_no)

            # Map ONGC field/basin location to Indian state
            state = "Unknown"
            for loc_key, state_val in _ONGC_LOCATION_STATE.items():
                if loc_key.lower() in location.lower():
                    state = state_val
                    break

            # Use upload date as start_date; no closing date shown in this table
            rec = _make_record(
                source="ONGC",
                tender_id=tender_no_clean,
                title=description,
                department=f"ONGC / {location}" if location else "ONGC",
                state=state,
                start_date=upload_date,
                url=ONGC_HOME,
                district=location or "Unknown",  # basin/field as proxy for district
            )
            records.append(rec)

        logger.info("[ONGC] Scraped %d Current NITs", len(records))
        await browser.close()

    return records


def scrape_ongc(conn=None) -> list[dict]:
    """
    Synchronous wrapper for the ONGC Playwright scraper.
    Saves results to the database and returns the list of tender dicts.
    """
    records = asyncio.run(_scrape_ongc())
    if not records:
        log_health(conn or get_db(), "ONGC", ONGC_HOME, "failed",
                   error_msg="No records scraped")
        return []

    db = conn or get_db()
    saved = upsert(db, records)
    log_health(db, source="ONGC", domain="tenders.ongc.co.in",
               status="ok", records_fetched=len(records))
    logger.info("[ONGC] Saved %d / %d records to DB", saved, len(records))
    return records


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  NHAI — Angular SPA (nhai.gov.in/#/tenders)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Architecture:
#   NHAI's website is an Angular 10 SPA.  The "/#/tenders" route triggers an
#   AJAX POST to /nhai/api/tenderlist with multipart/form-data parameters.
#
#   This endpoint is publicly accessible — no session cookie or CAPTCHA needed.
#   A plain requests.post() call returns all active tenders as JSON.
#
# Pagination:
#   The API accepts 'index' (page offset) and 'totalrecord' (page size).
#   Setting totalrecord=500 returns all records in one shot (total ~117 as of May 2026).
#
# Response shape:
#   {
#     "_resultflag": 1,
#     "total_count": 117,
#     "message": "success",
#     "list": [
#       {
#         "id": "58190",
#         "title": "Notice Inviting Quotation For Architectural Consultancy Services",
#         "publish_date": "2026-05-18 05:30:00",
#         "tender_no": "NHAI/HQ/DPR-Cell/NIQ/2026",
#         "bid_submission_end_date": "2026-05-25",
#         "bid_opening_date": "2026-05-25",
#         ...
#       }, ...
#     ]
#   }
#
# Note: title is returned in English when `language=en` is posted.

NHAI_API  = "https://nhai.gov.in/nhai/api/tenderlist"
NHAI_HOME = "https://nhai.gov.in/#/tenders"


def _fetch_nhai_page(index: int, page_size: int = 200) -> dict:
    """
    POST to the NHAI tenderlist API and return the parsed JSON response.
    'index' is the zero-based offset (0 = first page, 200 = second page, …).
    """
    resp = requests.post(
        NHAI_API,
        files={
            "language":      (None, "en"),
            "index":         (None, str(index)),
            "totalrecord":   (None, str(page_size)),
            "tender_no":     (None, ""),
            "title":         (None, ""),
            "bid_from_date": (None, ""),
            "bid_to_date":   (None, ""),
            "category_id":   (None, ""),
            "department_id": (None, ""),
            "captcha_page":  (None, "0"),
            "verification":  (None, ""),
        },
        headers={
            "Referer":    "https://nhai.gov.in/",
            "User-Agent": "Mozilla/5.0",
            "Accept":     "application/json, text/plain, */*",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def scrape_nhai(conn=None) -> list[dict]:
    """
    Scrape all active tenders from the NHAI REST API.

    NHAI is a central body (Ministry of Road Transport & Highways).
    All tenders are national highways — state is "Multiple / National" unless
    a state name can be extracted from the tender title.

    Returns list of tender dicts.
    """
    records: list[dict] = []
    page_size = 200
    index = 0

    while True:
        try:
            data = _fetch_nhai_page(index, page_size)
        except Exception as e:
            logger.error("[NHAI] API fetch failed at index=%d: %s", index, e)
            break

        if data.get("_resultflag") != 1:
            logger.info("[NHAI] API returned no records at index=%d (flag=%s)",
                        index, data.get("_resultflag"))
            break

        items = data.get("list", [])
        if not items:
            break

        for item in items:
            tender_no   = item.get("tender_no", "") or str(item.get("id", ""))
            title       = item.get("title", "").strip()
            start_date  = (item.get("publish_date") or "")[:10]       # trim to YYYY-MM-DD
            end_date    = (item.get("bid_submission_end_date") or "")[:10]

            if not title:
                continue

            # Attempt to extract state from title text
            state = "Unknown"
            from services.classifier import extract_state_from_org
            state_extracted = extract_state_from_org(title)
            if state_extracted:
                state = state_extracted

            rec = _make_record(
                source="NHAI",
                tender_id=tender_no or str(item.get("id", "")),
                title=title,
                department="NHAI / National Highways Authority of India",
                state=state,
                start_date=start_date,
                end_date=end_date,
                url=NHAI_HOME,
            )
            records.append(rec)

        total = int(data.get("total_count") or 0)
        index += page_size
        if index >= total or len(items) < page_size:
            break

    db = conn or get_db()
    if records:
        saved = upsert(db, records)
        log_health(db, source="NHAI", domain="nhai.gov.in",
                   status="ok", records_fetched=len(records))
        logger.info("[NHAI] Saved %d / %d records to DB", saved, len(records))
    else:
        log_health(db, source="NHAI", domain="nhai.gov.in",
                   status="failed", error_msg="No records fetched")
        logger.warning("[NHAI] No records scraped")

    return records


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  Coal India — WordPress + DataTables (coalindia.in/tenders/tenderupload/)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Architecture:
#   Coal India Limited (CIL) publishes tenders at /tenders/tenderupload/ as a
#   WordPress page with a DataTables-enhanced HTML table.  All rows are already
#   in the initial HTML (DataTables processes them client-side), so plain
#   requests can read them — but each row also has an expandable detail panel
#   (visible after clicking "View") that holds extra metadata.
#
#   We use Playwright so DataTables' JS fully initialises and the expanded rows
#   become visible in the DOM, then read all at once.
#
# Table structure (each <tr> has 4 base cells):
#   col[0] = Tender Reference No. (e.g., "GEM/2026/B/7457235 Dated 21-Apr-2026")
#   col[1] = Title / Description
#   col[2] = Opening / Expiry Date
#   col[3] = "View" (action button — expands detail panel below)
#
# Expanded detail panel (next <tr> after each data row) contains:
#   Tender Value, EMD, Document Cost, Sale dates, Contact name + address.
#
# All CIL HQ tenders originate in Kolkata (West Bengal).
# Subsidiary tenders (ECL, BCCL, CCL, NCL, WCL, SECL, MCL, NEC) have state
# encoded in the contact address — we extract it there.

COAL_INDIA_URL = "https://www.coalindia.in/tenders/tenderupload/"


async def _scrape_coal_india() -> list[dict]:
    """
    Playwright scraper for Coal India tender table.

    Navigates to the all-tenders listing, reads the DataTables-rendered HTML
    table, and parses both the base row (Reference No + Title + Date) and the
    expanded detail row (Tender Value, Contact address for state extraction).
    """
    records: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await browser.new_page()

        logger.info("[Coal India] Loading tender listing...")
        await page.goto(COAL_INDIA_URL, timeout=30_000, wait_until="networkidle")
        await page.wait_for_timeout(3_000)

        # The tender table has id="alltender" (DataTables plugin).
        # Each outer data row has 5 cells:
        #   [0] Tender Reference No.
        #   [1] Title / Description
        #   [2] Opening / Expiry Date
        #   [3] "View" link
        #   [4] Hidden detail panel (display:none) — contains Tender Value,
        #       EMD, Sale dates, Contact address.
        #
        # Using "#alltender > tbody > tr" avoids inner-table <tr> elements
        # from the detail panel being mixed into the main row list.
        rows = await page.query_selector_all("#alltender > tbody > tr")
        if not rows:
            # Fallback: look for any table with more than 3 td columns
            rows = await page.query_selector_all("table tbody tr")

        for row in rows:
            cells_el = await row.query_selector_all("td")
            if len(cells_el) < 3:
                continue

            tender_ref = (await cells_el[0].inner_text()).strip()
            title      = (await cells_el[1].inner_text()).strip()
            close_date = (await cells_el[2].inner_text()).strip()

            if not tender_ref or "tender ref" in tender_ref.lower():
                continue

            # Remove " Dated xx-xx-xxxx" suffix from reference number
            tender_ref_clean = re.split(r"\s+[Dd]ated", tender_ref)[0].strip()

            # Extract detail data from the hidden 5th cell (cells_el[4])
            amount = 0.0
            state  = "West Bengal"  # CIL HQ is in Kolkata (West Bengal)
            if len(cells_el) > 4:
                detail_text = await cells_el[4].inner_text()

                # Tender Value: e.g. "350,80,00,000.000" or "Rs. 7,35,87,624"
                val_m = re.search(
                    r"Tender\s+Value\s*[:\n]?\s*(?:Rs\.?\s*)?([\d,]+(?:\.\d+)?)",
                    detail_text, re.IGNORECASE,
                )
                if val_m:
                    try:
                        amount = float(val_m.group(1).replace(",", ""))
                    except ValueError:
                        pass

                # State from contact address — subsidiaries are in other states
                from services.classifier import extract_state_from_org
                state_from_contact = extract_state_from_org(detail_text)
                if state_from_contact and state_from_contact != "Unknown":
                    state = state_from_contact

            rec = _make_record(
                source="Coal-India",
                tender_id=re.sub(r"[^A-Za-z0-9]", "-", tender_ref_clean[:80]),
                title=title,
                department="Coal India Limited",
                state=state,
                end_date=close_date,
                url=COAL_INDIA_URL,
                amount=amount,
            )
            records.append(rec)

        logger.info("[Coal India] Scraped %d tenders", len(records))
        await browser.close()

    return records


def scrape_coal_india(conn=None) -> list[dict]:
    """
    Synchronous wrapper for the Coal India Playwright scraper.
    """
    records = asyncio.run(_scrape_coal_india())
    if not records:
        log_health(conn or get_db(), "Coal-India", COAL_INDIA_URL, "failed",
                   error_msg="No records scraped")
        return []

    db = conn or get_db()
    saved = upsert(db, records)
    log_health(db, source="Coal-India", domain="coalindia.in",
               status="ok", records_fetched=len(records))
    logger.info("[Coal India] Saved %d / %d records to DB", saved, len(records))
    return records


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  NTPC — ntpctender.ntpc.co.in  [BLOCKED — reCAPTCHA]
# ═══════════════════════════════════════════════════════════════════════════════
#
# Status: BLOCKED by Google reCAPTCHA v2/v3.
#
# Investigation findings (2026-05-19):
#   • The /Index/Search? form loads Google reCAPTCHA before allowing submission.
#   • Clicking the Search button in headless Playwright triggers reCAPTCHA which
#     must be solved before the form POSTs — no tender rows appear without it.
#   • Regional links (/Index/Search?Type=Reg&Region=N) pre-select a dropdown but
#     still need the CAPTCHA before results are shown.
#   • No unauthenticated JSON API was found — all data endpoints require the
#     CAPTCHA-validated form token.
#   • The /Index/GetCategory, GetSubMenusReg, GetCity etc. endpoints only return
#     filter option lists, not the actual tender rows.
#
# Future bypass options:
#   1. 2captcha / Anti-Captcha service — paid API, ~$3 / 1000 solves.
#      Pass reCAPTCHA site key (found in page source) to the service, receive
#      g-recaptcha-response token, inject it before form submit.
#   2. Register as a vendor (free) and use the authenticated search API.
#      Authenticated sessions skip reCAPTCHA for most searches.
#   3. NTPC also publishes tenders on GePNIC (already scraped via scrapers/nic.py)
#      and GeM (scrapers/gem.py) — cross-referencing those reduces the gap.

NTPC_HOME = "https://ntpctender.ntpc.co.in/"


def scrape_ntpc(conn=None) -> list[dict]:
    """
    NTPC scraper stub — returns empty list with a health log entry explaining why.
    Replace with 2captcha integration once a solve API key is available.
    """
    logger.warning(
        "[NTPC] Scraping blocked: Google reCAPTCHA required. "
        "Tenders are also on GePNIC (nic.py) and GeM (gem.py)."
    )
    db = conn or get_db()
    log_health(db, source="NTPC", domain="ntpctender.ntpc.co.in",
               status="blocked", error_msg="Google reCAPTCHA blocks unauthenticated search")
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# 5.  Convenience aggregator
# ═══════════════════════════════════════════════════════════════════════════════

def scrape_all_js_portals(conn=None) -> dict[str, int]:
    """
    Run all JS-rendered portal scrapers in sequence.
    Returns a dict mapping source name → records saved.

    Skips NTPC (blocked by reCAPTCHA).
    """
    db = conn or get_db()
    results: dict[str, int] = {}

    for name, fn in [
        ("ONGC",       scrape_ongc),
        ("NHAI",       scrape_nhai),
        ("Coal-India", scrape_coal_india),
        # NTPC skipped — see docstring above
    ]:
        try:
            recs = fn(conn=db)
            results[name] = len(recs)
            logger.info("[JS Portals] %s: %d records", name, len(recs))
        except Exception as e:
            logger.error("[JS Portals] %s failed: %s", name, e)
            results[name] = 0

    return results
