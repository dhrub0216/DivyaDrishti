"""
scrapers/central_psu.py

Scrapers for major central-government and PSU tender portals whose pages
are served as static or server-rendered HTML (no JavaScript bypass needed):

  MSEDCL        — Maharashtra State Electricity Distribution Co.
                  WordPress paginated list at mahadiscom.in/en/supplier/tenders/
                  Pagination: /page/{N}/ — stop when no items on a page.
                  ~133 records across ~23 pages.

  Chennai Port  — Chennai Port Authority (renamed from Chennai Port Trust 2021).
                  8 department sub-URLs, each has a plain HTML table.
                  URL pattern: chennaiport.gov.in/tenders/{1..8}
                  ~10 records total.

  AAI           — Airports Authority of India.
                  NIT listing at aai.aero/en/tender/nit-listing.
                  Has a Drupal math CAPTCHA: a datepicker + "X + Y = " text label.
                  The math CAPTCHA is solved by reading the label and computing
                  the answer (addition only, ddddocr not needed for math CAPTCHAs).
                  NOTE: The date input widget rejects programmatic fill via JS —
                  this scraper currently returns 0 records and is a known gap.

  BHEL          — Bharat Heavy Electricals Ltd.
                  Single-page HTML table at bhel.com/tenders (~3-10 tenders).

All of these use the shared _make_record() factory to produce normalised dicts
compatible with the repository.db upsert schema.

For JavaScript-rendered PSU portals (ONGC, NHAI, Coal India, NTPC), see:
  scrapers/js_portals.py
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

from services.classifier import classify_sector
from services.block_extractor import extract_block_from_title
from repository.db import get_db, upsert, log_health

logger = logging.getLogger(__name__)

_ocr = ddddocr.DdddOcr(show_ad=False)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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
) -> dict:
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
        "allocated_amount": 0.0,
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


# ---------------------------------------------------------------------------
# 1. MSEDCL — Maharashtra State Electricity Distribution Company
#    Public paginated WordPress tender list, no login needed.
#    URL: https://www.mahadiscom.in/en/supplier/tenders/page/{N}/
# ---------------------------------------------------------------------------

MSEDCL_BASE = "https://www.mahadiscom.in/en/supplier/tenders/page/{page}/"

async def _scrape_msedcl() -> list[dict]:
    records: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page_num = 1
        while True:
            url = MSEDCL_BASE.format(page=page_num)
            try:
                await page.goto(url, timeout=25_000, wait_until="domcontentloaded")
                await page.wait_for_timeout(1_500)
            except Exception as e:
                logger.warning("MSEDCL page %d load error: %s", page_num, e)
                break

            # Each tender is an <article> or <div class="post"> with a title link and date
            items = await page.query_selector_all("article, .type-post, .hentry")
            if not items:
                # Try generic h2/h3 links as fallback
                items = await page.query_selector_all(".entry-title a, h2 a, h3 a")

            new_count = 0
            for item in items:
                try:
                    # Title link
                    link_el = await item.query_selector("a[href]") or item
                    title = (await link_el.inner_text()).strip()
                    href  = await link_el.get_attribute("href") or ""

                    # Date
                    date_el = await item.query_selector("time, .entry-date, .post-date, .published")
                    date_str = ""
                    if date_el:
                        date_str = (await date_el.inner_text()).strip()
                        if not date_str:
                            date_str = await date_el.get_attribute("datetime") or ""

                    if not title or len(title) < 5:
                        continue

                    tid = re.sub(r"[^A-Za-z0-9]", "-", title[:60])
                    rec = _make_record(
                        source="MSEDCL",
                        tender_id=tid,
                        title=title,
                        department="MSEDCL / Maharashtra Electricity Distribution",
                        state="Maharashtra",
                        start_date=date_str,
                        end_date="",
                        url=href,
                    )
                    records.append(rec)
                    new_count += 1
                except Exception:
                    continue

            logger.info("MSEDCL page %d: %d tenders (total %d)", page_num, new_count, len(records))

            if new_count == 0:
                logger.info("MSEDCL: no items on page %d — done", page_num)
                break

            # Check for next page link
            next_link = await page.query_selector("a.next.page-numbers, a[rel='next'], a:has-text('Next')")
            if not next_link:
                logger.info("MSEDCL: no next page after page %d", page_num)
                break

            page_num += 1
            if page_num > 50:
                break

        await browser.close()
    logger.info("MSEDCL: scraped %d total tenders", len(records))
    return records


def scrape_msedcl(conn=None) -> list[dict]:
    records = asyncio.run(_scrape_msedcl())
    if not records:
        return []
    if conn is None:
        conn = get_db()
    saved = upsert(conn, records)
    log_health(conn, source="MSEDCL", domain="mahadiscom.in",
               status="ok", records_fetched=len(records))
    logger.info("MSEDCL: saved %d / %d records", saved, len(records))
    return records


# ---------------------------------------------------------------------------
# 2. Chennai Port Trust
#    8 department pages; each has a clean HTML table.
#    URL: https://www.chennaiport.gov.in/tenders/{dept_id}
# ---------------------------------------------------------------------------

CHENNAI_PORT_DEPTS = {
    1: "Engineering Department",
    2: "Mechanical And Electrical Engineering",
    3: "General Administration Department",
    4: "Traffic Department",
    5: "Marine Department",
    6: "Finance Department",
    7: "Material Management Division",
    8: "Medical Department",
}
CHENNAI_PORT_BASE = "https://www.chennaiport.gov.in/tenders/{dept_id}"


async def _scrape_chennai_port() -> list[dict]:
    records: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for dept_id, dept_name in CHENNAI_PORT_DEPTS.items():
            url = CHENNAI_PORT_BASE.format(dept_id=dept_id)
            try:
                await page.goto(url, timeout=20_000, wait_until="domcontentloaded")
                await page.wait_for_timeout(1_500)
            except Exception as e:
                logger.warning("Chennai Port dept %d load error: %s", dept_id, e)
                continue

            rows = await page.query_selector_all("table tr")
            dept_count = 0
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 2:
                    continue
                cell_texts = [( await c.inner_text()).strip() for c in cells]
                # Expected: Tender No | Title | Date | Close date | Amendment
                tender_no = cell_texts[0] if len(cell_texts) > 0 else ""
                title     = cell_texts[1] if len(cell_texts) > 1 else ""
                pub_date  = cell_texts[2] if len(cell_texts) > 2 else ""
                close_dt  = cell_texts[3] if len(cell_texts) > 3 else ""

                if not tender_no or not title or len(title) < 5:
                    continue
                # Skip header row
                if tender_no.lower() in ("tender no", "s.no", "#"):
                    continue

                rec = _make_record(
                    source="Chennai-Port",
                    tender_id=re.sub(r"\s+", "-", tender_no),
                    title=title,
                    department=f"Chennai Port Trust / {dept_name}",
                    state="Tamil Nadu",
                    start_date=pub_date,
                    end_date=close_dt,
                    url=url,
                )
                records.append(rec)
                dept_count += 1

            logger.info("Chennai Port dept %d (%s): %d tenders", dept_id, dept_name, dept_count)

        await browser.close()
    logger.info("Chennai Port: scraped %d total tenders", len(records))
    return records


def scrape_chennai_port(conn=None) -> list[dict]:
    records = asyncio.run(_scrape_chennai_port())
    if not records:
        return []
    if conn is None:
        conn = get_db()
    saved = upsert(conn, records)
    log_health(conn, source="Chennai-Port", domain="chennaiport.gov.in",
               status="ok", records_fetched=len(records))
    logger.info("Chennai Port: saved %d / %d records", saved, len(records))
    return records


# ---------------------------------------------------------------------------
# 3. AAI — Airports Authority of India
#    NIT listing: https://www.aai.aero/en/tender/nit-listing
#    Has a date-range search + image CAPTCHA (solved with ddddocr).
# ---------------------------------------------------------------------------

AAI_NIT_URL = "https://www.aai.aero/en/tender/nit-listing"


def _solve_captcha_bytes(png_bytes: bytes) -> str:
    """Solve image CAPTCHA using ddddocr (same approach as PMGSY)."""
    try:
        img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        arr = np.array(img)
        # Extract dark pixels onto white background
        dark = (arr[:, :, 0] < 100) & (arr[:, :, 1] < 100) & (arr[:, :, 2] < 100) & (arr[:, :, 3] > 0)
        clean = np.ones((arr.shape[0], arr.shape[1], 3), dtype=np.uint8) * 255
        clean[dark] = [0, 0, 0]
        out = Image.fromarray(clean, "RGB")
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        text = _ocr.classification(buf.getvalue()).strip()
        return text
    except Exception as e:
        logger.warning("ddddocr error: %s", e)
        return ""


async def _get_aai_captcha(page: Page) -> str:
    """
    AAI uses a Drupal math CAPTCHA: label shows 'X + Y = ' or 'X - Y = '.
    Parse the expression and return the numeric answer as a string.
    """
    # Find the CAPTCHA label text e.g. "1 + 0 = "
    label = await page.query_selector("span.field-prefix, label[for='edit-captcha-response'], .captcha .field-prefix")
    if label:
        text = (await label.inner_text()).strip()
        # Extract math expression from text like "1 + 0 = " or "3 - 2 = "
        m = re.search(r"(\d+)\s*([+\-×x*/])\s*(\d+)", text)
        if m:
            a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
            ops = {'+': a + b, '-': a - b, '×': a * b, 'x': a * b, '*': a * b, '/': a // b if b else 0}
            answer = ops.get(op, a + b)
            logger.info("AAI math CAPTCHA: %s → answer=%d", text, answer)
            return str(answer)
    logger.warning("AAI CAPTCHA label not found")
    return ""


async def _scrape_aai(max_retries: int = 6) -> list[dict]:
    records: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto(AAI_NIT_URL, timeout=30_000, wait_until="networkidle")
        await page.wait_for_timeout(2_000)

        # Set date range — last 90 days to today
        import datetime
        today = datetime.date.today()
        start_d = today - datetime.timedelta(days=90)
        start_str = start_d.strftime("%Y-%m-%d")
        end_str   = today.strftime("%Y-%m-%d")

        # Fill start date
        start_input = await page.query_selector("input[name='field_document_date_value[value][date]'], input#edit-field-document-date-value-value-date")
        if start_input:
            await start_input.fill(start_str)
        end_input = await page.query_selector("input[name='field_document_date_value_1[value][date]'], input#edit-field-document-date-value-1-value-date")
        if end_input:
            await end_input.fill(end_str)

        # Solve math CAPTCHA and submit
        solved = False
        for attempt in range(1, max_retries + 1):
            cap_text = await _get_aai_captcha(page)
            if not cap_text:
                logger.warning("AAI CAPTCHA not found (attempt %d)", attempt)
                await page.reload()
                await page.wait_for_timeout(2_000)
                # Re-fill dates after reload
                start_input = await page.query_selector("input[name='field_document_date_value[value][date]']")
                if start_input:
                    await start_input.fill(start_str)
                end_input = await page.query_selector("input[name='field_document_date_value_1[value][date]']")
                if end_input:
                    await end_input.fill(end_str)
                continue

            logger.info("AAI CAPTCHA attempt %d: answer=%s", attempt, cap_text)
            cap_input = await page.query_selector("input[name='captcha_response'], input#edit-captcha-response")
            if not cap_input:
                logger.error("AAI CAPTCHA input not found")
                break
            await cap_input.fill(cap_text)
            await page.wait_for_timeout(300)

            submit_btn = await page.query_selector("input#edit-submit-tender-nit, input[name='op'][value='Apply'], input[type='submit']")
            if submit_btn:
                await submit_btn.scroll_into_view_if_needed()
                await submit_btn.click(force=True)
            else:
                await cap_input.press("Enter")

            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            await page.wait_for_timeout(2_000)

            page_text = await page.inner_text("body")
            if "wrong" in page_text.lower() and "captcha" in page_text.lower():
                logger.warning("AAI CAPTCHA rejected (attempt %d)", attempt)
                continue

            rows = await page.query_selector_all("table tr, .views-row, .view-content .node, .views-table tr")
            if len(rows) > 1:
                solved = True
                logger.info("AAI CAPTCHA accepted (attempt %d), found %d rows", attempt, len(rows))
                break

            logger.warning("AAI: no results visible (attempt %d) — body: %s", attempt, page_text[:200])

        if not solved:
            logger.error("AAI CAPTCHA solving failed — aborting")
            await browser.close()
            return []

        # Parse results and paginate
        page_num = 1
        while True:
            rows = await page.query_selector_all("table tr")
            new_count = 0
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 2:
                    continue
                cell_texts = [(await c.inner_text()).strip() for c in cells]
                tender_no = cell_texts[0] if cell_texts else ""
                title     = cell_texts[1] if len(cell_texts) > 1 else ""
                date_str  = cell_texts[2] if len(cell_texts) > 2 else ""
                close_str = cell_texts[3] if len(cell_texts) > 3 else ""

                if not title or len(title) < 5 or tender_no.lower() in ("nit no", "tender no", "s.no"):
                    continue

                rec = _make_record(
                    source="AAI",
                    tender_id=re.sub(r"\s+", "-", tender_no or title[:40]),
                    title=title,
                    department="AAI / Airports Authority of India",
                    state="Central (National)",
                    start_date=date_str,
                    end_date=close_str,
                    url=AAI_NIT_URL,
                )
                records.append(rec)
                new_count += 1

            logger.info("AAI page %d: %d new tenders (total %d)", page_num, new_count, len(records))

            next_link = await page.query_selector("a:has-text('Next '), a[title='Go to next page'], li.pager-next a")
            if not next_link:
                break
            await next_link.click(force=True)
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            await page.wait_for_timeout(2_000)
            page_num += 1
            if page_num > 100:
                break

        await browser.close()
    logger.info("AAI: scraped %d total tenders", len(records))
    return records


def scrape_aai(conn=None) -> list[dict]:
    records = asyncio.run(_scrape_aai())
    if not records:
        return []
    if conn is None:
        conn = get_db()
    saved = upsert(conn, records)
    log_health(conn, source="AAI", domain="aai.aero",
               status="ok", records_fetched=len(records))
    logger.info("AAI: saved %d / %d records", saved, len(records))
    return records


# ---------------------------------------------------------------------------
# 4. BHEL — Bharat Heavy Electricals Ltd
#    Public HTML table at bhel.com/tenders (no pagination, ~5-10 tenders)
# ---------------------------------------------------------------------------

BHEL_URL = "https://www.bhel.com/tenders"


async def _scrape_bhel() -> list[dict]:
    records: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(BHEL_URL, timeout=25_000, wait_until="networkidle")
            await page.wait_for_timeout(2_000)
            rows = await page.query_selector_all("table tr")
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 3:
                    continue
                cell_texts = [(await c.inner_text()).strip() for c in cells]
                # Columns: Tender NIT No | Notification No | Description | Date | Unit | Opening | Closing
                full_text = " ".join(cell_texts)
                # Extract NIT number
                nit_m = re.search(r"Tender\s+NIT\s+Number\s*[:\-]?\s*(\d+)", full_text, re.IGNORECASE)
                nit_no = nit_m.group(1) if nit_m else cell_texts[0]
                # Extract title/description
                desc_m = re.search(r"Tender\s+Description\s*[:\-]?\s*(.+?)(?=Date|Unit|$)", full_text, re.IGNORECASE | re.DOTALL)
                title = desc_m.group(1).strip()[:300] if desc_m else cell_texts[2] if len(cell_texts) > 2 else full_text[:200]

                if not title or len(title) < 5:
                    continue

                rec = _make_record(
                    source="BHEL",
                    tender_id=str(nit_no),
                    title=title,
                    department="BHEL / Bharat Heavy Electricals Ltd",
                    state="Central (National)",
                    url=BHEL_URL,
                )
                records.append(rec)
        except Exception as e:
            logger.error("BHEL scrape error: %s", e)
        finally:
            await browser.close()
    logger.info("BHEL: scraped %d tenders", len(records))
    return records


def scrape_bhel(conn=None) -> list[dict]:
    records = asyncio.run(_scrape_bhel())
    if not records:
        return []
    if conn is None:
        conn = get_db()
    saved = upsert(conn, records)
    log_health(conn, source="BHEL", domain="bhel.com",
               status="ok", records_fetched=len(records))
    logger.info("BHEL: saved %d / %d records", saved, len(records))
    return records


# ---------------------------------------------------------------------------
# Convenience: run all PSU scrapers
# ---------------------------------------------------------------------------

def scrape_all_psu(conn=None) -> dict:
    if conn is None:
        conn = get_db()
    results = {}
    for name, fn in [
        ("MSEDCL",      scrape_msedcl),
        ("Chennai-Port", scrape_chennai_port),
        ("BHEL",        scrape_bhel),
        ("AAI",         scrape_aai),
    ]:
        try:
            recs = fn(conn=conn)
            results[name] = len(recs)
            logger.info("%s: %d records", name, len(recs))
        except Exception as e:
            logger.error("%s failed: %s", name, e)
            results[name] = 0
    return results
