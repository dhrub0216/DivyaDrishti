"""
scrapers/enrich_cheps.py — Re-enrich Chhattisgarh CHEPS tenders with real
title, department, probable amount, and sector by navigating each tender's
detail page on the live portal.

WHY THIS EXISTS
───────────────
The original CHEPS scraper stored NIT reference numbers (e.g., "NIT No 109
SYS 187407") as titles and NIT numbers as allocated_amount (109.0). This
enricher extracts the actual System Number from each DB record, navigates
to the tender's public detail page on the CHEPS portal, and writes back
real values.

HOW IT WORKS
────────────
1. From each CHEPS DB record, extract the CHEPS System No via regex.
2. Navigate to the CHEPS public tender search page using Playwright.
3. Search by System No in the advance-search form.
4. Parse the tender table row: get Description, Organization, Probable Amount.
5. Optionally click the "View" link to get the full detail page.
6. Update: title, department, allocated_amount, sector in DB.

USAGE
─────
  python3 -c "
  import sqlite3
  from scrapers.enrich_cheps import enrich_cheps_tenders
  conn = sqlite3.connect('tenders.db')
  enrich_cheps_tenders(conn, limit=100)
  conn.close()
  "
"""

import re
import time
import logging
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

_SYS_NO = re.compile(
    r'(?:SYS(?:TEM)?\s*No[.\s]*|S\.No\.\s*|System\s+No\s*[.\-]?\s*)(\d{5,7})',
    re.IGNORECASE,
)
_TENDER_NO = re.compile(r'(?:NIT\s+No\.?|Tender\s+No\.?)\s*(\d{3,6})\b', re.IGNORECASE)

# Simple sector keyword map for classifying from description
_SECTOR_KWORDS = {
    'Water & Sanitation': ['water', 'pipeline', 'drainage', 'sewage', 'sanitation',
                           'toilet', 'bore', 'hand pump', 'irrigation', 'canal', 'nala',
                           'jal', 'phed', 'phe'],
    'Energy':            ['electric', 'power', 'solar', 'transformer', 'feeder',
                          'wiring', 'light', 'energy', 'bijli', 'vidyut'],
    'Health':            ['hospital', 'health', 'medical', 'medicine', 'drug',
                          'dispensary', 'ambulance', 'phc', 'chc'],
    'Education':         ['school', 'college', 'university', 'classroom', 'library',
                          'hostel', 'shiksha', 'vidyalay', 'iti', 'skill'],
    'Agriculture':       ['agriculture', 'farm', 'crop', 'seeds', 'fertilizer',
                          'horticulture', 'fisheries', 'dairy', 'animal'],
    'Rural Development': ['panchayat', 'gram', 'rural', 'village', 'pmgsy', 'mnrega'],
    'Urban Development': ['urban', 'municipal', 'city', 'ward', 'nagar', 'market'],
    'Environment & Forestry': ['forest', 'plantation', 'nursery', 'environment',
                               'wildlife', 'ecology'],
    'Social Welfare':    ['tribal', 'welfare', 'hostel tribal', 'sc st', 'minority',
                          'prison', 'jail', 'anganwadi', 'ration'],
    'Digital & IT':      ['software', 'computer', 'server', 'it ', 'website',
                          'digital', 'surveillance', 'cctv'],
    'Infrastructure':    ['road', 'bridge', 'building', 'construction', 'renovation',
                          'repair', 'rcc', 'bituminous', 'culvert', 'boundary wall'],
}


def _guess_sector(text: str) -> str:
    t = text.lower()
    for sector, kws in _SECTOR_KWORDS.items():
        if any(k in t for k in kws):
            return sector
    return 'Other'


def _extract_sys_no(text: str) -> Optional[str]:
    m = _SYS_NO.search(text)
    if m:
        return m.group(1)
    return None


