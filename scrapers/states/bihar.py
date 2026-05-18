"""Bihar EPS v2 portal scraper."""

import sqlite3
import logging

from config.portals import BIHAR_EPSV2_BASE
from services.classifier import make_record, extract_date
from repository.db import log_health

logger = logging.getLogger(__name__)

NAV_TIMEOUT = 30_000


def scrape_bihar_epsv2(max_pages: int, headless: bool, conn: sqlite3.Connection = None) -> list:
    """
    Scrape Bihar EPS Version 2 e-Procurement portal.
    URL  : https://eproc2.bihar.gov.in/EPSV2Web/openarea/tenderListingPage.action
    Tech : AngularJS + Bootstrap nav-tabs.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    records      = []
    source_label = "EPSV2/Bihar"
    seen_ids: set = set()

    logger.info("[EPSV2] Starting Bihar EPS v2 scrape (max %d 'More' clicks per tab)", max_pages)

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
            page.goto(BIHAR_EPSV2_BASE, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            page.wait_for_timeout(5000)
            logger.info("[EPSV2] Page loaded: %s", page.title())

            tab_els = page.query_selector_all(".nav-tabs a")
            if tab_els:
                tabs = []
                for el in tab_els:
                    href = (el.get_attribute("href") or "").lstrip("#")
                    label = el.inner_text().strip()
                    tabs.append((href, label, el))
                logger.info("[EPSV2] Found %d tabs: %s", len(tabs), [lb for _, lb, _ in tabs])
            else:
                tabs = [("", "default", None)]
                logger.info("[EPSV2] .nav-tabs not found — scraping visible content")

            for pane_id, label, tab_el in tabs:
                logger.info("[EPSV2] → Tab: %s (#%s)", label, pane_id)

                pane_el   = page.query_selector(f"#{pane_id}") if pane_id else None
                is_active = False
                if pane_el:
                    css_classes = (pane_el.get_attribute("class") or "").split()
                    is_active   = "active" in css_classes

                if not is_active and tab_el is not None:
                    try:
                        tab_el.scroll_into_view_if_needed()
                        tab_el.click()
                        page.wait_for_timeout(3000)
                    except Exception as exc:
                        logger.warning("[EPSV2] Tab click failed (%s): %s", label, exc)

                row_sel = f"#{pane_id} table tr" if pane_id else "table tr"

                for click_num in range(max_pages):
                    rows = page.query_selector_all(row_sel)
                    data_rows = rows[1:] if len(rows) > 1 else []

                    new_count = 0
                    for row in data_rows:
                        cells = row.query_selector_all("td")
                        if len(cells) < 5:
                            continue
                        texts = [c.inner_text().strip() for c in cells]

                        tender_id = texts[1] if len(texts) > 1 else texts[0]
                        if not tender_id or tender_id in seen_ids:
                            continue
                        seen_ids.add(tender_id)

                        title  = texts[2] if len(texts) > 2 else texts[0]
                        dept   = texts[4] if len(texts) > 4 else "Bihar Government"
                        end_dt = texts[5] if len(texts) > 5 else ""

                        records.append(make_record(
                            tender_id  = tender_id[:120],
                            title      = title[:300],
                            department = dept[:200],
                            amount_str = "0",
                            state      = "Bihar",
                            source     = source_label,
                            source_url = BIHAR_EPSV2_BASE,
                            start_date = "",
                            end_date   = extract_date(end_dt) or "",
                        ))
                        new_count += 1

                    logger.info("[EPSV2] %s click#%d → %d new records (total %d)",
                                label, click_num + 1, new_count, len(records))

                    if new_count == 0 and click_num > 0:
                        break

                    more_sel  = f"#{pane_id} a[title='More Tenders']" if pane_id \
                                else "a[title='More Tenders']"
                    more_btn  = page.query_selector(more_sel)
                    if not more_btn:
                        more_btn = page.query_selector(
                            f"#{pane_id} a:has-text('More')" if pane_id else "a:has-text('More')"
                        )
                    if not more_btn:
                        break
                    try:
                        more_btn.scroll_into_view_if_needed()
                        more_btn.click()
                        page.wait_for_timeout(2000)
                    except Exception:
                        break

            if conn is not None:
                log_health(conn, source_label, BIHAR_EPSV2_BASE, "success",
                           records_fetched=len(records))

        except PWTimeout as e:
            logger.warning("[EPSV2] Navigation timeout — portal may be slow or down")
            if conn is not None:
                log_health(conn, source_label, BIHAR_EPSV2_BASE, "failed",
                           error_code="TIMEOUT", error_msg=str(e))
        except Exception as e:
            logger.warning("[EPSV2] Unexpected error: %s", e)
            if conn is not None:
                log_health(conn, source_label, BIHAR_EPSV2_BASE, "failed",
                           error_code=type(e).__name__, error_msg=str(e))
        finally:
            browser.close()

    logger.info("[EPSV2] Total scraped: %d (across all tabs)", len(records))
    return records
