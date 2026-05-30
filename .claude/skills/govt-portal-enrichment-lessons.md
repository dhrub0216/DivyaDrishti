# Government Portal Enrichment — Lessons from Trial & Failure

Everything below is a distilled lesson from a real enrichment run across 42,605
Indian government tenders. Each section starts with the mistake, then the fix.

---

## 1. NIC GePNIC Portal — Diminishing Returns on Re-runs

### What failed
Running the NIC enricher twice on the same portal (Punjab, Rajasthan, Maharashtra)
gave **0 updates in round 2**, wasting hours on timeouts.

### Why
The NIC portal shows only **currently active / open** tenders. Round 1 captures
all tenders that are both (a) in our DB and (b) still live on the portal.
After round 1, the remaining zero-budget DB records are **old/closed tenders** —
they no longer appear anywhere on the live portal.

### Rule
**Never re-run an NIC portal you already enriched.** Track which domains were
processed and skip them in subsequent runs. Fresh portals give 34–88% hit rates;
repeat runs give ~0%.

### Hit rates observed (first run only)
| Portal | Hit Rate |
|--------|----------|
| `www.pmgsytenders.gov.in` | 88% |
| `hptenders.gov.in` | 54% |
| `sikkimtender.gov.in` | 62% |
| `arunachaltenders.gov.in` | 100% |
| Most state NIC portals | 34–46% |
| Previously enriched portals | ~0% |

---

## 2. NIC `eprocure.gov.in` — Domain-in-Path Parsing Bug

### What failed
```python
base_url = surl.split(f'/{split_at}')[0]
# For surl = "https://eprocure.gov.in/eprocure/app?..."
# split_at = "eprocure"
# surl.split("/eprocure") splits at first occurrence — inside "://eprocure"
# Result: "https:/"   ← broken
```

### Fix
Never parse the base URL from source_url. Use the domain directly:
```python
base = f"https://{domain}"
```

### Also: eprocure.gov.in uses a different app path
```python
_PORTAL_APP_PATH = {
    "eprocure.gov.in": "/eprocure/app",   # not /nicgep/app
}
app_path = _PORTAL_APP_PATH.get(domain, "/nicgep/app")
```

---

## 3. CHEPS Portal (Chhattisgarh) — JS-Rendered, Login-Gated Archive

### What failed
- Direct HTTP/REST calls to CHEPS detail pages return "Wrong URL Or Error Page"
- Playwright search worked but returned "not_found" for all 20 test records
- Assumed portal had a searchable archive of all historical tenders

### Why
CHEPS portal at `https://eproc.cgstate.gov.in/CHEPS` is:
1. **JavaScript-rendered** — the tender list only loads after clicking "ADVANCE SEARCH"
2. **Active-only** — shows only currently open tenders (`getOpenRfqListAction`)
3. **No public archive** — closed/awarded tenders require login to view

### What's in the DB from CHEPS (3,236 records)
- The original scraper stored **NIT reference numbers as titles**, e.g. `"NIT No 109 Date 18.03.2026 SYS 187407"`
- `allocated_amount` stores the NIT number as a float (e.g. `109.0`) — this is garbage
- Department is always `"Chhattisgarh Government"` — a scraper placeholder
- ~1,995 records are **administrative notices** (claim, objection, amendment) not actual tenders

### Best achievable without portal access
Use keyword rules on the title:
- `PHED` in title → Water & Sanitation
- `TW District <name>` → Social Welfare (Tribal Welfare)
- `dawa apatti` → Health (medicine supply)
- `vehicle hire` → Transport & Logistics
- System numbers (SYS \d{5,7}) are extractable but useless without portal access

### Conclusion
~2,000 CHEPS records will remain unclassified and budget-less unless login
credentials for the portal are obtained.

---

## 4. Mixed Unit Storage Bug in `allocated_amount`

### What failed
The query `WHERE allocated_amount > MIN_VALID` with `MIN_VALID = 10_000` silently
excluded valid tenders whose amounts were stored in **Crores** (e.g. `25.5`).

### Why
Different scrapers stored amounts in different units:
- Bihar (EPSV2), CHEPS → raw Rupees (e.g. `2_500_000`)
- PVVNL, MVVNL, Jal Nigam → Crores (e.g. `25.5`)
- NIT numbers → raw integers ≤ 300 (garbage)

### Fix: dual-range validity check
```python
# A tender has a valid budget if:
has_budget = (
    (allocated_amount > 100_000)                    # raw Rupees: > 1 lakh
    OR (allocated_amount BETWEEN 0.001 AND 2000)    # stored as Crores
)
```
In `app.py`, normalize to Crores at display time:
```python
RUPEES_THRESHOLD = 100_000   # if amount > this, it's in raw Rupees
def _to_crores(amt):
    if amt > RUPEES_THRESHOLD:
        return amt / 1e7
    return amt   # already in Crores
```

---

## 5. Regex Bugs in Sector Classifier

