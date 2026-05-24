"""Deep-scrape enrichment functions for Bihar EPSV2 and UP Jal Nigam tenders."""

import re
import sqlite3
import time
import logging

from repository.db import get_db

logger = logging.getLogger(__name__)


def _db_retry(fn, *args, retries=8, base_delay=1.0):
    for attempt in range(retries):
        try:
            return fn(*args)
        except sqlite3.OperationalError as exc:
            if 'locked' not in str(exc) or attempt == retries - 1:
                raise
            wait = base_delay * (2 ** attempt)
            logger.warning("[DEEP] DB locked — retry %d/%d in %.0fs", attempt + 1, retries, wait)
            time.sleep(wait)

NAV_TIMEOUT = 30_000


def deep_scrape_bihar_epsv2(headless: bool = True) -> dict:
    """
    Enrich all Bihar EPSV2 tenders in the DB with:
      - allocated_amount  (from API field pacamtAsString)
      - contractor_name   (from tenderPreviewMap.invitedVendors, for awarded tenders)
      - start_date        (from publishdate epoch-ms field)

    Strategy — avoids 633 individual page clicks:
      1. One Playwright browser load captures the JWT Bearer token + the full
         tender listing (911 entries) which maps display-ID → internal system ID.
      2. Browser closes. All remaining calls use requests + JWT (no browser).
      3. For each Bihar tender in DB, call:
           POST /rest/tender/previewTenderByTenderId?tenderId={internal_id}
         to get pacamtAsString, publishdate, and invitedVendors.
      4. UPDATE tenders SET allocated_amount=…, contractor_name=…, start_date=…
         WHERE tender_id=… AND state='Bihar'
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    from datetime import datetime, timezone

    BASE       = "https://eproc2.bihar.gov.in/EPSV2Web"
    LIST_URL   = f"{BASE}/openarea/tenderListingPage.action"
    DETAIL_URL = f"{BASE}/rest/tender/previewTenderByTenderId"
    source_label = "EPSV2/Bihar"

    logger.info("[BIHAR-DEEP] Starting Bihar EPSV2 deep detail scrape")

    # Step 1: One browser load to grab JWT + full listing
    captured: dict = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page    = browser.new_page()

        def _on_req(req):
            if "rest/" in req.url:
                auth = req.headers.get("authorization", "")
                if auth and "jwt" not in captured:
                    captured["jwt"]      = auth
                    captured["post_body"] = req.post_data or ""

        def _on_resp(resp):
            if "getTenderList" in resp.url:
                try:
                    captured["tender_list"] = resp.json()
                except Exception:
                    pass

        page.on("request",  _on_req)
        page.on("response", _on_resp)

        try:
            page.goto(LIST_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            page.wait_for_timeout(8000)
            # Trigger the auth'd API calls by clicking the first View button
            btn = page.query_selector("#latestTenders button[ng-click*='previewTender']")
            if btn:
                btn.click()
                page.wait_for_timeout(3000)
        except PWTimeout:
            logger.warning("[BIHAR-DEEP] Page load timeout")
        finally:
            browser.close()

    jwt         = captured.get("jwt", "")
    tender_list = captured.get("tender_list", [])

    if not jwt:
        logger.error("[BIHAR-DEEP] Could not capture JWT — aborting")
        return {"updated": 0, "failed": 0, "skipped": 0}

    logger.info("[BIHAR-DEEP] JWT captured. Tender listing: %d entries", len(tender_list))

    # Build display_id (str) → internal system ID mapping
    id_map: dict = {
        str(t.get("currentOrgTenderId", "")): t.get("currenttenderid", 0)
        for t in tender_list
        if t.get("currentOrgTenderId") and t.get("currenttenderid")
    }
    logger.info("[BIHAR-DEEP] ID map: %d display→internal mappings", len(id_map))

    # Step 2: Load all Bihar tender IDs from DB
    conn = get_db()
    db_rows = conn.execute(
        "SELECT tender_id, allocated_amount, contractor_name, start_date "
        "FROM tenders WHERE state='Bihar' AND source=?",
        (source_label,),
    ).fetchall()
    logger.info("[BIHAR-DEEP] Bihar DB rows: %d", len(db_rows))

    # Step 3: Call REST API for each tender
    headers = {
        "Authorization":  jwt,
        "Content-Type":   "application/json",
        "Accept":         "application/json",
        "Referer":        LIST_URL,
        "User-Agent":     "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124.0.0.0",
    }
    sess = _req.Session()
    sess.headers.update(headers)
    sess.verify = False

    stats = {"updated": 0, "failed": 0}

    for row in db_rows:
        display_id  = str(row[0])
        internal_id = id_map.get(display_id, display_id)

        try:
            r = sess.post(f"{DETAIL_URL}?tenderId={internal_id}", timeout=20)
            if r.status_code != 200:
                stats["failed"] += 1
                continue

            d = r.json()

            # Amount
            pac_str    = d.get("pacamtAsString") or d.get("pacamt")
            amount     = float(pac_str) if pac_str else None

            # Start date (publishdate is epoch ms)
            pub_ms     = d.get("publishdate")
            start_iso  = (datetime.fromtimestamp(pub_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                          if pub_ms else None)

            # Contractor — only populated for awarded/past tenders
            tpm        = d.get("tenderPreviewMap") or {}
            vendors    = tpm.get("invitedVendors") or []
            contractor = "; ".join(v.get("vendorOrg", "") for v in vendors if v.get("vendorOrg"))
            contractor = contractor[:300] or None

            conn.execute(
                """UPDATE tenders
                   SET allocated_amount = COALESCE(?, allocated_amount),
                       contractor_name  = COALESCE(?, contractor_name),
                       start_date       = COALESCE(?, start_date)
                   WHERE tender_id = ? AND state = 'Bihar'""",
                (amount, contractor, start_iso, display_id),
            )
            conn.commit()
            stats["updated"] += 1

            if stats["updated"] % 50 == 0:
                logger.info("[BIHAR-DEEP] Progress: %d updated, %d failed",
                            stats["updated"], stats["failed"])

        except Exception as exc:
            logger.warning("[BIHAR-DEEP] Error for tender %s: %s", display_id, exc)
            stats["failed"] += 1

    conn.close()
    logger.info("[BIHAR-DEEP] Done. updated=%d failed=%d",
                stats["updated"], stats["failed"])
    return stats


def deep_scrape_up_tenders(limit: int = 300) -> dict:
    """
    Enrich UP Jal Nigam tenders with allocated_amount extracted from NIT PDFs.

    Strategy:
      1. Load UPJN tenders from DB where allocated_amount is 0 or NULL.
      2. Fetch each tender's detail page to get the PDF link.
      3. Download the PDF and extract the "Estimated cost of work" in Crores.
      4. UPDATE tenders SET allocated_amount=? WHERE tender_id=?

    Rate-limited to ~1 req/sec. Run repeatedly with --up-deep to process all records
    (6,000+ tenders); each run processes `limit` new records.
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as BS
    from pdfminer.high_level import extract_text as pdf_extract
    from io import BytesIO

    UPJN_BASE_URL = "https://jn.upsdc.gov.in"

    def _extract_amount(text: str):
        """Return estimated cost in Crores from NIT PDF text, or None."""
        flat = re.sub(r'\s+', ' ', text)
        # Primary: find Rs + amount + unit near "Estimated cost"
        m = re.search(
            r'[Ee]stimated\s+[Cc]ost[^.]{0,200}?Rs\.?\s*([\d,]+(?:\.\d+)?)\s*(Lacs?|Lakhs?|Crores?)',
            flat, re.I,
        )
        if not m:
            # Fallback: first Rs+Lacs/Crores in the document
            m = re.search(r'Rs\.?\s*([\d,]+(?:\.\d+)?)\s*(Lacs?|Lakhs?|Crores?)', flat, re.I)
        if not m:
            return None
        value = float(m.group(1).replace(',', ''))
        unit  = m.group(2).lower()
        return round(value if 'crore' in unit else value / 100, 4)

    conn  = get_db()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
    except sqlite3.OperationalError:
        pass
    rows  = conn.execute(
        """SELECT tender_id, source_url FROM tenders
           WHERE source = 'Jal Nigam/UP'
             AND (allocated_amount IS NULL OR allocated_amount = 0)
           ORDER BY CAST(SUBSTR(tender_id, 6) AS INTEGER) DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()

    logger.info("[UP-DEEP] %d UPJN tenders need amount enrichment", len(rows))
    if not rows:
        conn.close()
        return {"updated": 0, "failed": 0, "skipped": 0}

    sess = _req.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0"})
    sess.verify = False

    stats = {"updated": 0, "failed": 0, "skipped": 0}

    for tender_id, detail_url in rows:
        try:
            # Step 1: fetch detail page to get PDF link
            r = sess.get(detail_url, timeout=20)
            r.raise_for_status()
            soup = BS(r.text, "lxml")
            pdf_link = ""
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "pdf" in href.lower() or "UploadTender" in href:
                    pdf_link = href if href.startswith("http") else f"{UPJN_BASE_URL}/{href.lstrip('/')}"
                    break

            if not pdf_link:
                stats["skipped"] += 1
                time.sleep(0.5)
                continue

            # Step 2: download PDF
            pr = sess.get(pdf_link, timeout=30)
            pr.raise_for_status()
            if "pdf" not in pr.headers.get("Content-Type", "").lower() and len(pr.content) < 1000:
                stats["skipped"] += 1
                time.sleep(0.5)
                continue

            # Step 3: extract amount
            text   = pdf_extract(BytesIO(pr.content))
            amount = _extract_amount(text)
            if amount is None:
                stats["skipped"] += 1
                time.sleep(1)
                continue

            # Step 4: update DB
            _db_retry(conn.execute,
                      "UPDATE tenders SET allocated_amount = ? WHERE tender_id = ?",
                      (amount, tender_id))
            _db_retry(conn.commit)
            stats["updated"] += 1

            if stats["updated"] % 25 == 0:
                logger.info("[UP-DEEP] Progress: %d updated, %d failed, %d skipped",
                            stats["updated"], stats["failed"], stats["skipped"])
            time.sleep(1)

        except Exception as exc:
            logger.warning("[UP-DEEP] %s — %s", tender_id, exc)
            stats["failed"] += 1
            time.sleep(1)

    conn.close()
    logger.info("[UP-DEEP] Done — updated=%d failed=%d skipped=%d",
                stats["updated"], stats["failed"], stats["skipped"])
    return stats


def deep_scrape_details(limit: int = 100, headless: bool = True) -> dict:
    """
    Visit each tender's detail page and read the FULL contract description,
    then re-classify sector / state / district from the richer text.

    Targets DB rows where district='Unknown' OR sector IN ('Other', 'General').
    For GeM bids the detail URL is the bid number used as path on bidplus;
    for NIC tenders we use the stored source_url.

    Rate-limited (1.5 sec per page) to stay polite to portals.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    from services.classifier import classify_sector_v2, extract_state, extract_district, extract_block

    conn = get_db()
    rows = conn.execute(
        """SELECT tender_id, source, source_url, title, department, state, district, sector
           FROM tenders
           WHERE (district IS NULL OR district = 'Unknown'
                  OR sector IN ('Other', 'General', NULL))
           LIMIT ?""",
        (limit,),
    ).fetchall()

    if not rows:
        logger.info("[DEEP] No rows need deep scraping.")
        conn.close()
        return {"scraped": 0, "updated": 0, "failed": 0}

    logger.info("[DEEP] Will visit %d detail pages (approx %d min @ 1.5 sec/page)",
                len(rows), int(len(rows) * 1.5 / 60) + 1)

    stats = {"scraped": 0, "updated": 0, "failed": 0}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"),
        )
        page = ctx.new_page()
        page.set_default_timeout(20_000)

        for row in rows:
            tender_id = row[0]
            src       = row[1] or ""
            url       = row[2] or ""

            # Build detail URL
            if "GEM" in src:
                clean_id = re.sub(r"^Bid\s*No.?:?\s*", "", tender_id, flags=re.I).strip()
                detail_url = f"https://bidplus.gem.gov.in/showbidDocument/{clean_id}"
            elif url:
                detail_url = url
            else:
                continue

            try:
                page.goto(detail_url, wait_until="domcontentloaded", timeout=20_000)
                page.wait_for_timeout(1500)
                full_text = page.content()
                # Strip HTML for keyword extraction
                plain = re.sub(r"<[^>]+>", " ", full_text)
                plain = re.sub(r"\s+", " ", plain).strip()

                # Apply reclassifier to the much richer text
                title_full = (row[3] or "") + " " + plain[:4000]
                dept_full  = row[4] or ""

                new_sector   = classify_sector_v2(title_full, dept_full)
                new_state    = extract_state(title_full, dept_full) or row[5]
                new_district = extract_district(title_full, dept_full, new_state) or row[6]
                new_block    = extract_block(title_full, dept_full, new_state, new_district)

                if (new_sector != row[7]
                        or new_state != row[5]
                        or new_district != row[6]):
                    conn.execute(
                        """UPDATE tenders
                           SET sector=?, state=?, district=?, block=COALESCE(?, block)
                           WHERE tender_id=?""",
                        (new_sector, new_state, new_district, new_block, tender_id),
                    )
                    stats["updated"] += 1

                stats["scraped"] += 1

                if stats["scraped"] % 20 == 0:
                    conn.commit()
                    logger.info("[DEEP] %d / %d done — %d updated",
                                stats["scraped"], len(rows), stats["updated"])

                time.sleep(1.5)
            except PWTimeout:
                stats["failed"] += 1
            except Exception as e:
                logger.warning("[DEEP] %s — %s", tender_id, e)
                stats["failed"] += 1

        browser.close()

    conn.commit()
    conn.close()
    logger.info("[DEEP] Complete — %s", stats)
    return stats
