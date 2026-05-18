"""All Uttar Pradesh portal scrapers."""

import re
import time
import sqlite3
import logging

from config.portals import (
    UPJN_BASE, UPJN_LIST, UPEIDA_BASE, UPEIDA_LIST, UPSBC_LIST,
    PVVNL_LIST, MVVNL_BASE, ETENDER_UP, UPMSC_LIST,
)
from services.classifier import make_record, extract_date
from repository.db import log_health, upsert

logger = logging.getLogger(__name__)


def _upjn_hidden_fields(soup) -> dict:
    """Extract all ASP.NET hidden input fields from a BeautifulSoup page."""
    return {
        inp.get("name") or inp.get("id"): inp.get("value", "")
        for inp in soup.find_all("input", {"type": "hidden"})
        if inp.get("name") or inp.get("id")
    }


def scrape_upjalNigam(max_pages: int, conn: sqlite3.Connection = None) -> list:
    """
    Scrape UP Jal Nigam water-authority tender portal.
    URL  : https://jn.upsdc.gov.in/en/tenders
    Tech : ASP.NET WebForms — pagination via __doPostBack (VIEWSTATE chains per page).
    Volume: ~7,500 tenders with district-level location data.

    Columns scraped (by position):
      [0] Sr.No.  [1] District  [3] Tender No.  [4] Title
      [5] Upload date (start)  [7] Opening date (end)

    No amount or contractor shown on web portal (only in PDF documents).
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as BS

    source_label = "Jal Nigam/UP"
    H = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124.0.0.0",
        "Referer":    UPJN_LIST,
    }

    records:  list = []
    seen_ids: set  = set()

    logger.info("[UPJN] Starting UP Jal Nigam scrape (max %d pages)", max_pages)

    sess = _req.Session()
    sess.headers.update(H)
    sess.verify = False

    def parse_page(soup) -> int:
        """Parse one page of results, return count of new records added."""
        tables = soup.find_all("table")
        data_table = tables[1] if len(tables) > 1 else None
        if not data_table:
            return 0

        rows = data_table.find_all("tr")
        new = 0
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            district = cells[1].get_text(strip=True)
            # Skip pagination rows (ASP.NET GridView embeds pager inside the table)
            # These show as rows with district="1"/"2"/"First"/"Last"/etc.
            if district.isdigit() or district in ("First", "Last", "...", ""):
                continue
            # Tender number and its detail-page link
            tn_cell   = cells[3]
            tn_link   = tn_cell.find("a", href=True)
            tender_no = tn_cell.get_text(strip=True)
            # Extract tenderid from href like ../frmExpandTenderDetails.aspx?tenderid=19076
            tenderid_param = ""
            if tn_link:
                href = tn_link.get("href", "")
                m = re.search(r"tenderid=(\d+)", href, re.I)
                if m:
                    tenderid_param = m.group(1)
            tid = f"UPJN-{tenderid_param}" if tenderid_param else f"UPJN-{tender_no}-{district}"

            if tid in seen_ids:
                continue
            seen_ids.add(tid)

            # Title — strip embedded PDF link text
            title_cell = cells[4]
            title      = title_cell.get_text(" ", strip=True)
            title      = re.sub(r"\[\d+ KB\].*", "", title).strip().strip('"')

            start_raw = cells[5].get_text(strip=True) if len(cells) > 5 else ""
            end_raw   = cells[7].get_text(strip=True) if len(cells) > 7 else ""

            detail_url = (f"{UPJN_BASE}/frmExpandTenderDetails.aspx?tenderid={tenderid_param}"
                          if tenderid_param else UPJN_LIST)

            rec = make_record(
                tender_id  = tid[:120],
                title      = title[:300],
                department = "UP Jal Nigam",
                amount_str = "0",
                state      = "Uttar Pradesh",
                source     = source_label,
                source_url = detail_url,
                start_date = extract_date(start_raw) or "",
                end_date   = extract_date(end_raw)   or "",
            )
            rec["district"] = district[:100]   # make_record() hardcodes "Unknown"; override here
            records.append(rec)
            new += 1
        return new

    try:
        # Page 1 — GET request
        r = sess.get(UPJN_LIST, timeout=30)
        r.raise_for_status()
        soup = BS(r.text, "lxml")
        count = parse_page(soup)
        logger.info("[UPJN] Page 1 → %d records (total %d)", count, len(records))

        # Pages 2..N — ASP.NET postback; VIEWSTATE must come from the previous response
        for pg in range(2, max_pages + 1):
            hidden = _upjn_hidden_fields(soup)
            post_data = {
                **hidden,
                "__EVENTTARGET":   "ctl00$ContentPlaceHolder_Body$gvtender",
                "__EVENTARGUMENT": f"Page${pg}",
            }
            r = sess.post(UPJN_LIST, data=post_data, timeout=30)
            r.raise_for_status()
            soup = BS(r.text, "lxml")
            count = parse_page(soup)
            logger.info("[UPJN] Page %d → %d new records (total %d)", pg, count, len(records))
            if count == 0:
                break   # reached end of data

        if conn is not None:
            log_health(conn, source_label, UPJN_LIST, "success", records_fetched=len(records))

    except Exception as exc:
        logger.warning("[UPJN] Error: %s", exc)
        if conn is not None:
            log_health(conn, source_label, UPJN_LIST, "failed",
                       error_code=type(exc).__name__, error_msg=str(exc))

    logger.info("[UPJN] Total scraped: %d", len(records))
    return records


def scrape_upeida_archive(conn: sqlite3.Connection = None) -> list:
    """
    Scrape UPEIDA (UP Expressways Industrial Development Authority) archive tenders.
    URL    : https://upeida.up.gov.in/en/archivetenders
    Volume : ~28 high-value expressway/infrastructure tenders.
    Tech   : Static HTML table with URL-param pagination (?page=N).
    Note   : Amount and contractor are in PDF documents; not scraped here.
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as BS

    source_label = "UPEIDA/UP"
    H = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0", "Referer": UPEIDA_BASE}

    records:  list = []
    seen_ids: set  = set()

    logger.info("[UPEIDA] Scraping UPEIDA archive tenders")

    sess = _req.Session()
    sess.headers.update(H)
    sess.verify = False

    for pg in range(1, 10):   # max 10 pages; stop on empty
        url = UPEIDA_LIST if pg == 1 else f"{UPEIDA_LIST}?page={pg}"
        try:
            r = sess.get(url, timeout=20)
            r.raise_for_status()
        except Exception as exc:
            logger.warning("[UPEIDA] Page %d error: %s", pg, exc)
            break

        soup = BS(r.text, "lxml")
        tables = soup.find_all("table")
        data_table = tables[1] if len(tables) > 1 else None
        if not data_table:
            break

        rows = data_table.find_all("tr")
        new = 0
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            # Col[0]=S.No, Col[1]=Tender No (PDF link), Col[2]=Title, Col[3]=Upload date
            tn_cell = cells[1]
            tn_link = tn_cell.find("a", href=True)
            tid     = f"UPEIDA-{cells[0].get_text(strip=True)}"
            pdf_url = ""
            if tn_link:
                href    = tn_link.get("href", "")
                pdf_url = href if href.startswith("http") else f"{UPEIDA_BASE}/{href.lstrip('./')}"

            title     = cells[2].get_text(" ", strip=True)[:300] if len(cells) > 2 else "UPEIDA Tender"
            start_raw = cells[3].get_text(strip=True)            if len(cells) > 3 else ""
            end_raw   = cells[4].get_text(strip=True)            if len(cells) > 4 else ""

            if tid in seen_ids:
                continue
            seen_ids.add(tid)

            records.append(make_record(
                tender_id  = tid[:120],
                title      = title,
                department = "UPEIDA",
                amount_str = "0",
                state      = "Uttar Pradesh",
                source     = source_label,
                source_url = pdf_url or UPEIDA_LIST,
                start_date = extract_date(start_raw) or "",
                end_date   = extract_date(end_raw)   or "",
            ))
            new += 1

        logger.info("[UPEIDA] Page %d → %d records", pg, new)
        if new == 0:
            break

    if conn is not None:
        log_health(conn, source_label, UPEIDA_LIST, "success", records_fetched=len(records))

    logger.info("[UPEIDA] Total: %d", len(records))
    return records


