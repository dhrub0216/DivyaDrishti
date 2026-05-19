# DivyaDrishti — Divine Procurement Intelligence Engine 🪷

**दिव्यदृष्टि** · Pan-India Government Tender Analytics Platform

A full-stack intelligence system that scrapes 42,000+ government tenders from 50+ portals across India, classifies them into 12 standard sectors, geocodes them to exact GPS coordinates, and visualises the data in a real-time Streamlit dashboard with innovative charts.

---

## What It Does

| Step | What happens |
|------|-------------|
| **Scrape** | Collects open tenders from NIC GePNIC portals (all 28 states), GeM Bidplus, Bihar EPSV2, Chhattisgarh CHEPS, UP Jal Nigam, NHAI, Coal India, ONGC, and more |
| **Classify** | Uses keyword-based sector classification to tag each tender as Infrastructure / Health / Education / Agriculture / Energy / etc. |
| **Geocode** | Places each tender on the map using district coordinate tables + OpenStreetMap Nominatim |
| **Store** | Saves all data to a local SQLite database (`tenders.db`) with automatic schema migration |
| **Visualise** | Streams the data into a Streamlit dashboard with 13 different chart types |

---

## Dashboard (DivyaDrishti UI)

```
streamlit run app.py
```

The dashboard has **4 tabs**:

### Tab 1 — Mission Control
- **6 KPI cards**: Total budget, tender count, average, largest single tender, sector count, source count
- **4 Spotlight cards**: Top spending state, hottest sector, biggest tender, most active portal
- **Auto-Narrative Engine**: Generates 5 sentences of contextual insight from the current filter state
- **Adaptive Map**: Scatter plot (≤5,000 tenders) or aggregated district bubbles (>5,000) + linear feature lines for roads/pipelines
- **Source Ring chart**: Which portal contributed how many tenders

### Tab 2 — Intelligence Suite
- **Procurement Hierarchy Treemap**: State → Sector by ₹ Crores — instantly shows where money concentrates
- **Budget Flow Sankey**: Portal → State → Sector money river — follow every rupee's journey
- **Sector × State Heatmap Matrix**: 15 states × 12 sectors — spot procurement blind-spots

### Tab 3 — Sector Lens
- **Sector Bubble Pack**: Circle size = total budget — visceral sense of relative sector weight
- **Budget Waterfall**: Step-down from grand total to each sector
- **Timeline Pulse**: Procurement activity area chart by month
- **Leader Boards**: Top departments and contractors by ₹ Crores
- **Status Donut** + **Budget Histogram**

### Tab 4 — Data Vault
- Paginated searchable tender table with CSV download
- Portal health log (last scrape time, success/failure, record count per source)

---

## Project Structure

```
DivyaDrishti/
│
├── app.py                  # Streamlit dashboard — all 13 visualisations
├── cli.py                  # Command-line scraper entry point
├── pipeline.py             # Backward-compat shim (re-exports from services/)
├── scraper_v3.py           # Backward-compat shim (re-exports from scrapers/)
│
├── config/
│   ├── portals.py          # Portal URLs for all 50+ government websites
│   ├── sectors.py          # 12 sector definitions + colours
│   └── geography.py        # GPS coordinates for every Indian district & block
│
├── models/
│   └── tender.py           # TenderRecord dataclass + DB schema + map geometry
│
├── repository/
│   └── db.py               # SQLite read/write layer (get_db, upsert, log_health)
│
├── services/
│   ├── classifier.py       # Sector classification from tender title + department
│   ├── aggregator.py       # Data loading, coordinate jitter, aggregation
│   ├── geocoder.py         # Nominatim geocoding service
│   ├── enricher.py         # Entity geocoding (hospital/school/road name → GPS)
│   └── block_extractor.py  # Extract block name from tender title text
│
├── scrapers/
│   ├── orchestrator.py     # Pipeline runner — calls all scrapers in sequence
│   ├── nic.py              # NIC GePNIC portal scraper (30+ state portals)
│   ├── gem.py              # Government e-Marketplace Bidplus scraper
│   ├── api_sources.py      # data.gov.in API + PMGSY scraper
│   ├── deep.py             # Detail-page scraper (reads full contract text)
│   ├── js_portals.py       # JS-rendered PSU portals (ONGC, NHAI, Coal India, NTPC)
│   ├── central_psu.py      # HTML PSU portals (MSEDCL, Chennai Port, BHEL, AAI)
│   └── states/
│       ├── bihar.py        # Bihar EPS v2 (AJAX + Playwright)
│       ├── chhattisgarh.py # Chhattisgarh CHEPS (Java Struts + Playwright)
│       ├── up.py           # UP: Jal Nigam, UPEIDA, PVVNL, MVVNL, UPMSC
│       ├── karnataka.py    # Karnataka eProcurement
│       ├── ap_telangana.py # Andhra Pradesh + Telangana eProcurement
│       └── gujarat.py      # Gujarat nProcure (~4k tenders)
│
└── tenders.db              # SQLite database (42,000+ scraped tenders)
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium        # for JS-rendered portals
```

