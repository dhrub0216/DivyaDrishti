"""Gujarat nProcure portal scraper."""

import re
import sqlite3
import logging
from datetime import datetime

from repository.db import upsert

logger = logging.getLogger(__name__)


def scrape_gujarat(conn: sqlite3.Connection = None, headless: bool = True) -> list:
    """Scrape Gujarat tenders from tender.nprocure.com via Playwright DataTable pagination."""
    import hashlib
    import time as _time
    from bs4 import BeautifulSoup
    from playwright.sync_api import sync_playwright

    BASE_URL = "https://tender.nprocure.com"
    ABBREV = "GJ"
    all_records: list = []

    def _parse_row(row: dict):
        ref_no = row.get("1", "").strip()
        col2 = row.get("2", "")
        if not col2:
            return None
        soup = BeautifulSoup(col2, "html.parser")

        # Tender ID from hidden input
        tid_input = soup.find("input", {"name": "tenderid"})
        if not tid_input:
            return None
        raw_id = tid_input.get("value", "").strip()
        tender_id = f"{ABBREV}_{raw_id}"

        # Department: text of first red span before the form
        dept = ""
        first_span = soup.find("span")
        if first_span:
            form_el = first_span.find("form")
            if form_el:
                form_el.extract()
            dept = first_span.get_text(" ", strip=True)

        # Title: link whose text starts with "Name Of Work" prefix
        title = ""
        for a_tag in soup.find_all("a"):
            txt = a_tag.get_text(" ", strip=True)
            if txt and "Tender Id" not in txt and "Corrigendum" not in txt:
                # Strip label prefix
                title = re.sub(r"^Name Of Work\s*:\s*", "", txt, flags=re.I).strip()
                break

        # Amount: "Estimated Contract Value : 3460456.30"
        amount_cr = None
        m = re.search(r"Estimated Contract Value\s*:\s*([\d,.]+)", col2)
        if m:
            try:
                amount_cr = float(m.group(1).replace(",", "")) / 1_00_00_000
            except ValueError:
                pass

        # Closing date: "Last Date & Time For Submission : 26-05-2026 18:00:00"
        end_date = None
        dm = re.search(r"Last Date.*?:\s*(\d{2}-\d{2}-\d{4})", col2)
        if dm:
            try:
                end_date = datetime.strptime(dm.group(1), "%d-%m-%Y").date().isoformat()
            except ValueError:
                pass

        return {
            "tender_id":        tender_id,
            "title":            title or ref_no,
            "sector":           "Works",
            "department":       dept,
            "state":            "Gujarat",
            "district":         "",
            "block":            "",
            "allocated_amount": amount_cr,
            "latitude":         None,
            "longitude":        None,
            "status":           "active",
            "source":           "nProcure Gujarat",
            "source_url":       f"{BASE_URL}/view-nit-home",
            "contractor_name":  "",
            "start_date":       None,
            "end_date":         end_date,
            "scraped_at":       datetime.now().isoformat(timespec="seconds"),
        }

    captured_batches: list = []

    def _on_response(response):
        if "beforeLoginTenderTableList" in response.url:
            try:
                d = response.json()
                if d.get("data"):
                    captured_batches.append(d["data"])
                    logger.info("[GJ] Page captured: %d rows (server total: %s)",
                                len(d["data"]), d.get("iTotalRecords", "?"))
            except Exception:
                pass

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.on("response", _on_response)

        logger.info("[GJ] Loading nProcure portal...")
        page.goto(BASE_URL, timeout=90_000, wait_until="networkidle")
        _time.sleep(5)  # DataTable init

        # Change page length to 150 via DataTable API
        try:
            page.evaluate("$.fn.dataTable.tables({api: true}).page.len(150).draw()")
            _time.sleep(4)
        except Exception as exc:
            logger.debug("[GJ] length-change failed: %s", exc)

        # Click Next until the <li class="... next ..."> has "disabled" class
        page_num = 0
        while True:
            next_li = page.query_selector("li.paginate_button.next:not(.disabled)")
            if not next_li:
                logger.info("[GJ] No more Next pages after page %d", page_num)
                break
            next_a = next_li.query_selector("a.page-link")
            if next_a:
                next_a.click()
            else:
                next_li.click()
            _time.sleep(3)
            page_num += 1

        browser.close()

    # Parse all captured rows
    for batch in captured_batches:
        for row in batch:
            rec = _parse_row(row)
            if rec:
                all_records.append(rec)

    logger.info("[GJ] Gujarat done — %d total records", len(all_records))

    if conn and all_records:
        upsert(conn, all_records)
        # Inline import to avoid circular dependency
        from scrapers.orchestrator import geocode_missing_db
        geocode_missing_db(conn)

    return all_records