def scrape_upsbc(conn: sqlite3.Connection = None) -> list:
    """
    Scrape UPSBC (UP State Bridge Corporation) tender page.
    URL    : https://bridgecorporationltd.com/tender.php
    Volume : ~80 bridge/flyover/culvert tenders, all on a single page.
    Tech   : Static HTML table — no pagination needed.
    Note   : Amount and contractor are in PDF documents; not scraped here.
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as BS

    source_label = "UPSBC/UP"
    H = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0"}

    records: list = []
    logger.info("[UPSBC] Scraping UP State Bridge Corporation tenders")

    try:
        sess = _req.Session()
        sess.headers.update(H)
        sess.verify = False
        r = sess.get(UPSBC_LIST, timeout=20)
        r.raise_for_status()

        soup = BS(r.text, "lxml")
        tables = soup.find_all("table")
        data_table = tables[1] if len(tables) > 1 else tables[0]
        rows = data_table.find_all("tr")

        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            tender_no = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            subject   = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            date_raw  = cells[3].get_text(strip=True) if len(cells) > 3 else ""

            # PDF link in last cell
            pdf_link  = ""
            last_cell = cells[-1]
            link_tag  = last_cell.find("a", href=True)
            if link_tag:
                pdf_link = link_tag["href"] if link_tag["href"].startswith("http") else \
                           "https://bridgecorporationltd.com/" + link_tag["href"].lstrip("/")

            if not subject and not tender_no:
                continue

            tid = f"UPSBC-{re.sub(r'[^a-zA-Z0-9]', '-', tender_no)[:60]}"

            records.append(make_record(
                tender_id  = tid[:120],
                title      = f"{subject} ({tender_no})"[:300] if tender_no else subject[:300],
                department = "UP State Bridge Corporation",
                amount_str = "0",
                state      = "Uttar Pradesh",
                source     = source_label,
                source_url = pdf_link or UPSBC_LIST,
                start_date = extract_date(date_raw) or "",
                end_date   = "",
            ))

        if conn is not None:
            log_health(conn, source_label, UPSBC_LIST, "success", records_fetched=len(records))

        logger.info("[UPSBC] Total: %d", len(records))

    except Exception as exc:
        logger.warning("[UPSBC] Error: %s", exc)
        if conn is not None:
            log_health(conn, source_label, UPSBC_LIST, "failed",
                       error_code=type(exc).__name__, error_msg=str(exc))

    return records


def scrape_etender_up_orgs(conn: sqlite3.Connection = None) -> list:
    """
    Scrape etender.up.nic.in for target UP departments missing from other sources.
    Covers: Health, MSME, Social Welfare, Digital & IT sectors.
    Tech   : Session-based navigation — org listing page → per-dept tender list.
    Volume : ~175+ tenders across target departments.
    Note   : Amounts not shown on listing; set to 0. Tender IDs from portal (2026_DEPT_N_N).
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as BS

    H = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0"}

    # Which org names to scrape and what source label to assign
    TARGET_ORGS = {
        # Health sector
        "National Health Mission UP":                          ("NHM/UP",      "Health"),
        "Director General Medical Health":                     ("DGMH/UP",     "Health"),
        "Director General Medical Education and Training HQ":  ("DMET/UP",     "Health"),
        "Dr. Ram Manohar Lohia Institute of Medical Sciences": ("RMLIMS/UP",   "Health"),
        "Sanjay Gandhi Post Graduate Institute of Medical Sciences Lucknow": ("SGPGI/UP", "Health"),
        # MSME sector
        "Department of MSME And Export Promotion":             ("MSME/UP",     "MSME"),
        "UP Handicraft Development and Marketing Carporation": ("UPHDMC/UP",   "MSME"),
        # Social Welfare
        "Directorate of Social Welfare UP":                    ("SWUP/UP",     "Social Welfare"),
        # Digital & IT
        "UP Development Systems Corporation Ltd":              ("UPDSC/UP",    "Digital & IT"),
        "Remote Sensing Applications Centre UP":               ("RSAC/UP",     "Digital & IT"),
        "Shreetron India Limited":                             ("SHREETRON/UP","Digital & IT"),
    }

    records:  list = []
    seen_ids: set  = set()

    sess = _req.Session()
    sess.headers.update(H)
    sess.verify = False

    logger.info("[ETENDER_UP] Loading organisation list from etender.up.nic.in")
    try:
        r = sess.get(f"{ETENDER_UP}?page=FrontEndTendersByOrganisation&service=page", timeout=25)
        r.raise_for_status()
    except Exception as exc:
        logger.warning("[ETENDER_UP] Org listing failed: %s", exc)
        return records

    soup = BS(r.text, "lxml")
    # Extract org_name → session URL from the 3-column org table
    org_url_map: dict = {}
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) == 3:
            sno, org_name, cnt = [c.get_text(strip=True) for c in cells]
            if sno.isdigit():
                a = row.find("a", href=True)
                if a:
                    org_url_map[org_name] = ETENDER_UP + a["href"].lstrip("/nicgep/app")

    logger.info("[ETENDER_UP] Found %d organisations in listing", len(org_url_map))

    _DATE_BLOCK = re.compile(
        r'(\d{2}-\w{3}-\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)'   # e-Published date
        r'[\s\S]{0,120}?'
        r'(\d{2}-\w{3}-\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)'   # Closing date
        r'[\s\S]{0,60}?'
        r'\[([^\]]{3,300})\]'                               # [Title]
        r'\s*\[([^\]]*)\]'                                  # [Ref No]
        r'\s*\[(\d{4}_[A-Z_0-9]+)\]'                       # [TenderID]
        r'[\s\S]{0,10}?([A-Za-z][^\n\[]{3,200})',          # Org chain (first part)
    )

    for org_name, target in TARGET_ORGS.items():
        source_label, forced_sector = target
        url = org_url_map.get(org_name)
        if not url:
            logger.warning("[ETENDER_UP] Org not found in listing: %s", org_name)
            continue

        try:
            r2 = sess.get(url, timeout=25)
            r2.raise_for_status()
        except Exception as exc:
            logger.warning("[ETENDER_UP] %s fetch failed: %s", org_name, exc)
            continue

        from bs4 import BeautifulSoup as _BS2
        soup2 = _BS2(r2.text, "lxml")
        page_text = soup2.get_text(" ", strip=True)

        count_before = len(records)
        for m in _DATE_BLOCK.finditer(page_text):
            pub_raw, close_raw, title, ref_no, tender_id, org_chain = m.groups()
            if tender_id in seen_ids:
                continue
            seen_ids.add(tender_id)

            clean_title = re.sub(r'\s+', ' ', title).strip()[:300]
            clean_org   = re.sub(r'\s+', ' ', org_chain.split("||")[0]).strip()[:150]

            rec = make_record(
                tender_id  = f"ETUP-{tender_id}"[:120],
                title      = clean_title,
                department = clean_org or org_name,
                amount_str = "0",
                state      = "Uttar Pradesh",
                source     = source_label,
                source_url = f"{ETENDER_UP}?page=FrontEndTendersByOrganisation&service=page",
                start_date = extract_date(pub_raw.split()[0].replace("-", "/")) or "",
                end_date   = extract_date(close_raw.split()[0].replace("-", "/")) or "",
            )
            rec["sector"] = forced_sector
            records.append(rec)

        logger.info("[ETENDER_UP] %s: %d tenders scraped", org_name, len(records) - count_before)

    if conn is not None and records:
        log_health(conn, "ETENDER/UP", ETENDER_UP, "success", records_fetched=len(records))
    logger.info("[ETENDER_UP] Total: %d records", len(records))
    return records