def enrich_cheps_tenders(
    conn: sqlite3.Connection,
    limit: int = 200,
    headless: bool = True,
) -> dict:
    """
    Navigate CHEPS portal and update DB records with real titles, departments,
    probable amounts, and sector classification.

    Returns stats dict.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    BASE = 'https://eproc.cgstate.gov.in/CHEPS'
    LIST_URL = f'{BASE}/business/getOpenRfqListAction.do'

    cur = conn.cursor()

    # Fetch CHEPS records that need enrichment
    rows = cur.execute("""
        SELECT tender_id, title, allocated_amount
        FROM tenders
        WHERE source LIKE '%CHEPS%'
          AND sector = 'Other'
          AND (allocated_amount IS NULL OR allocated_amount < 100000)
    """).fetchall()

    logger.info("[CHEPS-ENRICH] %d CHEPS 'Other' records to process", len(rows))

    # Extract system numbers we can use
    searchable = []
    for tid, title, amt in rows:
        sys_no = _extract_sys_no(tid) or _extract_sys_no(title or '')
        if sys_no:
            searchable.append((tid, sys_no))

    logger.info("[CHEPS-ENRICH] %d records have extractable system numbers", len(searchable))
    searchable = searchable[:limit]

    stats = {'updated': 0, 'not_found': 0, 'errors': 0}
    updates = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 900},
        )
        page = ctx.new_page()
        page.set_default_timeout(25_000)

        try:
            page.goto(LIST_URL, wait_until='domcontentloaded', timeout=30_000)
            time.sleep(3)

            # Click "ADVANCE SEARCH" button if present
            try:
                adv = page.locator('text=ADVANCE SEARCH, text=Advance Search, text=Advanced Search').first
                if adv.is_visible(timeout=3000):
                    adv.click()
                    time.sleep(2)
            except Exception:
                pass

            for tid, sys_no in searchable:
                try:
                    # Look for a system-number search input
                    # Try the CHEPS advance search form fields
                    for field_sel in ['input[name="systemNo"]', 'input[name="rfqId"]',
                                      'input[name="tenderNo"]', 'input[placeholder*="System"]',
                                      'input[placeholder*="Tender"]']:
                        try:
                            inp = page.locator(field_sel).first
                            if inp.is_visible(timeout=1000):
                                inp.fill('')
                                inp.fill(sys_no)
                                break
                        except Exception:
                            continue

                    # Submit search
                    for btn_sel in ['input[type="submit"]', 'button[type="submit"]',
                                    'button:has-text("Search")', 'input[value="Search"]',
                                    'input[value="Go"]', 'button:has-text("Go")']:
                        try:
                            btn = page.locator(btn_sel).first
                            if btn.is_visible(timeout=1000):
                                btn.click()
                                time.sleep(2)
                                break
                        except Exception:
                            continue

                    # Find the result table row
                    # Look for the system number in any table cell
                    cell = page.locator(f'td:has-text("{sys_no}")').first
                    if not cell.is_visible(timeout=5000):
                        stats['not_found'] += 1
                        continue

                    row_el = cell.locator('xpath=ancestor::tr').first
                    cells = row_el.locator('td').all()
                    cell_texts = [c.inner_text().strip() for c in cells]

                    # Description is typically the longest cell
                    desc = max(cell_texts, key=len) if cell_texts else ''
                    # Probable amount — look for numeric cell with lakhs/crores/₹
                    amt_text = next(
                        (t for t in cell_texts if re.search(r'[\d,]{4,}|lakh|crore', t, re.I)),
                        ''
                    )
                    amt_val = None
                    amt_m = re.search(r'([\d,]+(?:\.\d+)?)', amt_text)
                    if amt_m:
                        try:
                            amt_val = float(amt_m.group(1).replace(',', ''))
                        except ValueError:
                            pass

                    # Department — try to click "View" for detail page
                    dept = 'Chhattisgarh Government'
                    try:
                        view_link = row_el.locator('a:has-text("View"), a:has-text("Details")').first
                        if view_link.is_visible(timeout=1000):
                            with page.expect_navigation(timeout=15_000):
                                view_link.click()
                            detail_text = page.inner_text('body')
                            # Extract department from detail page
                            dept_m = re.search(
                                r'(?:organization|department|organisation)[:\s]+([^\n\r]{5,80})',
                                detail_text, re.IGNORECASE
                            )
                            if dept_m:
                                dept = dept_m.group(1).strip()[:150]
                            # Extract amount from detail page if not found in table
                            if amt_val is None:
                                pa_m = re.search(
                                    r'(?:probable|estimated|tender)\s+(?:value|amount)[:\s₹]+([\d,]+(?:\.\d+)?)',
                                    detail_text, re.IGNORECASE
                                )
                                if pa_m:
                                    try:
                                        amt_val = float(pa_m.group(1).replace(',', ''))
                                    except ValueError:
                                        pass
                            page.go_back(timeout=15_000)
                            time.sleep(1)
                    except Exception:
                        pass

                    if not desc or len(desc) < 5:
                        stats['not_found'] += 1
                        continue

                    sector = _guess_sector(desc)
                    updates.append((desc[:300], dept[:200], amt_val, sector, tid))
                    stats['updated'] += 1
                    logger.info("[CHEPS-ENRICH] %s → %s | ₹%s | %s",
                                sys_no, desc[:50], amt_val, sector)

                except Exception as exc:
                    logger.warning("[CHEPS-ENRICH] SysNo %s error: %s", sys_no, exc)
                    stats['errors'] += 1

        except PWTimeout:
            logger.warning("[CHEPS-ENRICH] Portal navigation timeout")
        except Exception as exc:
            logger.warning("[CHEPS-ENRICH] Unexpected error: %s", exc)
        finally:
            browser.close()

    # Write updates to DB
    if updates:
        cur.executemany(
            "UPDATE tenders SET title=?, department=?, allocated_amount=?, sector=? "
            "WHERE tender_id=?",
            updates
        )
        conn.commit()
        logger.info("[CHEPS-ENRICH] Committed %d updates", len(updates))

    return stats
