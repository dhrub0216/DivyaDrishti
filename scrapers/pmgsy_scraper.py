"""
scrapers/pmgsy_scraper.py

Scrapes pmgsytenders.gov.in using Playwright + ddddocr CAPTCHA solving.
Flow: load Active Tenders page → extract CAPTCHA image → preprocess →
      ddddocr solve → submit form → paginate results → save to DB.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import time
from typing import Optional

import ddddocr
import numpy as np
from PIL import Image
from playwright.async_api import async_playwright, Page

from services.classifier import make_record, classify_sector, extract_state_from_org, parse_amount
from services.block_extractor import extract_block_from_title
from repository.db import get_db, upsert, log_health

logger = logging.getLogger(__name__)

BASE_URL = "https://www.pmgsytenders.gov.in/nicgep/app"
ACTIVE_URL = f"{BASE_URL}?page=FrontEndLatestActiveTenders&service=page"

# NIC org-code prefix → Indian state (from tender-ID patterns)
_ORG_CODE_STATE: dict = {
    "JKRRD": "Jammu & Kashmir",
    "KSRD":  "Karnataka",
    "KSRRD": "Karnataka",
    "MPRRD": "Madhya Pradesh",
    "CEJHR": "Jharkhand",
    "CEHP":  "Himachal Pradesh",
    "CEMAH": "Maharashtra",
    "CERJ":  "Rajasthan",
    "CEAR":  "Arunachal Pradesh",
    "CEASM": "Assam",
    "ENCPR": "Chhattisgarh",
    "APWD":  "Andhra Pradesh",
    "PWDBR": "Bihar",
    "AGRI":  "Unknown",        # agriculture dept — state unclear
}

_ocr = ddddocr.DdddOcr(show_ad=False)


# ---------------------------------------------------------------------------
# CAPTCHA solving
# ---------------------------------------------------------------------------

def _preprocess_captcha(png_bytes: bytes) -> bytes:
    """
    NIC PMGSY CAPTCHAs are RGBA PNGs: black character pixels + coloured noise dots.
    Extract only black pixels onto a white background, return as PNG bytes.
    """
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    arr = np.array(img)
    black_mask = (arr[:, :, 0] == 0) & (arr[:, :, 1] == 0) & (arr[:, :, 2] == 0) & (arr[:, :, 3] > 0)
    clean = np.ones((arr.shape[0], arr.shape[1], 3), dtype=np.uint8) * 255
    clean[black_mask] = [0, 0, 0]
    out = Image.fromarray(clean, "RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def _solve_captcha_bytes(png_bytes: bytes) -> str:
    """Return solved CAPTCHA text from raw PNG bytes."""
    try:
        clean = _preprocess_captcha(png_bytes)
        text = _ocr.classification(clean).strip()
        return text
    except Exception as e:
        logger.warning("ddddocr failed: %s", e)
        return ""


async def _get_captcha_text(page: Page) -> str:
    """Extract and solve the CAPTCHA from the current page."""
    img_el = await page.query_selector("img#captchaImage")
    if not img_el:
        logger.warning("captchaImage element not found")
        return ""
    src = await img_el.get_attribute("src") or ""
    if src.startswith("data:image/png;base64,"):
        b64 = src.split(",", 1)[1]
        png = base64.b64decode(b64)
    else:
        png = await page.evaluate("el => fetch(el.src).then(r=>r.arrayBuffer())", img_el)
        png = bytes(png)
    return _solve_captcha_bytes(png)


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

def _parse_row(cells: list, page_num: int) -> Optional[dict]:
    """Parse a result table row into a tender dict."""
    if len(cells) < 5:
        return None
    # Columns: S.No | e-Published Date | Bid Submission Closing | Opening Date | Title+Ref | Org Chain
    title_cell = cells[4] if len(cells) > 4 else ""
    org_cell   = cells[5] if len(cells) > 5 else ""

    # Extract title and tender ID.
    # NIC PMGSY format: "[Title text][Ref/NIC code][2024_ORG_NNNNN_N]"
    lines = [l.strip() for l in title_cell.split("\n") if l.strip()]
    title = lines[0] if lines else ""
    if not title:
        return None                     # skip blank / navigation rows

    tender_id = ""
    # 1) Explicit "Tender ID:" label
    for line in lines:
        m = re.search(r"Tender\s+ID\s*[:\-]\s*(\S+)", line, re.IGNORECASE)
        if m:
            tender_id = m.group(1)
            break
        m = re.search(r"Ref\.?\s*No\.?\s*[:\-]\s*(\S+)", line, re.IGNORECASE)
        if m:
            tender_id = m.group(1)

    # 2) NIC bracket format: last [YYYY_ORG_NNNNN_N] token
    if not tender_id:
        m = re.search(r'\[(\d{4}_[A-Z]+_\d+_\d+)\]', title_cell)
        if m:
            tender_id = m.group(1)

    # 3) Fallback: hash (no extra prefix — the field below adds the one PMGSY- prefix)
    if not tender_id:
        tender_id = str(abs(hash(title)) % 10 ** 9)

    publish_date = cells[1].strip() if len(cells) > 1 else ""
    close_date   = cells[2].strip() if len(cells) > 2 else ""

    # Sanity-check dates — skip navigation rows that leaked into the table
    if "|" in close_date or "|" in publish_date:
        return None

    state = extract_state_from_org(org_cell) if org_cell else "Unknown"

    # Supplement state via NIC org-code embedded in tender_id (YYYY_ORGCODE_N)
    if state == "Unknown":
        org_m = re.search(r'\d{4}_([A-Z]+)_', tender_id)
        if org_m:
            state = _ORG_CODE_STATE.get(org_m.group(1), "Unknown")

    # Further supplement from District keyword in title
    if state == "Unknown":
        dm = re.search(r'\bDistrict\s+([A-Za-z]+)', title, re.IGNORECASE)
        if dm:
            state = extract_state_from_org(dm.group(1)) or "Unknown"

    # Extract district name from title when present
    district = "Unknown"
    dm2 = re.search(r'\bDistrict\s+([A-Za-z][a-zA-Z\s]{2,}?)(?=[\]\.,]|$)', title, re.IGNORECASE)
    if dm2:
        district = dm2.group(1).strip().title()

    sector = classify_sector(title)
    block = extract_block_from_title(title)

    return {
        "tender_id": f"PMGSY-{tender_id}",
        "title": title,
        "sector": sector,
        "department": "PMGSY / Rural Roads",
        "state": state,
        "district": district,
        "block": block or "Unknown",
        "allocated_amount": 0.0,
        "latitude": None,
        "longitude": None,
        "status": "Active",
        "source": "PMGSY",
        "source_url": BASE_URL,
        "contractor_name": "",
        "start_date": publish_date,
        "end_date": close_date,
        "scraped_at": time.strftime("%Y-%m-%d"),
    }


async def _scrape_active(headless: bool = True, max_retries: int = 5) -> list[dict]:
    """Navigate PMGSY Active Tenders with CAPTCHA solving + full pagination."""
    records: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        # ── Initial page load ──────────────────────────────────────────────
        await page.goto(ACTIVE_URL, timeout=30_000)
        await page.wait_for_timeout(2_000)

        # ── Solve CAPTCHA and submit ───────────────────────────────────────
        # NIC PMGSY CAPTCHAs appear mixed-case visually but ddddocr always
        # lowercases output.  Strategy: for each CAPTCHA load, try lowercase
        # then UPPERCASE (re-reading the image before the uppercase attempt in
        # case the portal auto-refreshed it after the first rejection).
        solved = False
        for attempt in range(1, max_retries + 1):
            cap_accepted = False
            for case_pass in ("lower", "UPPER"):
                # Re-read CAPTCHA on every sub-attempt (handles auto-refresh)
                cap_text = await _get_captcha_text(page)
                if not cap_text:
                    logger.warning("Empty CAPTCHA solve (attempt %d %s)", attempt, case_pass)
                    break

                variant = cap_text.upper() if case_pass == "UPPER" else cap_text
                logger.info("CAPTCHA attempt %d/%s: %s", attempt, case_pass, variant)

                cap_input = await page.query_selector(
                    "input#captchaText, input[name='captchaText'], input[placeholder*='aptcha' i]"
                )
                if not cap_input:
                    logger.error("Captcha input field not found")
                    cap_accepted = None  # signal hard break
                    break

                await cap_input.fill(variant)
                await page.wait_for_timeout(300)

                search_btn = await page.query_selector("input#Submit, input[value='Search']")
                if search_btn:
                    await search_btn.scroll_into_view_if_needed()
                    await search_btn.click(force=True)
                else:
                    await cap_input.press("Enter")

                try:
                    await page.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
                await page.wait_for_timeout(2_000)

                page_text = await page.inner_text("body")
                page_html  = await page.content()

                if "Invalid Captcha" in page_text or "failure.png" in page_html:
                    logger.warning("CAPTCHA rejected (%s/%s): %s", attempt, case_pass, variant)
                    # Save debug screenshot on first rejection so we can inspect
                    if attempt == 1 and case_pass == "lower":
                        await page.screenshot(path="/tmp/pmgsy_rejected.png")
                    refresh = await page.query_selector("img[src*='refresh'], a[id*='refresh' i]")
                    if refresh:
                        await refresh.click()
                        await page.wait_for_timeout(1_500)
                    continue

                result_rows = await page.query_selector_all("table tr td:first-child")
                digit_rows = 0
                for td in result_rows:
                    txt = (await td.inner_text()).strip()
                    if txt and txt[0].isdigit():
                        digit_rows += 1

                if digit_rows > 0 or ("No Tenders" in page_text and "Provide Captcha" not in page_text):
                    solved = True
                    cap_accepted = True
                    logger.info("CAPTCHA accepted (%d/%s '%s'), %d result rows",
                                attempt, case_pass, variant, digit_rows)
                    break

                logger.warning("No results after submit (%d/%s), retrying", attempt, case_pass)

            if cap_accepted is True:
                break
            if cap_accepted is None:          # hard error (input not found)
                break
            if attempt == max_retries:
                logger.warning("CAPTCHA still not solved after %d attempts", max_retries)

        if not solved:
            logger.error("CAPTCHA solving failed — aborting")
            await browser.close()
            return []

        # ── Debug: screenshot first results page ──────────────────────────
        await page.screenshot(path="/tmp/pmgsy_results_p1.png", full_page=True)

        # ── Paginate through results ───────────────────────────────────────
        page_num = 1
        while True:
            rows = await page.query_selector_all("table tr")
            new_count = 0
            for row in rows:
                cells_el = await row.query_selector_all("td")
                if not cells_el:
                    continue
                cells = [await c.inner_text() for c in cells_el]
                if not cells[0].strip() or not cells[0].strip()[0].isdigit():
                    continue
                rec = _parse_row(cells, page_num)
                if rec:
                    records.append(rec)
                    new_count += 1

            logger.info("Page %d: %d new tenders (total %d)", page_num, new_count, len(records))

            # NIC PMGSY uses text links for pagination: "Previous" / "Next" or page numbers
            next_link = await page.query_selector(
                "a:has-text('Next '), a:has-text('>> '), "
                "td a:has-text('Next'), td a:has-text('>>'), "
                "a[id*='next' i], a[class*='next' i]"
            )
            if not next_link:
                # Log all <a> tags to help diagnose missing pagination
                all_links = await page.eval_on_selector_all(
                    "a", "els => els.map(e => e.innerText.trim()).filter(t => t)"
                )
                logger.info("All links on page %d: %s", page_num, all_links[:20])
                logger.info("No 'Next' link found — end of results")
                break

            await next_link.click(force=True)
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            await page.wait_for_timeout(2_000)
            page_num += 1
            if page_num > 300:
                break

        await browser.close()

    logger.info("Scraped %d PMGSY tenders total", len(records))
    return records


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scrape_pmgsy_active(headless: bool = True, conn=None) -> list[dict]:
    """
    Synchronous wrapper — scrapes all PMGSY Active Tenders and optionally
    saves them to the DB.  Returns list of tender dicts.
    """
    records = asyncio.run(_scrape_active(headless=headless))
    if not records:
        return []

    # Block names already set in _parse_row; log health
    if conn is None:
        conn = get_db()
    saved = upsert(conn, records)
    log_health(conn, source="PMGSY", domain="pmgsytenders.gov.in",
               status="ok", records_fetched=len(records))
    logger.info("Saved %d / %d PMGSY records to DB", saved, len(records))
    return records