def scrape_upmsc(conn: sqlite3.Connection = None) -> list:
    """
    Scrape UPMSC (UP Medical Supplies Corporation Ltd) tender listing.
    URL    : https://upmsc.in/
    Sector : Health — drugs, equipment, consumables, courier, QC contracts.
    Volume : ~140+ tenders in a single-page HTML table.
    Tech   : Static HTML table; no pagination needed.
    Note   : Tender amounts not shown on listing — set to 0.
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as BS

    source_label = "UPMSC/UP"
    H = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0"}

    records:  list = []
    seen_ids: set  = set()

    logger.info("[UPMSC] Scraping UP Medical Supplies Corporation tenders")

    try:
        r = _req.get(UPMSC_LIST, timeout=25, verify=False, headers=H)
        r.raise_for_status()
        soup = BS(r.text, "lxml")

        tables = soup.find_all("table")
        if not tables:
            logger.warning("[UPMSC] No tables found on page")
            return records

        # First table is the main tender listing
        rows = tables[0].find_all("tr")
        logger.info("[UPMSC] Found %d rows in tender table", len(rows))

        for row in rows[1:]:  # skip header row
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            tender_no   = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            description = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            start_raw   = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            end_raw     = cells[4].get_text(strip=True) if len(cells) > 4 else ""

            if not tender_no and not description:
                continue

            safe_tn = re.sub(r"[^a-zA-Z0-9]", "-", tender_no)[:60]
            tid = f"UPMSC-{safe_tn}"
            if tid in seen_ids:
                continue
            seen_ids.add(tid)

            # PDF link from the tender file cell
            pdf_url = ""
            for cell in cells:
                a = cell.find("a", href=True)
                if a and (".pdf" in a["href"].lower() or "TenderFiles" in a["href"]):
                    href = a["href"].replace("\\", "/")
                    pdf_url = href if href.startswith("http") else f"https://upmsc.in{href}"
                    break

            # Infer sub-sector from tender number (Drugs, Equipment, QC, etc.)
            tn_lower = tender_no.lower()
            if "drug" in tn_lower:
                dept = "UPMSC Drugs Division"
            elif "equip" in tn_lower or "eqp" in tn_lower:
                dept = "UPMSC Equipment Division"
            elif "qc" in tn_lower:
                dept = "UPMSC Quality Control"
            else:
                dept = "UP Medical Supplies Corporation"

            rec = make_record(
                tender_id  = tid[:120],
                title      = description[:300] if description else f"UPMSC Tender {tender_no}",
                department = dept,
                amount_str = "0",
                state      = "Uttar Pradesh",
                source     = source_label,
                source_url = pdf_url or UPMSC_LIST,
                start_date = extract_date(start_raw) or "",
                end_date   = extract_date(end_raw)   or "",
            )
            rec["sector"] = "Health"
            records.append(rec)

        if conn is not None:
            log_health(conn, source_label, UPMSC_LIST, "success", records_fetched=len(records))
        logger.info("[UPMSC] Total: %d records", len(records))

    except Exception as exc:
        logger.warning("[UPMSC] Error: %s", exc)
        if conn is not None:
            log_health(conn, source_label, UPMSC_LIST, "failed",
                       error_code=type(exc).__name__, error_msg=str(exc))

    return records


def scrape_pvvnl(conn: sqlite3.Connection = None) -> list:
    """
    Scrape PVVNL (Paschimanchal Vidyut Vitran Nigam Ltd) — UP Western power distribution.
    URL    : https://pvvnl.org/Tenders-Notice
    Sectors: Energy (power grid works, substation construction, meter supply, etc.)
    Districts covered: Meerut, Agra, Bareilly, Moradabad, Aligarh, Mathura, Saharanpur,
                       Noida, Ghaziabad, Hapur, Muzaffarnagar zones.
    Tech   : Static HTML table, single page, no pagination.
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as BS

    source_label = "PVVNL/UP"
    H = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0"}

    # Issuing authority → district mapping for Western UP zones
    _ZONE_DISTRICT = {
        "HAPUR": "HAPUR", "NOIDA": "GAUTAM BUDDHA NAGAR", "GZB": "GHAZIABAD",
        "GHAZIABAD": "GHAZIABAD", "MEERUT": "MEERUT", "AGRA": "AGRA",
        "ALIGARH": "ALIGARH", "MATHURA": "MATHURA", "BAREILLY": "BAREILLY",
        "MORADABAD": "MORADABAD", "MUZAFFARNAGAR": "MUZAFFARNAGAR",
        "SAHARANPUR": "SAHARANPUR", "BULANDSHAHR": "BULANDSHAHR",
        "RAMPUR": "RAMPUR", "BIJNOR": "BIJNOR", "AMROHA": "AMROHA",
        "LESA": "LUCKNOW",
    }

    def _zone_to_district(authority: str) -> str:
        au = authority.upper()
        for key, dist in _ZONE_DISTRICT.items():
            if key in au:
                return dist
        return ""

    records: list = []
    logger.info("[PVVNL] Scraping UP Western power tenders")

    try:
        sess = _req.Session()
        sess.headers.update(H)
        sess.verify = False
        r = sess.get(PVVNL_LIST, timeout=20)
        r.raise_for_status()

        soup = BS(r.text, "lxml")
        tables = soup.find_all("table")
        if not tables:
            logger.warning("[PVVNL] No tables found")
            return records

        data_table = tables[0]
        rows = data_table.find_all("tr")

        for row in rows[1:]:   # skip header
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            tender_no = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            authority = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            subject   = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            start_raw = cells[5].get_text(strip=True) if len(cells) > 5 else ""
            end_raw   = cells[6].get_text(strip=True) if len(cells) > 6 else ""

            if not subject and not tender_no:
                continue

            district = _zone_to_district(authority)
            tid = f"PVVNL-{re.sub(r'[^a-zA-Z0-9]', '-', tender_no)[:60]}" if tender_no else \
                  f"PVVNL-{re.sub(r'[^a-zA-Z0-9]', '-', subject[:40])}"

            rec = make_record(
                tender_id  = tid[:120],
                title      = f"{subject} — {tender_no}"[:300] if tender_no else subject[:300],
                department = f"PVVNL — {authority}"[:200] if authority else "PVVNL",
                amount_str = "0",
                state      = "Uttar Pradesh",
                source     = source_label,
                source_url = PVVNL_LIST,
                start_date = extract_date(start_raw) or "",
                end_date   = extract_date(end_raw) or "",
            )
            if district:
                rec["district"] = district
            records.append(rec)

        if conn is not None:
            log_health(conn, source_label, PVVNL_LIST, "success", records_fetched=len(records))
        logger.info("[PVVNL] Total: %d", len(records))

    except Exception as exc:
        logger.warning("[PVVNL] Error: %s", exc)
        if conn is not None:
            log_health(conn, source_label, PVVNL_LIST, "failed",
                       error_code=type(exc).__name__, error_msg=str(exc))

    return records