### Bug 1: Wrong spelling — `dava` vs `dawa`
The rule was `dava\s+apatti` but all real titles had `dawa apatti` (correct Hindi).
**Always test the classifier on a sample of unclassified records before running.**

### Bug 2: Stem match blocked by trailing `\b`
```python
# BROKEN: \b after "hir" fails because "hire" has a word char after "r"
r'\b(vehicle\s+hir|bus\s+hir)\b'

# FIXED: match "hire" or "hiring" explicitly
r'\b(vehicle\s+hire?|bus\s+hire?)\b'
```
The pattern `vehicle\s+hir` was intended as a prefix-match for hire/hiring, but the
trailing `\b` requires a word boundary immediately after "hir". Since "hire" has 'e'
after 'r', there is no boundary — nothing matches.

### Bug 3: Dept rules not firing because dept field is a placeholder
CHEPS always stores `department = "Chhattisgarh Government"`. Dept-based rules
(PHED, TW, etc.) never fire. Must also add those abbreviations to **title rules**.

### Lesson: test before running
```python
from scrapers.classify_sectors import _classify_one
for title, dept in sample_rows:
    print(_classify_one(title, dept), '←', title[:60])
```
Run this on ~20 unclassified samples to verify rules fire before running on 10k rows.

---

## 6. Python 3.9 Type Hint Incompatibility

### What failed
```python
def _classify_one(title: str, department: str) -> str | None:
# TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```
`X | Y` union syntax for type hints requires Python 3.10+. The system uses Python 3.9.

### Fix
```python
from typing import Optional
def _classify_one(title: str, department: str) -> Optional[str]:
# OR simply omit the return type annotation:
def _classify_one(title: str, department: str):
```

---

## 7. Sector Classification — What Remains Unclassifiable

After multiple passes with dept + title rules, these categories resist classification:

| Count | Source | Reason |
|-------|--------|--------|
| ~1,995 | CHEPS | Administrative notices (claim/objection/NIT extension) |
| ~226 | GEM Bidplus | Scraping artifact: title = "View Corrigendum/Representation" |
| ~262 | Haryana NIC | Titles truncated mid-sentence by scraper |
| ~100 | Various | One-word or date-only titles ("From", "Jan 13, 2026") |

These are not worth further effort — most aren't real procurement tenders.
Accepting ~9-10% "Other" is the right call.

---

## 8. Portal Timing — Night vs Daytime

### What failed
`etender.up.nic.in` timed out repeatedly when run at 1–2 AM IST.

### Why
NIC portals are hosted on NIC (National Informatics Centre) servers. These show
degraded performance outside business hours (maintenance windows, lower capacity).

### Rule
Run portal enrichment between **09:00–20:00 IST**. Large portals (UP, MP, Rajasthan)
with 2,000–6,000 tenders need the most reliable connectivity.

---

## 9. SQLite Concurrent Writes — DB Lock

See `sqlite-lock-handling.md` for full details. Short version:

```python
# When opening connection for any enricher:
conn = sqlite3.connect(DB_PATH, timeout=60)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=60000")
```

```python
# Wrap writes with retry:
def _db_retry(fn, *args, retries=8, base_delay=1.0):
    for attempt in range(retries):
        try:
            return fn(*args)
        except sqlite3.OperationalError as exc:
            if 'locked' not in str(exc) or attempt == retries - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
```

**Never run two enricher jobs in parallel against the same SQLite file** without
both jobs using WAL mode + busy_timeout. Even with these, only one writer can
operate at a time — the other will wait.

---

## 10. New Sector: Mining

Coal mining and mineral extraction form a distinct category not covered by Energy
(which is electricity/oil/gas). Added "Mining" sector with:

**Dept rules:** Coal India, Singareni Collieries (SCCL), NCL, BCCL, CCL, MCL,
SECL, ECL, WCL, NMDC, state Mineral Development departments.

**Title rules:** colliery, overburden, OB dump, OB removal, coal mine, coal block,
coal washery, mineral extraction, blasting, mine site, pit head.

---

## Quick Reference: Which Portals Have Been Enriched

| Portal | Status | Notes |
|--------|--------|-------|
| All 15 small/NE portals | Done — 746 updated | First run |
| `eprocure.gov.in` (Central) | Done — 200 updated | First run |
| `etenders.hry.nic.in`, `jktenders.gov.in`, `wbtenders.gov.in`, `tntenders.gov.in`, `uktenders.gov.in`, `jharkhandtenders.gov.in`, `govtprocurement.delhi.gov.in` | Done | First run (earlier session) |
| `etender.up.nic.in` | Partially done — timed out | Retry in daytime |
| `mptenders.gov.in`, `eproc.rajasthan.gov.in`, `mahatenders.gov.in`, `eproc.punjab.gov.in`, `www.etenders.kerala.gov.in`, `tendersodisha.gov.in` | Done — DO NOT RE-RUN | Diminishing returns confirmed |