### 2. Run the dashboard (pre-loaded data)

```bash
streamlit run app.py
```

### 3. Scrape fresh data

```bash
# Most important sources (no API key needed):
python cli.py --sources biharv2 cgstate up_misc gem

# Add NHAI and Coal India (JS-rendered, needs Playwright):
python cli.py --sources nhai coal_india ongc

# All state NIC portals (slow — 30+ states):
python cli.py --sources states

# With data.gov.in (needs free API key from data.gov.in):
python cli.py --sources datagov --api-key YOUR_KEY
```

### 4. Re-classify tenders (offline, fast)

```bash
python cli.py --reclassify
```

---

## Data Sources Covered

| Source | Type | Records | Notes |
|--------|------|---------|-------|
| NIC GePNIC (28 states) | HTML scraping | ~8,000 | Standard NIC portal, same structure across states |
| GeM Bidplus | HTML scraping | ~500 | Government e-Marketplace |
| Bihar EPS v2 | Playwright AJAX | ~633 | JS hash-tab pagination |
| Chhattisgarh CHEPS | Playwright | ~3,236 | Java Struts RFQ system |
| UP Jal Nigam | HTTP scraping | ~6,270 | Largest single source |
| UP MSMSE/Health/IT | HTTP scraping | ~5,000 | Sector-specific UP portals |
| UP Power (PVVNL/MVVNL) | HTTP scraping | ~500 | Distribution companies |
| NHAI | REST API | ~117 | Angular SPA, no browser needed |
| Coal India | Playwright DataTables | ~30 | DataTables with hidden detail cells |
| ONGC | Playwright Liferay | ~50 | Liferay portlet with CSRF token |
| Gujarat nProcure | Playwright XHR | ~3,987 | |
| Karnataka eProcurement | HTTP scraping | ~446 | |
| AP/Telangana | HTTP scraping | ~3,400 | |
| data.gov.in | REST API | variable | Requires API key |

---

## Technical Architecture

```
┌─────────────────────────────────────────────────────┐
│                   User / Browser                     │
└──────────────────────────┬──────────────────────────┘
                           │  streamlit run app.py
                           ▼
┌─────────────────────────────────────────────────────┐
│           app.py  (Streamlit Dashboard)             │
│  Tabs: Mission Control | Intelligence | Sector | Vault│
└──────────────────────────┬──────────────────────────┘
                           │  load_enterprise_tender_stream()
                           ▼
┌─────────────────────────────────────────────────────┐
│         services/aggregator.py                       │
│  Coordinate resolution · Reclassification · Memory   │
└──────────────────────────┬──────────────────────────┘
                           │  SELECT * FROM tenders
                           ▼
┌─────────────────────────────────────────────────────┐
│              tenders.db  (SQLite)                    │
│  42,000+ rows · 17 columns · 5 indexes               │
└──────────────────────────┬──────────────────────────┘
                           │  INSERT OR REPLACE
                           ▼
┌─────────────────────────────────────────────────────┐
│         scrapers/ (50+ sources)                      │
│  HTML · AJAX · Playwright · REST API                 │
└─────────────────────────────────────────────────────┘
```

---

## JavaScript Portal Bypass Strategy

Three different bypass techniques are used for portals that don't serve plain HTML:

| Portal | Technology | Bypass Method |
|--------|------------|---------------|
| **ONGC** | Liferay DXP portlet with CSRF token | Playwright loads home page → grabs live `p_auth` token from the "Current NITs" link → navigates to it. Tender Number is in `<th class="tno">` not `<td>` — must query `th, td` |
| **NHAI** | Angular SPA REST API | Direct `requests.post()` to `/nhai/api/tenderlist` with multipart form data. No browser needed. Returns all 117 tenders in one call |
| **Coal India** | jQuery DataTables | Playwright sets page size to "All", then selects only outer table rows (`#alltender > tbody > tr`) to avoid reading inner-table rows. Amount is in a hidden 5th cell |
| **NTPC** | reCAPTCHA v3 | Currently stubbed. Bypass options: 2captcha service, or vendor registration for authenticated access |

---

## Known Limitations

- **NTPC**: Blocked by Google reCAPTCHA v3 — stub in place, returns 0 records
- **AAI** (Airports Authority of India): Datepicker widget rejects programmatic fill — returns 0 records
- **Power Grid**: Times out (portal restructure) — not yet scraped
- **IREPS** (Indian Railways): Requires authenticated login with OTP — not publicly accessible

---

## Requirements

```
streamlit>=1.40
plotly>=6.0
pandas>=2.0
numpy>=1.24
requests>=2.28
playwright
geopy
ddddocr
Pillow
```

---

*Built for pan-India government procurement transparency.*  
*Data sourced from publicly available government tender portals.*
