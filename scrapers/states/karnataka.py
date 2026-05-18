"""Karnataka eProcurement portal scraper."""

import re
import sqlite3
import logging
import hashlib
from datetime import datetime

from services.classifier import classify_sector
from repository.db import upsert

logger = logging.getLogger(__name__)


def scrape_karnataka(conn: sqlite3.Connection = None, headless: bool = True) -> list:
    """
    Karnataka eProcurement (JBoss Seam / Ajax4JSF).
    Uses Playwright to iterate all 353 departments via the search form.
    No CAPTCHA on the public listing page.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    from bs4 import BeautifulSoup as BS

    BASE     = "https://eproc.karnataka.gov.in"
    LIST_URL = f"{BASE}/eprocurement/common/eproc_tenders_list.seam"

    if conn is None:
        from repository.db import get_db
        conn = get_db()

    all_records: list = []
    seen_ids:    set  = set()

    def _parse_row(row_el, dept_label):
        html  = row_el.inner_html()
        soup  = BS(html, "lxml")
        cells = soup.find_all("td")
        if len(cells) < 4:
            return None
        texts = [c.get_text(" ", strip=True) for c in cells]

        # Extract tender reference number and title
        tid   = None
        title = None
        close_raw = None

        for t in texts:
            if re.match(r"\d{4}[-_/]\S+", t) and tid is None:
                tid = t
            elif len(t) > 20 and title is None:
                title = t
            if re.search(r"\d{2}/\d{2}/\d{4}", t) and close_raw is None:
                close_raw = t

        # Fallback: use onclick tenderId
        m = re.search(r"tenderId=(\w+)", html)
        if m and not tid:
            tid = f"KA_{m.group(1)}"

        if not title:
            return None
        if not tid:
            tid = "KA_" + hashlib.md5(title.encode()).hexdigest()[:10]
        if tid in seen_ids:
            return None
        seen_ids.add(tid)

        close_dt = None
        if close_raw:
            for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
                try:
                    close_dt = datetime.strptime(close_raw.strip()[:10], fmt)
                    break
                except ValueError:
                    pass

        return {
            "tender_id":        tid,
            "title":            title,
            "sector":           classify_sector(title, dept_label),
            "department":       dept_label,
            "state":            "Karnataka",
            "district":         "Unknown",
            "block":            "Unknown",
            "allocated_amount": 0.0,
            "latitude":         None,
            "longitude":        None,
            "status":           "Active",
            "source":           f"KA/{dept_label[:12].upper().replace(' ','')}",
            "source_url":       LIST_URL,
            "contractor_name":  None,
            "start_date":       None,
            "end_date":         close_dt.isoformat() if close_dt else None,
            "scraped_at":       datetime.now().isoformat(timespec="seconds"),
        }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx     = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        page = ctx.new_page()
        page.set_default_timeout(60_000)

        try:
            page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3000)

            logger.info("[KA] Searching all active tenders (no dept filter)")

            # Click Search with empty dept filter to get all active tenders
            page.click("input[name='eprocTenders:butSearch']")
            page.wait_for_timeout(4000)

            # Set DataTable page size to 50
            try:
                for sel in ["select[name*='Length']", "select[name*='length']"]:
                    el = page.query_selector(sel)
                    if el:
                        page.select_option(sel, "50")
                        page.wait_for_timeout(2000)
                        break
            except Exception:
                pass

            page_num = 1
            consecutive_empty = 0
            while page_num <= 300:
                rows = page.query_selector_all("table tr")
                batch = []
                for row in rows:
                    rec = _parse_row(row, "Karnataka")
                    if rec:
                        batch.append(rec)
                        all_records.append(rec)

                if batch:
                    logger.info("[KA] Page %d: %d records", page_num, len(batch))
                    upsert(conn, batch)
                    consecutive_empty = 0
                else:
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        break

                # Click DataTable Next
                try:
                    next_btn = page.query_selector(
                        "a.paginate_button.next:not(.disabled), "
                        "#eprocTendersTab_next:not(.disabled)"
                    )
                    if next_btn:
                        cls = next_btn.get_attribute("class") or ""
                        if "disabled" in cls:
                            break
                        next_btn.click()
                        page.wait_for_timeout(1500)
                        page_num += 1
                    else:
                        break
                except Exception:
                    break

        except Exception as exc:
            logger.warning("[KA] Page load failed: %s", exc)
        finally:
            browser.close()

    # Inline import to avoid circular: scrapers.orchestrator → scrapers.states.karnataka
    from scrapers.orchestrator import geocode_missing_db
    geocode_missing_db(conn)
    logger.info("[KA] Karnataka done — %d total records", len(all_records))
    return all_records
