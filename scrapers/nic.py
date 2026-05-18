"""NIC portal scrapers — CPPP and GePNIC state portals."""

import re
import time
import sqlite3
import logging
from typing import Optional

from config.portals import NIC_PORTALS, GEPNIC_STATES
from services.classifier import classify_sector, parse_amount, extract_date, make_record, extract_state_from_org, _DATE_RE
from repository.db import upsert, log_health

logger = logging.getLogger(__name__)

NAV_TIMEOUT    = 30_000
ACTION_TIMEOUT = 10_000
PAGE_DELAY     = 2.0


def scrape_nic_portal(state_label: str, base_url: str, max_pages: int, headless: bool, conn: sqlite3.Connection = None) -> list:
    """
    Scrape a NIC eProcurement portal (CPPP or state variant).
    NIC portals all share the same HTML structure:
      page=FrontEndLatestActiveTender&service=page
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    records = []
    tender_url = f"{base_url}?page=FrontEndLatestActiveTender&service=page"

    logger.info("[NIC] %s — starting (max %d pages)", state_label, max_pages)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx     = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()
        page.set_default_timeout(NAV_TIMEOUT)

        try:
            page.goto(tender_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            page.wait_for_timeout(2000)

            for pg_num in range(1, max_pages + 1):
                try:
                    page.wait_for_selector("table", timeout=ACTION_TIMEOUT)
                except PWTimeout:
                    logger.warning("[NIC] %s page %d — no table found, stopping", state_label, pg_num)
                    break

                rows = page.query_selector_all("table tr")
                page_count = 0

                for row in rows[1:]:
                    cells = row.query_selector_all("td")
                    if len(cells) < 5:
                        continue

                    texts = [c.inner_text().strip() for c in cells]
                    title_text = max(texts, key=len)
                    ref = next((t for t in texts if re.search(r"NIT|/\d{4}|T-\d|BID", t, re.I)), texts[0])
                    org = next((t for t in texts if any(
                        kw in t.lower() for kw in ["ministry", "department", "division", "circle", "board"]
                    )), state_label)
                    amount_raw = next((t for t in texts if re.search(r"₹|lakh|crore|\d{5,}", t, re.I)), "0")

                    st = extract_state_from_org(org) if state_label == "Central (CPPP)" else state_label

                    date_cells = [t for t in texts if _DATE_RE.search(t)]
                    start_iso  = extract_date(date_cells[0]) if date_cells else ""
                    end_iso    = extract_date(date_cells[-1]) if len(date_cells) > 1 else ""

                    records.append(make_record(
                        tender_id       = ref[:120],
                        title           = title_text[:300],
                        department      = org[:200],
                        amount_str      = amount_raw,
                        state           = st,
                        source          = f"NIC/{state_label}",
                        source_url      = page.url,
                        contractor_name = "",
                        start_date      = start_iso,
                        end_date        = end_iso,
                    ))
                    page_count += 1

                logger.info("[NIC] %s page %d → %d tenders", state_label, pg_num, page_count)

                next_btn = page.query_selector("a:has-text('Next'), a:has-text('>')")
                if not next_btn:
                    logger.info("[NIC] %s — no Next button, done at page %d", state_label, pg_num)
                    break

                try:
                    next_btn.click()
                    page.wait_for_load_state("domcontentloaded")
                    time.sleep(PAGE_DELAY)
                except PWTimeout:
                    logger.warning("[NIC] %s — Next click timeout at page %d", state_label, pg_num)
                    break

            if conn is not None:
                log_health(conn, f"NIC/{state_label}", base_url, "success",
                           records_fetched=len(records))

        except PWTimeout as e:
            logger.warning("[NIC] %s — navigation timeout (portal may be down)", state_label)
            if conn is not None:
                log_health(conn, f"NIC/{state_label}", base_url, "failed",
                           error_code="TIMEOUT", error_msg=str(e))
        except Exception as e:
            logger.warning("[NIC] %s — error: %s", state_label, e)
            if conn is not None:
                log_health(conn, f"NIC/{state_label}", base_url, "failed",
                           error_code=type(e).__name__, error_msg=str(e))
        finally:
            browser.close()

    logger.info("[NIC] %s — total scraped: %d", state_label, len(records))
    return records


def scrape_gepnic_state(
    state_name: str,
    conn: sqlite3.Connection = None,
    skip_existing: bool = True,
) -> list:
    """
    Generic GePNIC NIC state-portal scraper.  Works for any state that uses the
    standard NIC GePNIC platform (identical HTML structure across all states).
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as BS

    base_url = GEPNIC_STATES.get(state_name)
    if not base_url:
        logger.warning("[GEPNIC] Unknown state: %s", state_name)
        return []

    abbrev = "".join(w[0] for w in state_name.split())
    source_prefix = f"ET{abbrev}"

    H = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0"}

    _DATE_BLOCK = re.compile(
        r'(\d{2}-\w{3}-\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)'
        r'[\s\S]{0,200}?'
        r'(\d{2}-\w{3}-\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)'
        r'[\s\S]{0,200}?'
        r'\[([^\]]{3,350})\]'
        r'\s*\[([^\]]*)\]'
        r'\s*\[(\d{4}_[A-Z_0-9]+)\]'
        r'[\s\S]{0,30}?([A-Za-z][^\n\[]{3,250})',
    )

    records:  list = []
    seen_ids: set  = set()

    existing_ids: set = set()
    if conn and skip_existing:
        existing_ids = {
            row[0] for row in conn.execute(
                "SELECT tender_id FROM tenders WHERE source LIKE ?", (f"{source_prefix}%",)
            ).fetchall()
        }

    sess = _req.Session()
    sess.headers.update(H)
    sess.verify = False

    logger.info("[GEPNIC:%s] Connecting to %s", state_name, base_url)
    try:
        r = sess.get(
            f"{base_url}?page=FrontEndTendersByOrganisation&service=page",
            timeout=30
        )
        r.raise_for_status()
    except Exception as exc:
        logger.warning("[GEPNIC:%s] Org listing failed: %s", state_name, exc)
        return records

    soup = BS(r.text, "lxml")
    org_list: list = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) == 3 and cells[0].get_text(strip=True).isdigit() and cells[2].get_text(strip=True).isdigit():
            a = row.find("a", href=True)
            if a:
                org_list.append((
                    cells[1].get_text(strip=True),
                    int(cells[2].get_text(strip=True)),
                    base_url + a["href"][a["href"].find("?"):],
                ))

    logger.info("[GEPNIC:%s] %d organisations, ~%d total active tenders",
                state_name, len(org_list), sum(c for _, c, _ in org_list))

    for org_name, expected_count, org_url in org_list:
        safe_org = re.sub(r"[^a-zA-Z0-9]", "", org_name)[:12].upper()
        source_label = f"{source_prefix}/{safe_org}"

        try:
            r2 = sess.get(org_url, timeout=60)
            r2.raise_for_status()
        except Exception as exc:
            logger.warning("[GEPNIC:%s] %s fetch failed: %s", state_name, org_name, exc)
            continue

        page_text = BS(r2.text, "lxml").get_text(" ", strip=True)
        org_new = 0

        for m in _DATE_BLOCK.finditer(page_text):
            pub_raw, close_raw, title, ref_no, tender_id, org_chain = m.groups()

            tid_key = f"{source_prefix}-{tender_id}"
            if tid_key in seen_ids or tid_key in existing_ids:
                continue
            seen_ids.add(tid_key)

            clean_title = re.sub(r'\s+', ' ', title).strip()[:300]
            clean_dept  = re.sub(r'\s+', ' ', org_chain.split("||")[0]).strip()[:150]

            def _gepnic_date(raw: str) -> str:
                m2 = re.match(r'(\d{2})-(\w{3})-(\d{4})', raw.strip())
                if not m2:
                    return ""
                _MON = {"Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
                        "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12"}
                d, mon, y = m2.groups()
                return f"{y}-{_MON.get(mon,'01')}-{d.zfill(2)}"

            rec = make_record(
                tender_id  = tid_key[:120],
                title      = clean_title,
                department = clean_dept or org_name,
                amount_str = "0",
                state      = state_name,
                source     = source_label,
                source_url = f"{base_url}?page=FrontEndTendersByOrganisation&service=page",
                start_date = _gepnic_date(pub_raw),
                end_date   = _gepnic_date(close_raw),
            )
            records.append(rec)
            org_new += 1

        if org_new:
            logger.info("[GEPNIC:%s] %-45s %4d new records", state_name, org_name[:45], org_new)

        if conn and records:
            upsert(conn, records)
            records = []

    if conn:
        log_health(conn, f"GEPNIC/{state_name}", base_url, "success",
                   records_fetched=len(seen_ids))
        # Avoid circular import — import inline
        from scrapers.orchestrator import geocode_missing_db
        geocode_missing_db(conn)

    logger.info("[GEPNIC:%s] Done — %d new records", state_name, len(seen_ids))
    return records
