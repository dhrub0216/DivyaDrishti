"""
scrapers/enrich_nic.py — Generalized NIC GePNIC portal budget enricher.

WHY THIS EXISTS
───────────────
When we scrape the NIC GePNIC portals (all 29 state portals like mptenders.gov.in,
eproc.rajasthan.gov.in, etc.), the org-listing page that lists all tenders does NOT
show the tender's estimated budget ("Tender Value").  The budget only appears on each
tender's individual detail page.

This file navigates to those detail pages, extracts the amount, and writes it back to
the database.  It can recover budget data for up to 23,633 tenders.

HOW IT WORKS (one portal, one pass)
─────────────────────────────────────
1. Visit  `{domain}/nicgep/app?page=FrontEndTendersByOrganisation&service=page`
   → get a list of all organisations active on that portal.
2. For each org, follow the org-specific link to see the org's active tenders.
3. From the org's tender listing, collect every `FrontEndViewTender` link.
4. Visit each detail page:
   a. Extract  `Tender ID = 2026_XYZ_123456_N`  (NIC's own ID format).
   b. Match it against our DB: tender_id stored as  `ETXX-2026_XYZ_123456_N`.
   c. Read  `Tender Value in ₹ NNN`  — the primary amount field.
   d. Fall back to  `EMD Amount in ₹ NNN / 0.02`  when Tender Value is 0
      (EMD is legally set at ~2 % of contract value).
5. Amounts stored in the DB are in Crores (÷ 1,00,00,000).

RATE LIMITING
─────────────
NIC portals ban IPs for rapid requests.  We wait 1 second between requests by default.
Increase `delay_sec` if you see HTTP 429 or repeated redirects to the homepage.

USAGE (from cli.py)
────────────────────
  python cli.py --enrich-nic                     # all 29 portals, 50 tenders each
  python cli.py --enrich-nic --nic-limit 200     # 200 per portal
  python cli.py --enrich-nic --nic-domains etender.up.nic.in mptenders.gov.in
"""

import re
import time
import logging
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)


def _db_retry(fn, *args, retries=8, base_delay=1.0):
    """Retry a SQLite call on 'database is locked' with exponential backoff.

    SQLite allows only one writer at a time. When two enricher processes run
    in parallel, the slower one will hit OperationalError('database is locked').
    This wrapper waits up to ~4 minutes total (1+2+4+8+16+32+64+128 s) before
    giving up.
    """
    for attempt in range(retries):
        try:
            return fn(*args)
        except sqlite3.OperationalError as exc:
            if 'locked' not in str(exc) or attempt == retries - 1:
                raise
            wait = base_delay * (2 ** attempt)
            logger.warning("[NIC-ENRICH] DB locked — retry %d/%d in %.0fs", attempt + 1, retries, wait)
            time.sleep(wait)

# ── Amount extraction patterns ─────────────────────────────────────────────────
_TV  = re.compile(r'Tender\s+Value\s+in\s+₹\s*([\d,]+(?:\.\d+)?)', re.IGNORECASE)
_EMD = re.compile(r'EMD\s+Amount\s+in\s+₹\s*([\d,]+(?:\.\d+)?)',   re.IGNORECASE)
_NIC_ID = re.compile(r'\b(\d{4}_[A-Z][A-Z0-9]+_\d+_\d+)\b')

# Maps a NIC portal domain → the 2-char state abbreviation we prefix in tender_id
_DOMAIN_PREFIX: dict[str, str] = {
    "etender.up.nic.in":              "ETUP",
    "mptenders.gov.in":               "ETMP",
    "eproc.rajasthan.gov.in":         "ETR",
    "mahatenders.gov.in":             "ETM",
    "eproc.punjab.gov.in":            "ETP",
    "www.etenders.kerala.gov.in":     "ETK",
    "tendersodisha.gov.in":           "ETO",
    "etenders.hry.nic.in":            "ETH",
    "jktenders.gov.in":               "ETJ&K",
    "wbtenders.gov.in":               "ETWB",
    "tntenders.gov.in":               "ETTN",
    "uktenders.gov.in":               "ETUK",
    "govtprocurement.delhi.gov.in":   "ETDL",
    "jharkhandtenders.gov.in":        "ETJH",
    "tripuratenders.gov.in":          "ETTR",
    "etenders.chd.nic.in":            "ETCHD",
    "www.assamtenders.gov.in":        "ETAS",
    "eprocure.goa.gov.in":            "ETGA",
    "hptenders.gov.in":               "ETHP",
    "eprocure.andamannicobar.gov.in": "ETAN",
    "pudutenders.gov.in":             "ETPY",
    "ddtenders.gov.in":               "ETDD",
    "dnhtenders.gov.in":              "ETDNH",
    "tendersutl.gov.in":              "ETUT",
    "arunachaltenders.gov.in":        "ETAR",
    "sikkimtender.gov.in":            "ETSK",
    "meghalayatenders.gov.in":        "ETME",
    "manipurtenders.gov.in":          "ETMN",
    "nagalandtenders.gov.in":         "ETNL",
    "www.pmgsytenders.gov.in":        "ETPMGSY",
    "tenders.ladakh.gov.in":          "ETLDK",
    # Central Government portal — uses /eprocure/app path (not /nicgep/app)
    "eprocure.gov.in":                "ETC(",
}