def scrape_mvvnl(years: int = 4, max_pages: int = 30, conn: sqlite3.Connection = None) -> list:
    """
    Scrape MVVNL (Madhyanchal Vidyut Vitran Nigam Ltd) — UP Central/Lucknow power dist.
    URL    : https://mvvnl.in/en/tenders?year=YYYY&display=50
    Sectors: Energy (substations, grid work, cable laying, transformer supply, etc.)
    Districts: Lucknow, Kanpur, Unnao, Hardoi, Sitapur, Lakhimpur Kheri, Barabanki, etc.
    Tech   : ASP.NET WebForms — year + display params bypass pagination without VIEWSTATE.
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as BS
    from datetime import date as _date

    source_label = "MVVNL/UP"
    H = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0"}

    _ZONE_DISTRICT = {
        "LUCKNOW": "LUCKNOW", "LESA": "LUCKNOW", "KANPUR": "KANPUR NAGAR",
        "UNNAO": "UNNAO", "HARDOI": "HARDOI", "SITAPUR": "SITAPUR",
        "LAKHIMPUR": "LAKHIMPUR KHERI", "BARABANKI": "BARABANKI",
        "RAE BARELI": "RAE BARELI", "RAEBARELI": "RAE BARELI",
        "SULTANPUR": "SULTANPUR", "FATEHPUR": "FATEHPUR",
        "BANDA": "BANDA", "JALAUN": "JALAUN",
        "EUCC": "LUCKNOW", "MEDCO": "LUCKNOW",
    }

    def _zone_to_district(authority: str) -> str:
        au = authority.upper()
        for key, dist in _ZONE_DISTRICT.items():
            if key in au:
                return dist
        return ""

    records: list = []
    current_year = _date.today().year
    logger.info("[MVVNL] Scraping UP Central power tenders (last %d years)", years)

    try:
        sess = _req.Session()
        sess.headers.update(H)
        sess.verify = False

        for yr in range(current_year, current_year - years, -1):
            page = 1
            yr_count = 0
            while page <= max_pages:
                url = f"{MVVNL_BASE}?year={yr}&display=50&page={page}"
                try:
                    r = sess.get(url, timeout=20)
                    r.raise_for_status()
                except Exception as e:
                    logger.warning("[MVVNL] Year %d page %d error: %s", yr, page, e)
                    break

                soup = BS(r.text, "lxml")
                tables = soup.find_all("table")
                # Table layout: [0]=filters, [1]=tender data, [2]=pagination
                if len(tables) < 2:
                    break

                data_table = tables[1]
                rows = data_table.find_all("tr")
                rows_on_page = 0

                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) < 4:
                        continue
                    # First cell is S.No (numeric) — skip header rows
                    sno_text = cells[0].get_text(strip=True)
                    if not sno_text.isdigit():
                        continue

                    nit_raw   = cells[1].get_text(separator=" ", strip=True)
                    nit       = re.split(r'\[', nit_raw)[0].strip()
                    date_raw  = cells[2].get_text(strip=True)
                    authority = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                    subject   = cells[4].get_text(strip=True) if len(cells) > 4 else ""

                    if not subject and not nit:
                        continue

                    district = _zone_to_district(authority)
                    tid = f"MVVNL-{re.sub(r'[^a-zA-Z0-9]', '-', nit)[:60]}" if nit else \
                          f"MVVNL-{sno_text}"

                    rec = make_record(
                        tender_id  = tid[:120],
                        title      = f"{subject} — {nit}"[:300] if nit else subject[:300],
                        department = f"MVVNL — {authority}"[:200] if authority else "MVVNL",
                        amount_str = "0",
                        state      = "Uttar Pradesh",
                        source     = source_label,
                        source_url = url,
                        start_date = "",
                        end_date   = extract_date(date_raw) or "",
                    )
                    if district:
                        rec["district"] = district
                    records.append(rec)
                    yr_count += 1
                    rows_on_page += 1

                logger.info("[MVVNL] Year %d page %d → %d tenders", yr, page, rows_on_page)
                if rows_on_page == 0:
                    break
                page += 1

            logger.info("[MVVNL] Year %d total → %d tenders", yr, yr_count)

        if conn is not None:
            log_health(conn, source_label, MVVNL_BASE, "success", records_fetched=len(records))
        logger.info("[MVVNL] Total: %d", len(records))

    except Exception as exc:
        logger.warning("[MVVNL] Error: %s", exc)
        if conn is not None:
            log_health(conn, source_label, MVVNL_BASE, "failed",
                       error_code=type(exc).__name__, error_msg=str(exc))

    return records


def enrich_up_power_amounts(conn: sqlite3.Connection) -> int:
    """
    For PVVNL/MVVNL tenders with no allocated_amount:
      - MVVNL: OCR page 1 of the tender PDF (English, clean text); extract EMD.
      - PVVNL: OCR NIT letter pages; attempt to find EMD numeric values.
    Estimated project cost = EMD / 0.02  (EMD is 2% of estimated cost in GoI procurement).
    Returns count of records updated.
    """
    try:
        from ocrmac.ocrmac import OCR as _AppleOCR
        import fitz as _fitz
    except ImportError:
        logger.warning("[enrich_up_power] ocrmac or pymupdf not installed — pip3 install ocrmac pymupdf")
        return 0

    import requests as _req
    import zipfile as _zf
    import io as _io
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as _BS

    H = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0"}
    # Matches "Rs. 2,65,000" or "Rs.265000" (English-format)
    _RS_PAT = re.compile(r'(?:Rs\.?|S\s*R\s+)([\d,]+(?:\.\d+)?)', re.IGNORECASE)
    # Naked amount: Indian comma-separated numbers ≥5 digits (fallback for Hindi docs)
    _NUM_PAT = re.compile(r'\b(\d[\d,]{4,14})\b')

    def _emd_from_page_image(img_path: str) -> float:
        try:
            res = _AppleOCR(img_path, recognition_level='accurate', language_preference=['en-US'])
            items = res.recognize()   # list of (text, confidence, [x, y, w, h])
        except Exception:
            return 0.0

        rs_amounts: list = []
        naked_nums: list = []
        emd_y = None

        for text, conf, bbox in items:
            if conf < 0.4:
                continue
            tl = text.lower()
            if emd_y is None and 'earnest money' in tl:
                emd_y = bbox[1]
            for m in _RS_PAT.finditer(text):
                try:
                    v = float(m.group(1).replace(',', ''))
                    if v > 500:
                        rs_amounts.append((v, bbox[1]))
                except ValueError:
                    pass
            for m in _NUM_PAT.finditer(text):
                try:
                    v = float(m.group(1).replace(',', ''))
                    if 5_000 <= v <= 50_000_000:
                        naked_nums.append(v)
                except ValueError:
                    pass

        if emd_y is not None and rs_amounts:
            same_line = [amt for amt, y in rs_amounts if abs(y - emd_y) < 0.03]
            if same_line:
                return max(same_line)
        if rs_amounts:
            return max(amt for amt, _ in rs_amounts)
        if naked_nums:
            return max(naked_nums)
        return 0.0

    def _emd_from_pdf(doc, max_pages: int = 4) -> float:
        for i in range(min(max_pages, len(doc))):
            pix = doc[i].get_pixmap(matrix=_fitz.Matrix(250 / 72, 250 / 72))
            path = f"/tmp/_up_enrich_p{i}.png"
            pix.save(path)
            emd = _emd_from_page_image(path)
            if emd > 0:
                return emd
        return 0.0

    cur = conn.cursor()
    updated = 0

    # MVVNL
    mvvnl_rows = cur.execute(
        "SELECT tender_id, title FROM tenders "
        "WHERE source='MVVNL/UP' AND (allocated_amount IS NULL OR allocated_amount=0)"
    ).fetchall()
    logger.info("[enrich_up_power] MVVNL: %d tenders to enrich", len(mvvnl_rows))

    nit_needed = {}
    for tid, title in mvvnl_rows:
        m = re.search(r'—\s*([\w/\-]+)\s*$', title)
        if m:
            nit_needed[m.group(1).strip()] = tid

    mvvnl_pdf_map: dict = {}
    if nit_needed:
        _YEAR_PAT = re.compile(r'(?:^|/)(\d{4})(?:-\d{2})?(?:/|$)')
        years_to_search = set()
        for nit in nit_needed:
            for m in _YEAR_PAT.finditer('/' + nit + '/'):
                yr_val = int(m.group(1))
                if 2000 <= yr_val <= 2035:
                    years_to_search.add(yr_val)

        if not years_to_search:
            current_year = __import__('datetime').date.today().year
            years_to_search = {current_year, current_year - 1}

        for yr in sorted(years_to_search, reverse=True):
            if not (set(nit_needed.keys()) - set(mvvnl_pdf_map.keys())):
                break
            new_found_this_year = True
            for page in range(1, 60):
                if not (set(nit_needed.keys()) - set(mvvnl_pdf_map.keys())):
                    break
                if not new_found_this_year:
                    break
                new_found_this_year = False
                list_url = f"{MVVNL_BASE}?year={yr}&display=50&page={page}"
                try:
                    r = _req.get(list_url, timeout=20, headers=H, verify=False)
                    soup = _BS(r.text, "lxml")
                    tables = soup.find_all("table")
                    if len(tables) < 2:
                        break
                    rows_on_page = 0
                    remaining = set(nit_needed.keys()) - set(mvvnl_pdf_map.keys())
                    for row in tables[1].find_all("tr"):
                        cells = row.find_all("td")
                        if len(cells) < 2:
                            continue
                        link_tag = cells[1].find("a", href=True)
                        if not link_tag:
                            continue
                        nit_text = re.split(r'\[', cells[1].get_text(strip=True))[0].strip()
                        href = link_tag["href"]
                        if href.startswith("../site/"):
                            pdf_url = "https://mvvnl.in/" + href[3:]
                            if nit_text in remaining:
                                mvvnl_pdf_map[nit_text] = pdf_url
                                new_found_this_year = True
                                logger.info("[enrich_up_power] MVVNL found PDF for %s", nit_text)
                            rows_on_page += 1
                    if rows_on_page == 0:
                        break
                except Exception as e:
                    logger.warning("[enrich_up_power] MVVNL scrape %s: %s", list_url, e)
                    break

    for nit, tid in nit_needed.items():
        pdf_url = mvvnl_pdf_map.get(nit)
        if not pdf_url:
            logger.warning("[enrich_up_power] MVVNL no PDF URL for NIT=%s", nit)
            continue
        try:
            r = _req.get(pdf_url, timeout=40, headers=H, verify=False)
            doc = _fitz.open(stream=r.content, filetype="pdf")
            emd = _emd_from_pdf(doc, max_pages=2)
            if emd > 0:
                cost = (emd / 0.02) / 1_00_00_000
                cur.execute(
                    "UPDATE tenders SET allocated_amount=? WHERE tender_id=?", (cost, tid)
                )
                updated += 1
                logger.info("[enrich_up_power] MVVNL %s: EMD=%.0f → est_cost=%.4f Cr", nit, emd, cost)
            else:
                logger.warning("[enrich_up_power] MVVNL %s: EMD not found", nit)
        except Exception as e:
            logger.warning("[enrich_up_power] MVVNL %s error: %s", nit, e)

    # PVVNL
    pvvnl_rows = cur.execute(
        "SELECT tender_id, title FROM tenders "
        "WHERE source='PVVNL/UP' AND (allocated_amount IS NULL OR allocated_amount=0)"
    ).fetchall()
    logger.info("[enrich_up_power] PVVNL: %d tenders to enrich", len(pvvnl_rows))

    pvvnl_zip_map: dict = {}
    try:
        r = _req.get(PVVNL_LIST, timeout=20, headers=H, verify=False)
        soup = _BS(r.text, "lxml")
        for row in soup.select("table tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            tender_no = cells[1].get_text(strip=True)
            safe_tn = re.sub(r"[^a-zA-Z0-9]", "-", tender_no)[:60]
            tid_key = f"PVVNL-{safe_tn}"
            for cell in cells:
                a = cell.find("a", href=True)
                if a and ".zip" in a["href"].lower():
                    href = a["href"]
                    if not href.startswith("http"):
                        href = "https://pvvnl.org/" + href.lstrip("/")
                    pvvnl_zip_map[tid_key] = href
                    break
    except Exception as e:
        logger.warning("[enrich_up_power] PVVNL listing: %s", e)

    for tid, title in pvvnl_rows:
        zip_url = pvvnl_zip_map.get(tid)
        if not zip_url:
            logger.warning("[enrich_up_power] PVVNL no ZIP for %s", tid)
            continue
        try:
            r = _req.get(zip_url, timeout=40, headers=H, verify=False)
            with _zf.ZipFile(_io.BytesIO(r.content)) as z:
                pdfs = sorted(
                    [n for n in z.namelist() if n.lower().endswith(".pdf")],
                    key=lambda n: (0 if "letter" in n.lower() else 1),
                )
                if not pdfs:
                    continue
                pdf_data = z.read(pdfs[0])

            doc = _fitz.open(stream=pdf_data, filetype="pdf")
            emd = _emd_from_pdf(doc, max_pages=3)
            if emd > 0:
                cost = (emd / 0.02) / 1_00_00_000
                cur.execute(
                    "UPDATE tenders SET allocated_amount=? WHERE tender_id=?", (cost, tid)
                )
                updated += 1
                logger.info("[enrich_up_power] PVVNL %s: EMD≈%.0f → est_cost=%.4f Cr", tid, emd, cost)
            else:
                logger.warning("[enrich_up_power] PVVNL %s: no amount found", tid)
        except Exception as e:
            logger.warning("[enrich_up_power] PVVNL %s error: %s", tid, e)

    conn.commit()
    logger.info("[enrich_up_power] Done. Updated %d UP power tenders.", updated)
    return updated


def enrich_etender_up_amounts(conn: sqlite3.Connection) -> int:
    """
    Enrich etender.up.nic.in tenders (MSME/UP, NHM/UP, DGMH/UP, etc.) with
    Tender Value by visiting each tender's detail page via session navigation.
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as BS

    H = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0"}

    TARGET_ORGS = [
        "Department of MSME And Export Promotion",
        "UP Handicraft Development and Marketing Carporation",
        "National Health Mission UP",
        "Director General Medical Health",
        "Director General Medical Education and Training HQ",
        "Dr. Ram Manohar Lohia Institute of Medical Sciences",
        "Sanjay Gandhi Post Graduate Institute of Medical Sciences Lucknow",
        "Directorate of Social Welfare UP",
        "UP Development Systems Corporation Ltd",
        "Remote Sensing Applications Centre UP",
        "Shreetron India Limited",
    ]

    _TV  = re.compile(r'Tender\s+Value\s+in\s+₹\s*([\d,]+)', re.IGNORECASE)
    _EMD = re.compile(r'EMD\s+Amount\s+in\s+₹\s*([\d,]+)', re.IGNORECASE)

    cur = conn.cursor()
    etup_ids = {
        row[0]: row[0]
        for row in cur.execute(
            "SELECT tender_id FROM tenders "
            "WHERE source_url LIKE '%FrontEndTendersByOrganisation%' "
            "AND (allocated_amount IS NULL OR allocated_amount = 0)"
        ).fetchall()
    }
    logger.info("[enrich_etender] %d etender tenders need amount enrichment", len(etup_ids))
    if not etup_ids:
        return 0

    sess = _req.Session()
    sess.headers.update(H)
    sess.verify = False

    try:
        r = sess.get(f"{ETENDER_UP}?page=FrontEndTendersByOrganisation&service=page", timeout=25)
        r.raise_for_status()
    except Exception as exc:
        logger.warning("[enrich_etender] Org listing failed: %s", exc)
        return 0

    soup = BS(r.text, "lxml")
    org_url_map: dict = {}
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) == 3 and cells[0].get_text(strip=True).isdigit():
            a = row.find("a", href=True)
            if a:
                org_url_map[cells[1].get_text(strip=True)] = ETENDER_UP + a["href"].lstrip("/nicgep/app")

    updated = 0

    for org_name in TARGET_ORGS:
        org_url = org_url_map.get(org_name)
        if not org_url:
            continue

        try:
            r2 = sess.get(org_url, timeout=25)
            r2.raise_for_status()
        except Exception as exc:
            logger.warning("[enrich_etender] %s listing failed: %s", org_name, exc)
            continue

        soup2 = BS(r2.text, "lxml")
        detail_links = [
            (a.get_text(strip=True), ETENDER_UP + a["href"].lstrip("/nicgep/app"))
            for a in soup2.find_all("a", href=True)
            if "FrontEndViewTender" in a.get("href", "")
        ]

        org_updated = 0
        for link_text, detail_url in detail_links:
            title_clean = re.sub(r'[\[\]]', '', link_text).strip()[:80]
            matching = cur.execute(
                "SELECT tender_id FROM tenders "
                "WHERE source_url LIKE '%FrontEndTendersByOrganisation%' "
                "AND (allocated_amount IS NULL OR allocated_amount = 0) "
                "AND title LIKE ?",
                (f"%{title_clean[:40]}%",)
            ).fetchone()
            if not matching:
                continue
            db_tid = matching[0]

            try:
                r3 = sess.get(detail_url, timeout=20)
                detail_text = BS(r3.text, "lxml").get_text(" ", strip=True)
                tv_m = _TV.search(detail_text)
                emd_m = _EMD.search(detail_text)

                amount_rs = 0.0
                if tv_m:
                    amount_rs = float(tv_m.group(1).replace(",", ""))
                elif emd_m:
                    amount_rs = float(emd_m.group(1).replace(",", "")) / 0.02

                if amount_rs > 0:
                    cost_cr = amount_rs / 1_00_00_000
                    cur.execute(
                        "UPDATE tenders SET allocated_amount=? WHERE tender_id=?",
                        (cost_cr, db_tid)
                    )
                    updated += 1
                    org_updated += 1
                    logger.info("[enrich_etender] %s: ₹%.0f → %.4f Cr", db_tid, amount_rs, cost_cr)
            except Exception as exc:
                logger.warning("[enrich_etender] %s detail failed: %s", db_tid, exc)

        logger.info("[enrich_etender] %s: %d/%d updated", org_name, org_updated, len(detail_links))

    conn.commit()
    logger.info("[enrich_etender] Done. Updated %d etender UP tenders.", updated)
    return updated


