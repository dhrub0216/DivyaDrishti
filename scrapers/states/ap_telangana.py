"""Andhra Pradesh and Telangana eProcurement portal scrapers."""

import re
import sqlite3
import logging
import datetime as _dt

from services.classifier import classify_sector
from repository.db import upsert

logger = logging.getLogger(__name__)


def scrape_ap_telangana(state: str, conn: sqlite3.Connection = None, headless: bool = True) -> list:
    """
    Andhra Pradesh and Telangana eProcurement (shared Java TMS codebase).
    Uses Playwright — the home page renders tender widgets via JS from commented-out templates.
    AP: tender.apeprocurement.gov.in  |  Telangana: tender.telangana.gov.in
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    from bs4 import BeautifulSoup as BS

    PORTALS = {
        "Andhra Pradesh": "https://tender.apeprocurement.gov.in",
        "Telangana":      "https://tender.telangana.gov.in",
    }
    base_url = PORTALS.get(state)
    if not base_url:
        logger.warning("[AP/TS] Unknown state: %s", state)
        return []

    abbrev = "AP" if "Andhra" in state else "TS"
    if conn is None:
        from repository.db import get_db
        conn = get_db()

    all_records: list = []
    seen_ids:    set  = set()

    # Columns: Dept | Tender ID | Ref No | Category | Title | Est Value | Published | Start | Close | Action
    def _parse_table_rows(page_html):
        recs = []
        soup = BS(page_html, "lxml")
        for table in soup.find_all("table"):
            rows = [r for r in table.find_all("tr") if len(r.find_all("td")) >= 5]
            if len(rows) < 2:
                continue
            for row in rows:
                cols = [c.get_text(" ", strip=True) for c in row.find_all("td")]
                dept  = cols[0] if cols[0] else ""
                tid_s = cols[1].strip() if len(cols) > 1 else ""
                title = cols[4].strip() if len(cols) > 4 else ""
                est_v = cols[5].strip() if len(cols) > 5 else "0"
                close = cols[8].strip() if len(cols) > 8 else ""

                if not title or not tid_s:
                    continue
                tid = f"{abbrev}_{tid_s}"
                if tid in seen_ids:
                    continue
                seen_ids.add(tid)

                end_date = None
                if close:
                    for fmt in ("%d/%m/%Y %I:%M %p", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
                        try:
                            end_date = _dt.datetime.strptime(close[:19], fmt).isoformat(timespec="seconds")
                            break
                        except ValueError:
                            pass

                # Convert estimated value (Rupees) → Crores
                try:
                    amount_cr = float(est_v.replace(",", "")) / 1_00_00_000
                except (ValueError, AttributeError):
                    amount_cr = 0.0

                recs.append({
                    "tender_id":        tid,
                    "title":            title,
                    "sector":           classify_sector(title, dept),
                    "department":       dept,
                    "state":            state,
                    "district":         "Unknown",
                    "block":            "Unknown",
                    "allocated_amount": amount_cr,
                    "latitude":         None,
                    "longitude":        None,
                    "status":           "Active",
                    "source":           f"{abbrev}/PORTAL",
                    "source_url":       base_url,
                    "contractor_name":  None,
                    "start_date":       None,
                    "end_date":         end_date,
                    "scraped_at":       _dt.datetime.now().isoformat(timespec="seconds"),
                })
        return recs

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        page = ctx.new_page()
        page.set_default_timeout(60_000)

        try:
            home_url = f"{base_url}/login.html"
            page.goto(home_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(5000)

            logger.info("[%s] Page loaded: %s", abbrev, page.title())

            # AP portal shows a splash overlay that blocks clicks — dismiss it via JS
            try:
                page.evaluate("""
                    var splash = document.getElementById('splash');
                    if (splash) splash.style.display = 'none';
                    var overlay = document.querySelector('.splash, .loading-overlay, #overlay');
                    if (overlay) overlay.style.display = 'none';
                """)
                page.wait_for_timeout(500)
            except Exception:
                pass

            # Click "View All" — use dispatch_event to bypass any overlay
            clicked = False
            for sel in ["#viewCurrentall", "a[id*='viewCurrentall']", "a.viewCurrentalltabs"]:
                try:
                    btn = page.query_selector(sel)
                    if btn:
                        btn.dispatch_event("click")
                        page.wait_for_timeout(5000)
                        logger.info("[%s] Dispatched click on '%s'", abbrev, sel)
                        clicked = True
                        break
                except Exception as e:
                    logger.warning("[%s] dispatch_event failed (%s): %s", abbrev, sel, e)

            if not clicked:
                try:
                    page.evaluate("""
                        var btn = document.getElementById('viewCurrentall') ||
                                  document.querySelector('.viewCurrentalltabs');
                        if (btn) btn.click();
                    """)
                    page.wait_for_timeout(5000)
                    clicked = True
                    logger.info("[%s] Used inline JS click", abbrev)
                except Exception:
                    pass

            if not clicked:
                logger.warning("[%s] Could not trigger expand link", abbrev)

            # Set DataTable page size to 50
            try:
                for length_sel in ["select[name*='Length']", "select[name*='length']", "select[name*='pageSize']"]:
                    el = page.query_selector(length_sel)
                    if el:
                        page.select_option(length_sel, "50")
                        page.wait_for_timeout(1500)
                        break
            except Exception:
                pass

            page_num = 1
            consecutive_empty = 0
            while page_num <= 200:  # safety cap: 200 pages × 50 = 10,000 max
                html = page.content()
                batch = _parse_table_rows(html)
                if batch:
                    logger.info("[%s] Page %d: %d records", abbrev, page_num, len(batch))
                    all_records.extend(batch)
                    upsert(conn, batch)
                    consecutive_empty = 0
                else:
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        break

                # Click DataTable "Next" button
                try:
                    next_btn = page.query_selector(
                        "a.paginate_button.next:not(.disabled), "
                        "#tenderList_next:not(.disabled), "
                        "li.paginate_button.next:not(.disabled) a"
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
            logger.warning("[%s] Page error: %s", abbrev, exc)
        finally:
            browser.close()

    if all_records:
        upsert(conn, all_records)
        # Inline import to avoid circular dependency
        from scrapers.orchestrator import geocode_missing_db
        geocode_missing_db(conn)

    logger.info("[%s] %s done — %d total records", abbrev, state, len(all_records))
    return all_records
