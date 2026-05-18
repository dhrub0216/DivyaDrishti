"""Chhattisgarh CHEPS e-Procurement portal scraper."""

import re
import time
import sqlite3
import logging

from config.portals import CGSTATE_CHEPS_URL
from services.classifier import make_record, extract_date, _DATE_RE
from repository.db import log_health

logger = logging.getLogger(__name__)

NAV_TIMEOUT    = 30_000
ACTION_TIMEOUT = 10_000
PAGE_DELAY     = 2.0


def scrape_cgstate_cheps(max_pages: int, headless: bool, conn: sqlite3.Connection = None) -> list:
    """
    Scrape Chhattisgarh CHEPS e-Procurement portal.

    URL  : https://eproc.cgstate.gov.in/CHEPS/business/getOpenRfqListAction.do
    Tech : Java Struts (.do actions) — different HTML structure from NIC GePNIC.
           Data is rendered in an HTML table; pagination via "Next" button or
           URL param ?pageNo=N (Struts standard).

    Extracts: RFQ reference, title, department, estimated value, dates.
    All records are tagged state="Chhattisgarh".
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    records      = []
    source_label = "CHEPS/Chhattisgarh"

    logger.info("[CHEPS] Starting Chhattisgarh CHEPS scrape (max %d pages)", max_pages)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.set_default_timeout(NAV_TIMEOUT)

        try:
            page.goto(CGSTATE_CHEPS_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            page.wait_for_timeout(3000)   # Struts apps render slower than NIC

            for pg_num in range(1, max_pages + 1):
                # Wait for a table to appear on the page
                try:
                    page.wait_for_selector("table", timeout=ACTION_TIMEOUT)
                except PWTimeout:
                    logger.warning("[CHEPS] Page %d — no table found, stopping", pg_num)
                    break

                # Try several CSS selectors; Java Struts portals vary in class names
                rows = []
                for selector in [
                    "table.list tr",
                    "table.rfqList tr",
                    "table.dataTable tr",
                    "table.tablestyle tr",
                    "table.listTable tr",
                    "table tr",           # broadest fallback
                ]:
                    rows = page.query_selector_all(selector)
                    if len(rows) > 1:    # >1 means at least one data row beyond header
                        break

                page_count = 0
                for row in rows[1:]:    # skip header row
                    cells = row.query_selector_all("td")
                    if len(cells) < 3:
                        continue

                    texts = [c.inner_text().strip() for c in cells]
                    texts = [t for t in texts if t]   # drop empty cells
                    if not texts:
                        continue

                    # Flexible field extraction (same strategy as NIC scraper)
                    title_text = max(texts, key=len)

                    # RFQ / reference number: cell containing RFQ pattern or year
                    ref = next(
                        (t for t in texts if re.search(r"RFQ|rfq|NIT|/\d{4}|BID|\bT[-/]\d", t, re.I)),
                        texts[0],
                    )

                    # Department / organisation cell
                    org = next(
                        (t for t in texts if any(
                            kw in t.lower() for kw in [
                                "department", "directorate", "division", "board",
                                "ministry", "office", "corporation", "authority",
                                "samiti", "nigam", "mandal", "vibhag",
                            ]
                        )),
                        "Chhattisgarh Government",
                    )

                    # Amount
                    amount_raw = next(
                        (t for t in texts if re.search(r"₹|lakh|crore|\d{5,}", t, re.I)),
                        "0",
                    )

                    # Dates
                    date_cells = [t for t in texts if _DATE_RE.search(t)]
                    start_iso  = extract_date(date_cells[0])  if date_cells         else None
                    end_iso    = extract_date(date_cells[-1]) if len(date_cells) > 1 else None

                    records.append(make_record(
                        tender_id       = ref[:120],
                        title           = title_text[:300],
                        department      = org[:200],
                        amount_str      = amount_raw,
                        state           = "Chhattisgarh",
                        source          = source_label,
                        source_url      = page.url,
                        start_date      = start_iso or "",
                        end_date        = end_iso   or "",
                    ))
                    page_count += 1

                logger.info("[CHEPS] Page %d → %d records", pg_num, page_count)

                # Pagination
                # Strategy 1: visible "Next" button / link
                next_btn = page.query_selector(
                    "a:has-text('Next'), a:has-text('>'), "
                    "input[value='Next'], button:has-text('Next'), "
                    "a:has-text('next'), a[title='Next Page']"
                )
                if next_btn:
                    try:
                        next_btn.click()
                        page.wait_for_load_state("domcontentloaded")
                        time.sleep(PAGE_DELAY)
                        continue
                    except PWTimeout:
                        logger.warning("[CHEPS] Next-button click timeout at page %d", pg_num)
                        break

                # Strategy 2: Struts URL-param pagination (?pageNo=N or ?currentPage=N)
                navigated = False
                for param in ("pageNo", "currentPage", "page"):
                    next_url = f"{CGSTATE_CHEPS_URL}?{param}={pg_num + 1}"
                    try:
                        page.goto(next_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
                        page.wait_for_timeout(2000)
                        # Detect empty / unchanged page (no data rows = end of list)
                        probe_rows = page.query_selector_all("table tr")
                        if len(probe_rows) > 1:
                            navigated = True
                            break
                    except PWTimeout:
                        pass

                if not navigated:
                    logger.info("[CHEPS] Pagination exhausted at page %d", pg_num)
                    break

            if conn is not None:
                log_health(conn, source_label, CGSTATE_CHEPS_URL, "success",
                           records_fetched=len(records))

        except PWTimeout as e:
            logger.warning("[CHEPS] Navigation timeout — portal may be down or slow")
            if conn is not None:
                log_health(conn, source_label, CGSTATE_CHEPS_URL, "failed",
                           error_code="TIMEOUT", error_msg=str(e))
        except Exception as e:
            logger.warning("[CHEPS] Unexpected error: %s", e)
            if conn is not None:
                log_health(conn, source_label, CGSTATE_CHEPS_URL, "failed",
                           error_code=type(e).__name__, error_msg=str(e))
        finally:
            browser.close()

    logger.info("[CHEPS] Total scraped: %d", len(records))
    return records