def enrich_upmsc_amounts(conn: sqlite3.Connection) -> int:
    """
    Enrich UPMSC tenders via their etender.up.nic.in tender detail pages.
    UPMSC posts tenders on both upmsc.in (773 total) and etender (7 active).
    For active ones, fetches Tender Value directly from detail page.
    For closed/archived drug rate contracts, sets a sentinel -1 to mark 'Rate Contract'.
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as BS

    H = {"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0"}
    _TV  = re.compile(r'Tender\s+Value\s+in\s+₹\s*([\d,]+)', re.IGNORECASE)
    _EMD_FIXED = re.compile(r'EMD[^\n]{0,40}Rs\.?\s*([\d,]+)', re.IGNORECASE)
    _CRORE_PAT = re.compile(r'([\d.]+)\s*(?:crore|Cr\.?)', re.IGNORECASE)
    _LAKH_PAT  = re.compile(r'([\d.]+)\s*(?:lakh|lac)', re.IGNORECASE)

    cur = conn.cursor()
    rows = cur.execute(
        "SELECT tender_id, title, source_url FROM tenders "
        "WHERE source='UPMSC/UP' AND (allocated_amount IS NULL OR allocated_amount = 0)"
    ).fetchall()
    logger.info("[enrich_upmsc] %d UPMSC tenders to enrich", len(rows))

    updated = 0
    rate_contracts = 0

    sess = _req.Session()
    sess.headers.update(H)
    sess.verify = False

    for tid, title, pdf_url in rows:
        if not pdf_url or "upmsc.in" not in pdf_url:
            continue
        try:
            r = sess.get(pdf_url, timeout=30)
            r.raise_for_status()

            content_type = r.headers.get("Content-Type", "")
            if "pdf" in content_type or pdf_url.lower().endswith(".pdf"):
                import fitz as _fitz
                doc = _fitz.open(stream=r.content, filetype="pdf")
                text = "".join(doc[i].get_text() for i in range(min(6, doc.page_count)))

                cr_m = _CRORE_PAT.search(text)
                lk_m = _LAKH_PAT.search(text)
                emd_m = _EMD_FIXED.search(text)

                amount_rs = 0.0
                if cr_m:
                    amount_rs = float(cr_m.group(1)) * 1_00_00_000
                elif lk_m:
                    amount_rs = float(lk_m.group(1)) * 1_00_000
                elif emd_m:
                    raw = float(emd_m.group(1).replace(",", ""))
                    if "per item" not in text[max(0, emd_m.start()-20):emd_m.end()+20].lower():
                        amount_rs = raw / 0.02

                if amount_rs > 0:
                    cost_cr = amount_rs / 1_00_00_000
                    cur.execute(
                        "UPDATE tenders SET allocated_amount=? WHERE tender_id=?",
                        (cost_cr, tid)
                    )
                    updated += 1
                    logger.info("[enrich_upmsc] %s: ₹%.0f → %.4f Cr", tid, amount_rs, cost_cr)
                else:
                    rate_contracts += 1
            else:
                logger.warning("[enrich_upmsc] %s: unexpected content type %s", tid, content_type)

        except Exception as exc:
            logger.warning("[enrich_upmsc] %s error: %s", tid, exc)

    conn.commit()
    logger.info(
        "[enrich_upmsc] Done. Updated %d; %d rate contracts (no fixed amount).",
        updated, rate_contracts
    )
    return updated