# Portals that use a path prefix other than /nicgep/app
_PORTAL_APP_PATH: dict[str, str] = {
    "eprocure.gov.in": "/eprocure/app",
}


def _extract_amount_rupees(page_text: str) -> Optional[float]:
    """
    Return the tender value in raw Rupees (not Crores) from a detail-page text.
    Primary: 'Tender Value in ₹ N,NNN,NNN'
    Fallback: 'EMD Amount in ₹ N,NNN' → estimated contract value = EMD / 0.02
    Returns None if nothing found.
    """
    tv = _TV.search(page_text)
    if tv:
        try:
            val = float(tv.group(1).replace(",", ""))
            if val > 0:
                return val
        except ValueError:
            pass

    emd = _EMD.search(page_text)
    if emd:
        try:
            val = float(emd.group(1).replace(",", ""))
            if val > 0:
                return val / 0.02   # EMD ≈ 2 % of contract value
        except ValueError:
            pass

    return None


def enrich_nic_portal_amounts(
    conn:             sqlite3.Connection,
    limit_per_portal: int   = 50,
    delay_sec:        float = 1.2,
    target_domains:   Optional[list] = None,
) -> dict:
    """
    Visit NIC GePNIC portal detail pages and write Tender Value back to the DB.

    Parameters
    ──────────
    conn             : open SQLite connection (caller manages commit/close)
    limit_per_portal : max tenders to enrich per portal domain per call
    delay_sec        : seconds to wait between HTTP requests (NIC rate-limits)
    target_domains   : if given, only process these domain hostnames; else all

    Returns a dict mapping domain → {"visited": N, "updated": N, "errors": N}
    """
    import requests as _req
    import urllib3
    urllib3.disable_warnings()
    from bs4 import BeautifulSoup as BS

    # Enable WAL mode (allows concurrent reads alongside writes) and set a
    # 60-second busy-timeout so SQLite waits instead of immediately raising
    # OperationalError when another process holds the write lock.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
    except sqlite3.OperationalError:
        pass  # read-only connection or already set — not fatal

    H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

    # ── Discover unique NIC portal domains that still have zero-budget tenders ──
    rows = conn.execute("""
        SELECT DISTINCT
            SUBSTR(source_url, 9,
                   INSTR(SUBSTR(source_url, 9), '/') - 1) AS domain,
            source_url
        FROM tenders
        WHERE (source_url LIKE 'https://%/nicgep%'
            OR source_url LIKE 'https://eprocure.gov.in/%')
          AND (allocated_amount IS NULL OR allocated_amount <= 10000)
        ORDER BY domain
    """).fetchall()

    portal_domains = {}   # domain → base_url
    for domain, surl in rows:
        if domain and domain not in portal_domains:
            # Use the domain directly rather than parsing source_url, which can
            # break when the domain name contains the same word as the path segment
            # (e.g. eprocure.gov.in has /eprocure/ in both domain and path).
            base = f"https://{domain}"
            portal_domains[domain] = base

    if target_domains:
        portal_domains = {d: u for d, u in portal_domains.items() if d in target_domains}

    logger.info("[NIC-ENRICH] %d unique NIC portals to process", len(portal_domains))

    overall: dict = {}
    cur = conn.cursor()

    for domain, base_url in portal_domains.items():
        stats = {"visited": 0, "updated": 0, "errors": 0}
        overall[domain] = stats
        prefix = _DOMAIN_PREFIX.get(domain, "ET")

        logger.info("[NIC-ENRICH] ── %s  (prefix=%s, base=%s)", domain, prefix, base_url)

        sess = _req.Session()
        sess.headers.update(H)
        sess.verify = False

        # Step 1: org listing
        app_path = _PORTAL_APP_PATH.get(domain, "/nicgep/app")
        try:
            r = sess.get(f"{base_url}{app_path}?page=FrontEndTendersByOrganisation&service=page",
                         timeout=30)
            r.raise_for_status()
            time.sleep(delay_sec)
        except Exception as exc:
            logger.warning("[NIC-ENRICH] %s org listing failed: %s", domain, exc)
            stats["errors"] += 1
            continue

        soup = BS(r.text, "lxml")
        org_links: list = []
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            if not tds[0].get_text(strip=True).isdigit():
                continue
            a = tr.find("a", href=lambda h: h and "DirectLink" in h)
            if a:
                org_links.append((tds[1].get_text(strip=True), a["href"]))

        logger.info("[NIC-ENRICH] %s: %d organisations", domain, len(org_links))

        portal_updated = 0

        # Step 2: iterate orgs, then tenders
        for org_name, org_href in org_links:
            if portal_updated >= limit_per_portal:
                break

            try:
                r2 = sess.get(f"{base_url}{org_href}", timeout=30)
                r2.raise_for_status()
                time.sleep(delay_sec)
            except Exception as exc:
                logger.warning("[NIC-ENRICH] %s / %s org page failed: %s", domain, org_name[:30], exc)
                stats["errors"] += 1
                continue

            soup2 = BS(r2.text, "lxml")
            detail_links = [
                (a.get_text(strip=True)[:80], a["href"])
                for a in soup2.find_all("a", href=True)
                if "FrontEndViewTender" in a["href"]
            ]

            if not detail_links:
                continue

            logger.info("[NIC-ENRICH] %s / %-35s → %d tenders", domain, org_name[:35], len(detail_links))

            for _link_text, detail_href in detail_links:
                if portal_updated >= limit_per_portal:
                    break

                stats["visited"] += 1
                try:
                    r3 = sess.get(f"{base_url}{detail_href}", timeout=25)
                    r3.raise_for_status()
                    time.sleep(delay_sec)
                except Exception as exc:
                    logger.warning("[NIC-ENRICH] detail page error: %s", exc)
                    stats["errors"] += 1
                    continue

                page_text = BS(r3.text, "lxml").get_text(" ", strip=True)

                # Extract the NIC tender ID (e.g. "2026_AICTS_507848_1")
                nic_id_m = _NIC_ID.search(page_text)
                if not nic_id_m:
                    continue
                nic_id = nic_id_m.group(1)

                # Match to our DB tender_id  (e.g. "ETMP-2026_AICTS_507848_1")
                db_tid = f"{prefix}-{nic_id}"

                row = cur.execute(
                    "SELECT allocated_amount FROM tenders WHERE tender_id=?", (db_tid,)
                ).fetchone()

                if row is None:
                    # Try prefix-free match in case our prefix derivation differs
                    row2 = cur.execute(
                        "SELECT tender_id, allocated_amount FROM tenders "
                        "WHERE tender_id LIKE ?", (f"%-{nic_id}",)
                    ).fetchone()
                    if row2:
                        db_tid = row2[0]
                        row = (row2[1],)

                if row is None:
                    continue   # this tender was not scraped (maybe expired/new)

                existing_amt = row[0]
                if existing_amt and float(existing_amt) > 10000:
                    continue   # already have a valid amount

                # Extract amount
                amount_rs = _extract_amount_rupees(page_text)
                if amount_rs is None or amount_rs <= 0:
                    continue

                # Store in raw Rupees (consistent with Bihar/CHEPS scrapers).
                # app.py normalises to Crores at display time based on magnitude.
                _db_retry(
                    cur.execute,
                    "UPDATE tenders SET allocated_amount=? WHERE tender_id=?",
                    (amount_rs, db_tid),
                )
                stats["updated"] += 1
                portal_updated += 1
                logger.info("[NIC-ENRICH] %s  ₹%.0f (%.4f Cr)", db_tid, amount_rs, amount_rs/1e7)

        _db_retry(conn.commit)
        logger.info("[NIC-ENRICH] %s done — visited=%d updated=%d errors=%d",
                    domain, stats["visited"], stats["updated"], stats["errors"])

    return overall
