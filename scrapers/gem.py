"""GeM Bidplus scraper."""

import re
import time
import sqlite3
import logging

from config.portals import GEM_URL
from services.classifier import make_record
from repository.db import log_health

logger = logging.getLogger(__name__)

NAV_TIMEOUT    = 30_000
ACTION_TIMEOUT = 10_000
PAGE_DELAY     = 2.0


def scrape_gem(max_pages: int, headless: bool, conn: sqlite3.Connection = None) -> list:
    """Scrape Government e-Marketplace bid listings."""
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
                try:
                    page.wait_for_selector("[class*='bid'], [class*='card'], table", timeout=ACTION_TIMEOUT)
                except PWTimeout:
                    logger.warning("[GEM] page %d — no bid elements found", pg_num)
                    break

                cards = page.query_selector_all("[class*='bid-list'], [class*='bidCard'], .card")
                if cards:
                    for card in cards:
                        text = card.inner_text()
                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        if len(lines) < 3:
                            continue

                        bid_no = next((l for l in lines if re.search(r"GEM/\d{4}/", l)), "")
                        bid_no = re.search(r"GEM/\d{4}/[\w/]+", bid_no or "")
                        bid_no = bid_no.group(0) if bid_no else (lines[0] if lines else "GEM-UNKNOWN")

                        BID_NO_RE = re.compile(r"^(bid\s*no|gem/\d{4})", re.I)
                        candidates = [l for l in lines if len(l) > 20 and not BID_NO_RE.match(l)]
                        title = candidates[0] if candidates else (lines[1] if len(lines) > 1 else lines[0])

                        ministry = next((l for l in lines if any(
                            kw in l.lower() for kw in ["ministry", "department", "govt"]
                        )), "Government of India")

                        amount_raw = next((l for l in lines if re.search(
                            r"₹|lakh|crore|\d[\d,]{3,}", l, re.I)
                        ), "0")

                        records.append(make_record(
                            tender_id  = bid_no[:120],
                            title      = title[:300],
                            department = ministry[:200],
                            amount_str = amount_raw,
                            state      = "Central (GeM)",
                            source     = "GEM Bidplus",
                            source_url = page.url,
                            status     = "Active",
                        ))
                else:
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
