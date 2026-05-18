"""
DivyaDrishti — Divine Procurement Intelligence Engine  v3.0
Pan-India Public Expenditure & Tender Analytics · दिव्यदृष्टि
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from pipeline import (
    load_enterprise_tender_stream,
    load_health_log,
    get_full_hierarchy,
    server_side_aggregate,
    get_view_config,
    SECTOR_DEPARTMENTS,
    SECTOR_COLORS,
    STATE_CENTERS,
    DISTRICT_COORDINATES,
)
import math
import numpy as np

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DivyaDrishti — Procurement Intelligence",
    page_icon="🪷",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Sentinel values ───────────────────────────────────────────────────────────
ALL = "All"

# Threshold above which we switch to aggregated map (performance guard)
SCATTER_LIMIT = 5_000

STATUS_COLORS = {"Active": "#2E7D52", "Awarded": "#C47629", "Completed": "#1A4A7A"}

# ─── CSS ── DivyaDrishti brand theme ──────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap');

/* ── Tokens ── */
:root {
  --saffron : #C47629;
  --gold    : #A8821E;
  --maroon  : #7B2D42;
  --ink     : #2C1810;
  --muted   : #6B5C4A;
  --ivory   : #FEFDF7;
  --cream   : #F8F2E4;
  --border  : #E4D9C5;
  --white   : #FFFFFF;
}

/* ── Base ── */
html, body, [class*="css"] { font-family:'Inter',sans-serif !important; }

/* ── Brand hero block ── */
.brand-header {
  display:flex; align-items:center; gap:20px; padding:8px 0 2px 0;
}
.brand-name {
  font-family:'Rajdhani',sans-serif;
  font-size:2.5rem; font-weight:700;
  line-height:1.05; letter-spacing:0.5px;
}
.divya   { color:#C47629; }
.drishti { color:#7B2D42; }
.brand-sanskrit {
  font-size:.95rem; color:#A8821E;
  letter-spacing:3px; margin-top:3px; font-weight:500;
}
.brand-tagline {
  font-size:.82rem; color:#6B5C4A;
  margin-top:5px; letter-spacing:0.3px;
}

/* ── Drill level badge ── */
.badge {
  display:inline-block; padding:4px 16px; border-radius:20px;
  font-size:.78rem; font-weight:600; letter-spacing:0.4px;
  background:#F8F2E4; color:#7B2D42;
  border:1px solid #E4D9C5; margin-bottom:10px;
}

/* ── Aggregation warning ── */
.agg-warn {
  padding:8px 14px; background:#FFF8EC;
  border-left:4px solid #C47629;
  border-radius:4px; font-size:.82rem;
  color:#7D5A00; margin-bottom:10px;
}

/* ── KPI metric cards ── */
div[data-testid="metric-container"] {
  background:#FFFFFF;
  border-left:4px solid #C47629;
  border-radius:8px; padding:8px 12px;
  box-shadow:0 2px 8px rgba(196,118,41,0.10);
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] > div:first-child {
  background:#F8F2E4 !important;
}

/* ── Sidebar brand header ── */
.sidebar-brand {
  text-align:center; padding:4px 0 8px 0;
}
.sidebar-brand-name {
  font-family:'Rajdhani',sans-serif;
  font-size:1.55rem; font-weight:700; letter-spacing:0.5px;
}
.sidebar-brand-sub {
  font-size:.7rem; color:#6B5C4A; letter-spacing:1.5px; margin-top:2px;
}

/* ── Primary button ── */
.stButton > button[kind="primary"] {
  background:linear-gradient(135deg,#C47629,#7B2D42) !important;
  border:none !important; color:white !important;
  font-family:'Rajdhani',sans-serif !important;
  font-weight:600 !important; letter-spacing:0.5px;
  border-radius:6px !important;
}
.stButton > button[kind="primary"]:hover {
  filter:brightness(1.08);
  box-shadow:0 4px 14px rgba(123,45,66,0.3) !important;
}

/* ── Secondary buttons ── */
.stButton > button:not([kind="primary"]) {
  border:1.5px solid #E4D9C5 !important;
  font-family:'Rajdhani',sans-serif !important;
  font-weight:600 !important; letter-spacing:0.3px;
  border-radius:6px !important; color:#2C1810 !important;
}

/* ── Table header ── */
.stDataFrame thead tr th {
  background:#F8F2E4 !important;
  font-family:'Rajdhani',sans-serif !important;
  font-weight:600; letter-spacing:0.3px;
  color:#7B2D42 !important;
}

/* ── Dividers ── */
hr { border-color:#E4D9C5 !important; opacity:0.7; }
</style>
""", unsafe_allow_html=True)

# ─── Load data (cached) ────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def get_data() -> pd.DataFrame:
    return load_enterprise_tender_stream()

@st.cache_data(ttl=3600, show_spinner=False)
def get_hierarchy(_df: pd.DataFrame) -> dict:
    return get_full_hierarchy(_df)

with st.spinner("🔄 Loading enterprise tender database…"):
    df_master = get_data()

hierarchy = get_hierarchy(df_master)
all_sectors = sorted(hierarchy.keys())

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — 5-level cascading filters
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
<div class="sidebar-brand">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 56 56" width="48" height="48">
    <circle cx="28" cy="28" r="26" fill="none" stroke="#A8821E" stroke-width="1.2" opacity="0.55"/>
    <g transform="translate(28,28)" opacity="0.35">
      <ellipse cx="0" cy="-12" rx="3.5" ry="8" fill="#C47629"/>
      <ellipse cx="0" cy="-12" rx="3.5" ry="8" fill="#C47629" transform="rotate(45)"/>
      <ellipse cx="0" cy="-12" rx="3.5" ry="8" fill="#A8821E" transform="rotate(90)"/>
      <ellipse cx="0" cy="-12" rx="3.5" ry="8" fill="#A8821E" transform="rotate(135)"/>
      <ellipse cx="0" cy="-12" rx="3.5" ry="8" fill="#C47629" transform="rotate(180)"/>
      <ellipse cx="0" cy="-12" rx="3.5" ry="8" fill="#C47629" transform="rotate(225)"/>
      <ellipse cx="0" cy="-12" rx="3.5" ry="8" fill="#A8821E" transform="rotate(270)"/>
      <ellipse cx="0" cy="-12" rx="3.5" ry="8" fill="#A8821E" transform="rotate(315)"/>
    </g>
    <path d="M6,28 Q28,12 50,28 Q28,44 6,28 Z" fill="#FFFBF0"/>
    <path d="M6,28 Q28,12 50,28 Q28,44 6,28 Z" fill="none" stroke="#7B2D42" stroke-width="1.5"/>
    <defs>
      <radialGradient id="sb-iris" cx="50%" cy="50%">
        <stop offset="0%" stop-color="#C47629"/>
        <stop offset="100%" stop-color="#8B5E14"/>
      </radialGradient>
    </defs>
    <circle cx="28" cy="28" r="10" fill="url(#sb-iris)"/>
    <circle cx="28" cy="28" r="5.5" fill="#7B2D42"/>
    <circle cx="28" cy="28" r="2" fill="#A8821E"/>
    <circle cx="28" cy="28" r="0.9" fill="#FFFBF0"/>
    <path d="M6,28 Q28,13 50,28" fill="none" stroke="#A8821E" stroke-width="0.9" opacity="0.5"/>
    <ellipse cx="28" cy="17" rx="2.5" ry="3.8" fill="#C47629" opacity="0.9"/>
    <ellipse cx="28" cy="17" rx="1.2" ry="2" fill="#A8821E"/>
  </svg>
  <div class="sidebar-brand-name">
    <span class="divya">Divya</span><span class="drishti">Drishti</span>
  </div>
  <div class="sidebar-brand-sub">DIVINE PROCUREMENT VISION</div>
</div>
""", unsafe_allow_html=True)
    st.caption(f"**{len(df_master):,}** tenders · {df_master['state'].nunique()} states · 12 sectors")
    st.markdown("---")

    # ── Global keyword search ─────────────────────────────────────────────────
    st.markdown("#### 🔍 Global Search")
    search_query = st.text_input(
        "", placeholder="Search by title, dept, tender ID…",
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown("#### 📊 Drill-Down Filters")

    # ── Level 1: Sector ────────────────────────────────────────────────────────
    selected_sector = st.selectbox("Sector", [ALL] + all_sectors)

    # ── Level 2: Department (cascades from sector) ─────────────────────────────
    if selected_sector != ALL:
        dept_options = [ALL] + sorted(hierarchy[selected_sector].keys())
    else:
        # Flatten all departments across all sectors
        all_depts = sorted({d for s in hierarchy for d in hierarchy[s]})
        dept_options = [ALL] + all_depts
    selected_dept = st.selectbox("Department", dept_options)

    # ── Level 3: State ─────────────────────────────────────────────────────────
    if selected_sector != ALL and selected_dept != ALL:
        state_options = [ALL] + sorted(hierarchy[selected_sector][selected_dept].keys())
    elif selected_sector != ALL:
        state_options = [ALL] + sorted({
            s for d in hierarchy[selected_sector].values() for s in d
        })
    else:
        state_options = [ALL] + sorted(df_master["state"].unique())
    selected_state = st.selectbox("State / UT", state_options)

    # ── Level 4: District ──────────────────────────────────────────────────────
    if selected_state != ALL:
        if selected_sector != ALL and selected_dept != ALL:
            raw_districts = hierarchy[selected_sector][selected_dept].get(selected_state, {})
        elif selected_sector != ALL:
            raw_districts = {
                d: blocks
                for dept_data in hierarchy[selected_sector].values()
                for d, blocks in dept_data.get(selected_state, {}).items()
            }
        else:
            raw_districts = {
                d: [] for d in sorted(df_master[df_master["state"] == selected_state]["district"].unique())
            }
        district_options = [ALL] + sorted(raw_districts.keys())
    else:
        district_options = [ALL]
    selected_district = st.selectbox("District", district_options)

    # ── Level 5: Block ─────────────────────────────────────────────────────────
    if selected_state != ALL and selected_district != ALL:
        mask_blk = (df_master["state"] == selected_state) & (df_master["district"] == selected_district)
        if selected_sector != ALL:
            mask_blk &= df_master["sector"] == selected_sector
        block_options = [ALL] + sorted(df_master[mask_blk]["block"].unique())
    else:
        block_options = [ALL]
    selected_block = st.selectbox("Block / Taluka", block_options)

    st.markdown("---")
    st.markdown("#### ⚙️ Additional Filters")

    # Status filter
    all_statuses = sorted(df_master["status"].unique().tolist())
    selected_statuses = st.multiselect("Status", all_statuses, default=all_statuses)

    # Budget range slider
    amt_min = float(df_master["allocated_amount"].min())
    amt_max = float(df_master["allocated_amount"].max())
    budget_range = st.slider(
        "Budget Range (₹ Crores)",
        min_value=amt_min, max_value=amt_max,
        value=(amt_min, min(amt_max, 500.0)),
        step=1.0, format="₹%.0f Cr",
    )

    st.markdown("---")

    with st.expander("⚙️ Advanced Settings", expanded=False):
        # Data source indicator
        from pathlib import Path
        db_exists = (Path(__file__).parent / "tenders.db").exists()
        if db_exists:
            import sqlite3
            _cnt = sqlite3.connect(Path(__file__).parent / "tenders.db").execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
            st.success(f"📡 Real Data — {_cnt:,} scraped tenders in DB")
        else:
            st.warning("🧪 Preview mode — seed data. Run scraper for real data.")

        st.markdown("#### 🔄 Run Live Scraper")
        import subprocess, sys
        _sources = st.multiselect(
            "Sources", ["cppp", "gem", "states", "datagov", "pmgsy", "cgstate", "biharv2", "up_misc", "up_power", "up_sectors"],
            default=["cppp", "gem"],
            help=(
                "cppp=Central portal, gem=GeM bids, "
                "states=all 34 state/UT NIC portals (full India coverage), "
                "datagov=data.gov.in API, "
                "pmgsy=PMGSY rural road portal (block/panchayat level), "
                "cgstate=Chhattisgarh CHEPS RFQ portal, "
                "biharv2=Bihar EPS v2 portal (all tender tabs), "
                "up_misc=UP custom portals: Jal Nigam (7,500+ tenders), UPEIDA expressways, State Bridge Corp, "
                "up_power=UP power distribution: PVVNL (Western UP) + MVVNL (Central/Lucknow) — Energy sector, "
                "up_sectors=UP Health/MSME/SocialWelfare/IT — etender.up.nic.in dept portals + UPMSC"
            ),
        )
        _pages   = st.number_input("Pages per portal", min_value=1, max_value=200, value=10)
        _api_key = st.text_input("data.gov.in API Key", type="password",
                                  placeholder="Required only for 'datagov' source")

        if st.button("▶ Start Scraping", type="primary", use_container_width=True):
            cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"),
                   "--sources"] + _sources + ["--pages", str(_pages)]
            if _api_key:
                cmd += ["--api-key", _api_key]
            with st.spinner("Scraping live portals… (may take several minutes)"):
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                st.success("✅ Scraping complete — refreshing data")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Scraper error — check logs")
                st.code((result.stderr or result.stdout)[-3000:])

        if st.button("🔄 Refresh Display", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        # ── Entity Geocoder ───────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 🌐 Entity Geocoder")
        st.caption("Replaces district-centre placement with real OSM coords for hospitals, "
                   "schools, road A→B endpoints. Uses Nominatim — ~1 record/sec.")
        _enrich_limit = st.number_input(
            "Records to enrich (per run)",
            min_value=10, max_value=2000, value=200, step=50,
        )
        if st.button("🌐 Run Entity Geocoding", use_container_width=True):
            if not (Path(__file__).parent / "tenders.db").exists():
                st.warning("No tenders.db found. Run the scraper first.")
            else:
                cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"),
                       "--enrich-entities", "--enrich-limit", str(_enrich_limit)]
                sub_timeout = min(5400, max(120, _enrich_limit * 3))
                with st.spinner(
                    f"Geocoding ~{_enrich_limit} records (≈ {int(sub_timeout/60)} min). "
                    f"Cache makes repeats free."
                ):
                    try:
                        result = subprocess.run(cmd, capture_output=True, text=True,
                                                 timeout=sub_timeout)
                    except subprocess.TimeoutExpired:
                        st.warning(
                            f"⏱️ UI timeout reached. Partial progress saved to "
                            f"tenders.db. Reload to see results, or run in terminal "
                            f"for larger batches."
                        )
                        st.cache_data.clear()
                        st.stop()
                if result.returncode == 0:
                    st.success("✅ Entity geocoding complete")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Enrichment failed — see logs")
                    st.code((result.stderr or result.stdout)[-2500:])

        # ── Reclassifier ──────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 🔍 Re-classify Sector / Location")
        st.caption("Reads each tender's title + department text and replaces "
                   "'Other'/'Unknown' with proper sector, state, district, block. "
                   "Runs offline (no network) — takes seconds.")
        if st.button("🔍 Reclassify Database", use_container_width=True):
            if not (Path(__file__).parent / "tenders.db").exists():
                st.warning("No tenders.db found. Run the scraper first.")
            else:
                cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"), "--reclassify"]
                with st.spinner("Reclassifying records…"):
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode == 0:
                    st.success("✅ Reclassification complete")
                    st.code(result.stdout[-500:])
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Reclassify failed")
                    st.code((result.stderr or result.stdout)[-2500:])

        # ── Deep Scrape ───────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 📄 Deep Scrape (Contract Text)")
        st.caption("For each tender, visits the portal's detail page, reads the "
                   "FULL work description + scope of work, then re-classifies "
                   "sector/state/district from the richer content. Slow (~1.5s "
                   "per record) but most accurate.")
        _deep_limit = st.number_input(
            "Detail pages to fetch", min_value=10, max_value=2000, value=100, step=20,
        )
        st.caption(
            f"⚠️ For large batches (>100), prefer terminal: "
            f"`python3 scraper_v3.py --deep-scrape --deep-limit {_deep_limit}` — "
            f"avoids browser UI timeout."
        )
        if st.button("📄 Run Deep Scrape", use_container_width=True):
            if not (Path(__file__).parent / "tenders.db").exists():
                st.warning("No tenders.db found. Run the scraper first.")
            else:
                cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"),
                       "--deep-scrape", "--deep-limit", str(_deep_limit)]
                sub_timeout = min(5400, max(300, _deep_limit * 12))
                est_min = int(sub_timeout / 60)
                with st.spinner(
                    f"Visiting ~{_deep_limit} detail pages — timeout {est_min} min. "
                    f"Progress saved every 20 records, so partial completion is OK."
                ):
                    try:
                        result = subprocess.run(cmd, capture_output=True, text=True,
                                                 timeout=sub_timeout)
                    except subprocess.TimeoutExpired:
                        st.warning(
                            f"⏱️ Subprocess hit {est_min}-min UI timeout. "
                            f"Partial progress saved to tenders.db (records are "
                            f"committed every 20 pages). Reload to see the data, "
                            f"or run in terminal for unbounded runtime."
                        )
                        st.cache_data.clear()
                        st.stop()

                if result.returncode == 0:
                    st.success("✅ Deep scrape complete")
                    st.code(result.stdout[-1000:])
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Deep scrape failed")
                    st.code((result.stderr or result.stdout)[-2500:])

        # ── UP Project Value Enrichment ────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 💰 UP Project Value Enrichment")
        st.caption("Extracts ₹ Estimated Cost from UP Jal Nigam NIT PDFs and saves to DB. "
                   "~60% success rate on recent tenders. Run repeatedly to cover all records.")
        _up_limit = st.number_input(
            "UPJN tenders to enrich", min_value=10, max_value=500, value=100, step=50,
        )
        if st.button("💰 Extract UP Project Values", use_container_width=True):
            if not (Path(__file__).parent / "tenders.db").exists():
                st.warning("No tenders.db found. Run the scraper first.")
            else:
                cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"),
                       "--up-deep", "--up-deep-limit", str(_up_limit)]
                est_min = max(3, int(_up_limit * 2.5 / 60))
                with st.spinner(f"Fetching {_up_limit} UPJN PDFs (≈ {est_min} min)…"):
                    try:
                        result = subprocess.run(cmd, capture_output=True, text=True,
                                                timeout=max(180, _up_limit * 3))
                    except subprocess.TimeoutExpired:
                        st.warning("⏱️ Timeout — partial progress saved. Reload to see results.")
                        st.cache_data.clear()
                        st.stop()
                if result.returncode == 0:
                    st.success("✅ UP enrichment complete")
                    st.code(result.stdout[-500:])
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Enrichment failed")
                    st.code((result.stderr or result.stdout)[-1500:])

        # ── UP Power Amount Enrichment (PVVNL / MVVNL) ────────────────────────
        st.markdown("---")
        st.markdown("#### ⚡ UP Power Tender Amounts")
        st.caption(
            "Downloads each PVVNL/MVVNL tender document, OCRs page 1, extracts "
            "Earnest Money Deposit (EMD) and computes Estimated Cost = EMD ÷ 0.02."
        )
        if st.button("⚡ Extract UP Power Project Values", use_container_width=True):
            if not (Path(__file__).parent / "tenders.db").exists():
                st.warning("No tenders.db found. Run the scraper first.")
            else:
                cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"),
                       "--enrich-power"]
                with st.spinner("Downloading & OCR-ing PVVNL/MVVNL tender PDFs…"):
                    try:
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                    except subprocess.TimeoutExpired:
                        st.warning("⏱️ Timeout — partial progress saved.")
                        st.cache_data.clear()
                        st.stop()
                if result.returncode == 0:
                    st.success("✅ UP Power enrichment complete")
                    st.code(result.stdout[-800:])
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Enrichment failed")
                    st.code((result.stderr or result.stdout)[-1500:])

        st.markdown("---")
        if st.button("🏥 Scrape UP Health / MSME / Social Welfare / IT", use_container_width=True):
            if not (Path(__file__).parent / "tenders.db").exists():
                st.warning("No tenders.db found. Run the scraper first.")
            else:
                cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"),
                       "--scrape-up-sectors"]
                with st.spinner("Fetching UP sector tenders from etender.up.nic.in & upmsc.in…"):
                    try:
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    except subprocess.TimeoutExpired:
                        st.warning("⏱️ Timeout — partial progress saved.")
                        st.cache_data.clear()
                        st.stop()
                if result.returncode == 0:
                    st.success("✅ UP sector scrape complete")
                    st.code(result.stdout[-1200:])
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Scrape failed")
                    st.code((result.stderr or result.stdout)[-1500:])

        st.markdown("---")
        st.markdown("**🗺️ Multi-State GePNIC Scraper** (active tenders, all depts)")
        _gepnic_states_available = [
            # Already have data
            "Uttar Pradesh", "Rajasthan", "Madhya Pradesh", "Maharashtra",
            "Odisha", "Haryana", "West Bengal", "Tamil Nadu", "Central (CPPP)",
            # New: North-east
            "Arunachal Pradesh", "Assam", "Manipur", "Meghalaya",
            "Mizoram", "Nagaland", "Tripura",
            # New: Other states
            "Goa", "Himachal Pradesh", "Jharkhand", "Kerala", "Punjab",
            # New: Union Territories
            "Delhi", "Jammu & Kashmir", "Chandigarh", "Andaman & Nicobar",
            "Dadra & Nagar Haveli", "Daman & Diu", "Puducherry", "Lakshadweep",
            # GePNIC confirmed (previously thought non-GePNIC)
            "Uttarakhand", "Sikkim",
        ]
        _sel_states = st.multiselect(
            "States to scrape", _gepnic_states_available,
            default=[], key="gepnic_state_sel",
            help="Scrapes ALL government departments for selected states from NIC portals"
        )
        _col_g1, _col_g2 = st.columns(2)
        if _col_g1.button("🌏 Scrape Selected States", use_container_width=True, key="gepnic_sel_btn"):
            if not _sel_states:
                st.warning("Select at least one state above.")
            else:
                cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"),
                       "--gepnic-states"] + _sel_states
                with st.spinner(f"Scraping {', '.join(_sel_states)}… (may take 5–20 min)"):
                    try:
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                    except subprocess.TimeoutExpired:
                        st.warning("⏱️ Timeout — partial progress saved.")
                        st.cache_data.clear()
                        st.stop()
                if result.returncode == 0:
                    st.success("✅ GePNIC scrape complete")
                    st.code(result.stdout[-1500:])
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Scrape failed")
                    st.code((result.stderr or result.stdout)[-1500:])
        if _col_g2.button("🌍 Scrape ALL States & UTs", use_container_width=True, key="gepnic_all_btn"):
            cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"),
                   "--gepnic-states", "all"]
            with st.spinner("Scraping all states & UTs… (60–120 min)"):
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
                except subprocess.TimeoutExpired:
                    st.warning("⏱️ Timeout — partial progress saved.")
                    st.cache_data.clear()
                    st.stop()
            if result.returncode == 0:
                st.success("✅ All states scraped")
                st.code(result.stdout[-1500:])
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Scrape failed")
                st.code((result.stderr or result.stdout)[-1500:])

        st.markdown("---")
        st.markdown("**🗺️ Non-GePNIC State Scrapers** (Karnataka · AP · Telangana · Gujarat)")
        _ncol1, _ncol2, _ncol3, _ncol4 = st.columns(4)
        if _ncol1.button("🏛️ Karnataka", use_container_width=True, key="ka_btn"):
            cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"), "--scrape-karnataka"]
            with st.spinner("Scraping Karnataka eProcurement…"):
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                st.success("✅ Karnataka done")
                st.cache_data.clear(); st.rerun()
            else:
                st.error("Failed"); st.code((result.stderr or result.stdout)[-1000:])
        if _ncol2.button("🏛️ Andhra Pradesh", use_container_width=True, key="ap_btn"):
            cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"), "--scrape-ap"]
            with st.spinner("Scraping AP eProcurement…"):
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                st.success("✅ AP done")
                st.cache_data.clear(); st.rerun()
            else:
                st.error("Failed"); st.code((result.stderr or result.stdout)[-1000:])
        if _ncol3.button("🏛️ Telangana", use_container_width=True, key="ts_btn"):
            cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"), "--scrape-telangana"]
            with st.spinner("Scraping Telangana eProcurement…"):
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                st.success("✅ Telangana done")
                st.cache_data.clear(); st.rerun()
            else:
                st.error("Failed"); st.code((result.stderr or result.stdout)[-1000:])
        if _ncol4.button("🏛️ Gujarat", use_container_width=True, key="gj_btn"):
            cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"), "--scrape-gujarat"]
            with st.spinner("Scraping Gujarat nProcure (~4k tenders)…"):
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
            if result.returncode == 0:
                st.success("✅ Gujarat done")
                st.cache_data.clear(); st.rerun()
            else:
                st.error("Failed"); st.code((result.stderr or result.stdout)[-1000:])

        # ── Data Source Health ─────────────────────────────────────────────────
        st.markdown("---")
        with st.expander("🩺 Data Source Health", expanded=False):
            _health = load_health_log()
            if _health is None or _health.empty:
                st.caption("No scraping attempts logged yet. Run the scraper to populate.")
            else:
                _ok   = _health[_health["status"] == "success"]
                _fail = _health[_health["status"] == "failed"]

                hc1, hc2 = st.columns(2)
                hc1.metric("✅ Reachable", len(_ok))
                hc2.metric("❌ Blocked / Down", len(_fail))

                if not _fail.empty:
                    st.markdown("**Failed domains** — could not scrape:")
                    for _, row in _fail.iterrows():
                        st.markdown(
                            f"<small>🔴 **{row['source']}** — `{row['error_code']}`<br>"
                            f"<span style='color:#888'>{row['domain']}</span></small>",
                            unsafe_allow_html=True,
                        )

                if not _ok.empty:
                    st.markdown("**Reachable** sources:")
                    for _, row in _ok.iterrows():
                        st.markdown(
                            f"<small>🟢 **{row['source']}** — {row['records_fetched']:,} records</small>",
                            unsafe_allow_html=True,
                        )

                st.caption(f"Last update: {_health['logged_at'].max()}")


# ─────────────────────────────────────────────────────────────────────────────
# APPLY FILTERS
# ─────────────────────────────────────────────────────────────────────────────
df = df_master.copy()

# Cascading filters
if selected_sector != ALL:
    df = df[df["sector"] == selected_sector]
if selected_dept != ALL:
    df = df[df["department"] == selected_dept]
if selected_state != ALL:
    df = df[df["state"] == selected_state]
if selected_district != ALL:
    df = df[df["district"] == selected_district]
if selected_block != ALL:
    df = df[df["block"] == selected_block]

# Additional filters
df = df[
    df["status"].isin(selected_statuses) &
    df["allocated_amount"].between(budget_range[0], budget_range[1])
]

# Global keyword search (applied last)
if search_query.strip():
    q = search_query.strip().lower()
    mask = (
        df["title"].str.lower().str.contains(q, na=False) |
        df["department"].str.lower().str.contains(q, na=False) |
        df["tender_id"].str.lower().str.contains(q, na=False)
    )
    df = df[mask]

# ─────────────────────────────────────────────────────────────────────────────
# DRILL LEVEL DETECTION
# ─────────────────────────────────────────────────────────────────────────────
if selected_state == ALL:
    drill_level = "national"
    level_label = "🌏 National View — All States & Sectors"
elif selected_district == ALL:
    drill_level = "state"
    level_label = f"📍 State View — {selected_state}"
elif selected_block == ALL:
    drill_level = "district"
    level_label = f"🏙️ District View — {selected_district}, {selected_state}"
else:
    drill_level = "block"
    level_label = f"🔍 Block View — {selected_block}, {selected_district}"

render_mode = "scatter" if len(df) <= SCATTER_LIMIT else "aggregated"

# ─────────────────────────────────────────────────────────────────────────────
# PAGE HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="brand-header">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 72" width="72" height="72">
    <circle cx="36" cy="36" r="33" fill="none" stroke="#A8821E" stroke-width="1.5" opacity="0.5"/>
    <circle cx="36" cy="36" r="27" fill="none" stroke="#C47629" stroke-width="0.6" opacity="0.3"/>
    <g fill="#A8821E" opacity="0.6">
      <polygon points="36,4 38.2,8 36,12 33.8,8" transform="rotate(0,36,36)"/>
      <polygon points="36,4 38.2,8 36,12 33.8,8" transform="rotate(45,36,36)"/>
      <polygon points="36,4 38.2,8 36,12 33.8,8" transform="rotate(90,36,36)"/>
      <polygon points="36,4 38.2,8 36,12 33.8,8" transform="rotate(135,36,36)"/>
      <polygon points="36,4 38.2,8 36,12 33.8,8" transform="rotate(180,36,36)"/>
      <polygon points="36,4 38.2,8 36,12 33.8,8" transform="rotate(225,36,36)"/>
      <polygon points="36,4 38.2,8 36,12 33.8,8" transform="rotate(270,36,36)"/>
      <polygon points="36,4 38.2,8 36,12 33.8,8" transform="rotate(315,36,36)"/>
    </g>
    <g transform="translate(36,36)" opacity="0.3">
      <ellipse cx="0" cy="-15" rx="4.5" ry="10" fill="#C47629"/>
      <ellipse cx="0" cy="-15" rx="4.5" ry="10" fill="#A8821E" transform="rotate(45)"/>
      <ellipse cx="0" cy="-15" rx="4.5" ry="10" fill="#C47629" transform="rotate(90)"/>
      <ellipse cx="0" cy="-15" rx="4.5" ry="10" fill="#A8821E" transform="rotate(135)"/>
      <ellipse cx="0" cy="-15" rx="4.5" ry="10" fill="#C47629" transform="rotate(180)"/>
      <ellipse cx="0" cy="-15" rx="4.5" ry="10" fill="#A8821E" transform="rotate(225)"/>
      <ellipse cx="0" cy="-15" rx="4.5" ry="10" fill="#C47629" transform="rotate(270)"/>
      <ellipse cx="0" cy="-15" rx="4.5" ry="10" fill="#A8821E" transform="rotate(315)"/>
    </g>
    <path d="M8,36 Q36,14 64,36 Q36,58 8,36 Z" fill="#FFFBF0"/>
    <path d="M8,36 Q36,14 64,36 Q36,58 8,36 Z" fill="none" stroke="#7B2D42" stroke-width="1.8"/>
    <defs>
      <radialGradient id="hero-iris" cx="40%" cy="40%">
        <stop offset="0%" stop-color="#D4902E"/>
        <stop offset="100%" stop-color="#7B5010"/>
      </radialGradient>
    </defs>
    <circle cx="36" cy="36" r="13" fill="url(#hero-iris)"/>
    <circle cx="36" cy="36" r="7.5" fill="#7B2D42"/>
    <circle cx="36" cy="36" r="3" fill="#A8821E"/>
    <circle cx="36" cy="36" r="1.2" fill="#FFFBF0"/>
    <circle cx="33" cy="33" r="1.2" fill="rgba(255,251,240,0.4)"/>
    <path d="M8,36 Q36,15 64,36" fill="none" stroke="#A8821E" stroke-width="1.2" opacity="0.4"/>
    <ellipse cx="36" cy="21" rx="3.2" ry="5" fill="#C47629" opacity="0.95"/>
    <ellipse cx="36" cy="21" rx="1.6" ry="2.8" fill="#A8821E"/>
    <circle cx="36" cy="21" rx="0.7" fill="#FFFBF0" opacity="0.8"/>
  </svg>
  <div>
    <div class="brand-name"><span class="divya">Divya</span><span class="drishti">Drishti</span></div>
    <div class="brand-sanskrit">दिव्यदृष्टि</div>
    <div class="brand-tagline">Pan-India Procurement Intelligence · 12 Sectors · {df_master['state'].nunique()} States/UTs · All Administrative Tiers</div>
  </div>
</div>
<span class="badge">{level_label}</span>
""", unsafe_allow_html=True)
st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# EMPTY STATE GUARD
# ─────────────────────────────────────────────────────────────────────────────
if df.empty:
    st.warning("⚠️ No tenders match the current filter combination. Please broaden your selection.")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# KPI CARDS — dynamically recalculate at every level
# ─────────────────────────────────────────────────────────────────────────────
total_funds   = float(df["allocated_amount"].sum())
active_count  = int((df["status"] == "Active").sum())
avg_cost      = float(df["allocated_amount"].mean())
top_row       = df.loc[df["allocated_amount"].idxmax()]
sector_count  = df["sector"].nunique()
dept_count    = df["department"].nunique()

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("💰 Total Budget", f"₹{total_funds:,.1f} Cr")
c2.metric("📋 Total Tenders", f"{len(df):,}",
          delta=f"{active_count} Active", delta_color="off")
c3.metric("📊 Avg per Tender", f"₹{avg_cost:,.2f} Cr")
c4.metric("🏆 Largest Tender", f"₹{float(top_row['allocated_amount']):,.1f} Cr",
          delta=str(top_row["sector"]), delta_color="off")
c5.metric("🏭 Sectors Active", f"{sector_count}")
c6.metric("🏢 Departments", f"{dept_count}")
st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# GEOCODING COVERAGE BANNER — show how many records have real entity coords
# ─────────────────────────────────────────────────────────────────────────────
# A record has "real coords" if its title contains a known facility / linear pattern
# Heuristic proxy: records with latitude2 (linear) OR district != Unknown have been resolved.
if drill_level in ("state", "district", "block") and len(df) > 0:
    coverage_known_district = (df["district"].astype(str) != "Unknown").sum()
    coverage_pct = coverage_known_district / len(df) * 100
    if coverage_pct < 100:
        st.warning(
            f"🌐 **Geocoding coverage:** {coverage_known_district:,} / {len(df):,} tenders "
            f"({coverage_pct:.0f}%) have district-level placement. "
            f"For real hospital/school/road coordinates from OSM, click "
            f"**'🌐 Run Entity Geocoding'** in the sidebar.",
            icon="ℹ️",
        )

# ─────────────────────────────────────────────────────────────────────────────
# MAP — Dual-mode adaptive rendering
# ─────────────────────────────────────────────────────────────────────────────
map_col, info_col = st.columns([4, 1])

view = get_view_config(df, selected_state if selected_state != ALL else None,
                       selected_district if selected_district != ALL else None)

with map_col:

    if render_mode == "aggregated":
        # ── AGGREGATED MODE: >5000 points → group to prevent lag ─────────────
        st.markdown(
            '<div class="agg-warn">⚡ Aggregated view active — too many points for scatter. '
            'Narrow filters to switch to deep-dive scatter mode.</div>',
            unsafe_allow_html=True,
        )

        # Group at the most meaningful level for current drill depth
        if drill_level in ("national", "state"):
            agg_col = "state"
            hover_name = "state"
        else:
            agg_col = "district"
            hover_name = "district"

        agg_df = server_side_aggregate(df, agg_col)

        # Attach state-center coordinates for national view
        if agg_col == "state":
            agg_df["lat"] = agg_df["state"].map(
                lambda s: STATE_CENTERS.get(s, {}).get("lat", 22.5)
            )
            agg_df["lon"] = agg_df["state"].map(
                lambda s: STATE_CENTERS.get(s, {}).get("lon", 82.5)
            )

        fig = px.scatter_mapbox(
            agg_df,
            lat="lat", lon="lon",
            size="total_amount",
            color="total_amount",
            color_continuous_scale="YlOrRd",
            hover_name=hover_name,
            hover_data={"total_amount": ":.1f", "count": True, "lat": False, "lon": False},
            labels={"total_amount": "₹ Crores", "count": "Tenders"},
            mapbox_style="open-street-map",
            center={"lat": view["lat"], "lon": view["lon"]},
            zoom=view["zoom"],
            size_max=60,
            height=540,
        )
        fig.update_coloraxes(colorbar_title="₹ Cr")

    else:
        # ── SCATTER MODE: ≤5000 points → individual markers ──────────────────
        df_plot = df.copy()
        a_min = float(df_plot["allocated_amount"].min())
        a_max = float(df_plot["allocated_amount"].max())
        # Diameter (pixels): 14 (min) → 38 (max). Was 10–50 with area-mode
        # which collapsed to 3–8 px diameter — invisible when many points clustered.
        size_min, size_max = 14, 38
        df_plot["bubble"] = (
            ((df_plot["allocated_amount"] - a_min) / max(a_max - a_min, 1))
            * (size_max - size_min) + size_min
        )
        df_plot["amt_fmt"] = df_plot["allocated_amount"].apply(lambda x: f"₹{x:,.2f} Cr")

        # Split linear (lat2/lon2 present) vs point geometry
        if "latitude2" in df_plot.columns:
            linear_mask = df_plot["latitude2"].notna() & df_plot["longitude2"].notna()
        else:
            linear_mask = pd.Series([False] * len(df_plot), index=df_plot.index)
        df_lines  = df_plot[linear_mask]
        df_points = df_plot[~linear_mask]
        # Use points DataFrame for the px.scatter_mapbox base layer
        df_plot = df_points if not df_points.empty else df_plot

        # Lifecycle fields may be null on partially scraped rows — coerce
        for col in ("contractor_name", "start_date", "end_date"):
            if col not in df_plot.columns:
                df_plot[col] = "—"
            df_plot[col] = df_plot[col].fillna("—").replace("", "—")

        fig = px.scatter_mapbox(
            df_plot,
            lat="latitude", lon="longitude",
            size="bubble",
            color="sector",
            color_discrete_map=SECTOR_COLORS,
            hover_name="title",
            hover_data={
                "department":      True,
                "amt_fmt":         True,
                "status":          True,
                "state":           True,
                "district":        True,
                "block":           True,
                "contractor_name": True,
                "start_date":      True,
                "end_date":        True,
                "bubble":          False,
                "latitude":        False,
                "longitude":       False,
            },
            labels={
                "amt_fmt":         "Allocated",
                "department":     "Dept",
                "status":         "Status",
                "sector":         "Sector",
                "contractor_name":"Contractor",
                "start_date":     "Start",
                "end_date":       "End",
            },
            mapbox_style="open-street-map",
            center={"lat": view["lat"], "lon": view["lon"]},
            zoom=view["zoom"],
            height=540,
        )
        # sizemode default ("diameter") — bubble value IS diameter in px
        fig.update_traces(marker=dict(opacity=0.85))

        # ── Linear features (roads / bridges / pipelines) — drawn as lines ──
        if not df_lines.empty:
            for sector, group in df_lines.groupby("sector", observed=True):
                color = SECTOR_COLORS.get(str(sector), "#888")
                # Build a single multi-line trace per sector for performance
                lat_seq, lon_seq, hover_seq = [], [], []
                for _, r in group.iterrows():
                    lat_seq.extend([float(r["latitude"]), float(r["latitude2"]), None])
                    lon_seq.extend([float(r["longitude"]), float(r["longitude2"]), None])
                # Line trace (no per-segment hover)
                fig.add_trace(go.Scattermapbox(
                    lat=lat_seq, lon=lon_seq,
                    mode="lines",
                    line=dict(width=5, color=color),
                    opacity=0.75,
                    hoverinfo="skip",
                    showlegend=False,
                    name=f"{sector} (line)",
                ))
                # Midpoint marker for hover info
                mid_lat = [(float(r["latitude"]) + float(r["latitude2"])) / 2 for _, r in group.iterrows()]
                mid_lon = [(float(r["longitude"]) + float(r["longitude2"])) / 2 for _, r in group.iterrows()]
                hover_txt = [
                    f"<b>{r['title']}</b><br>"
                    f"🏢 {r['department']}<br>"
                    f"💰 {r['amt_fmt']}<br>"
                    f"📍 {r['block']}, {r['district']}<br>"
                    f"📌 {r['status']}"
                    for _, r in group.iterrows()
                ]
                fig.add_trace(go.Scattermapbox(
                    lat=mid_lat, lon=mid_lon,
                    mode="markers",
                    marker=dict(size=10, color=color, opacity=0.95),
                    hovertext=hover_txt,
                    hoverinfo="text",
                    showlegend=False,
                    name=f"{sector} (line-anchor)",
                ))

        # ── District boundary halo — visual cue showing focus area ──────────
        if drill_level in ("district", "block") and selected_state in DISTRICT_COORDINATES:
            if selected_district in DISTRICT_COORDINATES[selected_state]:
                c = DISTRICT_COORDINATES[selected_state][selected_district]
                # Approximate district radius (~25 km for most Indian districts)
                radius_km = 25 if drill_level == "district" else 8
                # 1° lat ≈ 111 km; 1° lon ≈ 111 km × cos(lat)
                r_lat = radius_km / 111.0
                r_lon = radius_km / (111.0 * math.cos(math.radians(c["lat"])))
                circle_lats = [c["lat"] + r_lat * math.sin(t) for t in np.linspace(0, 2*math.pi, 60)]
                circle_lons = [c["lon"] + r_lon * math.cos(t) for t in np.linspace(0, 2*math.pi, 60)]
                fig.add_trace(go.Scattermapbox(
                    lat=circle_lats, lon=circle_lons,
                    mode="lines",
                    line=dict(width=2, color="rgba(196, 118, 41, 0.6)"),
                    fill="toself",
                    fillcolor="rgba(196, 118, 41, 0.06)",
                    hoverinfo="skip",
                    showlegend=False,
                    name=f"{selected_district} boundary",
                ))
                # Marker at district centre
                fig.add_trace(go.Scattermapbox(
                    lat=[c["lat"]], lon=[c["lon"]],
                    mode="markers+text",
                    marker=dict(size=14, color="#7B2D42", symbol="circle"),
                    text=[f"📍 {selected_district}"],
                    textposition="top right",
                    textfont=dict(size=11, color="#7B2D42"),
                    hoverinfo="skip",
                    showlegend=False,
                ))

    fig.update_layout(
        margin=dict(l=0, r=0, t=5, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1,
                    font=dict(size=11)),
    )
    st.plotly_chart(fig, use_container_width=True)

with info_col:
    st.markdown("#### 📌 View Info")
    st.markdown(f"**Mode:** `{render_mode}`")
    st.markdown(f"**Records:** `{len(df):,}`")
    st.markdown(f"**Scatter limit:** `{SCATTER_LIMIT:,}`")
    st.markdown("---")

    if render_mode == "scatter":
        st.markdown("**Sectors shown**")
        for sec in sorted(df["sector"].unique()):
            color = SECTOR_COLORS.get(sec, "#999")
            cnt = int((df["sector"] == sec).sum())
            st.markdown(
                f'<span style="background:{color};border-radius:50%;display:inline-block;'
                f'width:10px;height:10px;margin-right:5px;"></span>{sec[:14]} ({cnt})',
                unsafe_allow_html=True,
            )
    else:
        # Top spending areas
        grp = "state" if drill_level in ("national","state") else "district"
        top5 = df.groupby(grp)["allocated_amount"].sum().nlargest(5)
        st.markdown(f"**Top {grp.capitalize()}s**")
        for name, amt in top5.items():
            st.caption(f"{str(name)[:18]}: ₹{amt:,.0f} Cr")

    st.markdown("---")
    st.markdown("**Status**")
    for s, col in STATUS_COLORS.items():
        cnt = int((df["status"] == s).sum())
        if cnt:
            st.markdown(
                f'<span style="color:{col};font-weight:700;">●</span> {s}: {cnt:,}',
                unsafe_allow_html=True,
            )

# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS GRID — 4 charts
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
ch1, ch2, ch3, ch4 = st.columns(4)

# Chart 1: Funds by Sector
with ch1:
    st.markdown("**💹 Budget by Sector**")
    sec_df = (
        df.groupby("sector")["allocated_amount"].sum()
        .reset_index().rename(columns={"allocated_amount": "₹ Cr"})
        .sort_values("₹ Cr", ascending=True)
    )
    fig1 = px.bar(
        sec_df, x="₹ Cr", y="sector", orientation="h",
        color="sector", color_discrete_map=SECTOR_COLORS,
        text_auto=".0f", height=320,
    )
    fig1.update_layout(showlegend=False, margin=dict(t=5,b=5,l=5,r=5),
                       yaxis=dict(tickfont=dict(size=10)))
    st.plotly_chart(fig1, use_container_width=True)

# Chart 2: Status donut
with ch2:
    st.markdown("**📊 Status Split**")
    stat_df = df["status"].value_counts().reset_index()
    stat_df.columns = ["Status", "Count"]
    fig2 = px.pie(
        stat_df, names="Status", values="Count",
        color="Status", color_discrete_map=STATUS_COLORS,
        hole=0.5, height=320,
    )
    fig2.update_traces(textposition="outside", textinfo="percent+label")
    fig2.update_layout(showlegend=False, margin=dict(t=5,b=5,l=5,r=5))
    st.plotly_chart(fig2, use_container_width=True)

# Chart 3: Top Departments by spend
with ch3:
    st.markdown("**🏢 Top Departments**")
    dept_df = (
        df.groupby("department")["allocated_amount"].sum()
        .nlargest(8).reset_index()
        .rename(columns={"allocated_amount": "₹ Cr", "department": "Dept"})
        .sort_values("₹ Cr")
    )
    dept_df["Dept"] = dept_df["Dept"].str[:28]
    fig3 = px.bar(
        dept_df, x="₹ Cr", y="Dept", orientation="h",
        text_auto=".0f", height=320,
        color="₹ Cr", color_continuous_scale=["#F8E8CC", "#C47629", "#7B2D42"],
    )
    fig3.update_layout(showlegend=False, coloraxis_showscale=False,
                       margin=dict(t=5,b=5,l=5,r=5),
                       yaxis=dict(tickfont=dict(size=9)))
    st.plotly_chart(fig3, use_container_width=True)

# Chart 4: Amount distribution histogram
with ch4:
    st.markdown("**📈 Budget Distribution**")
    fig4 = px.histogram(
        df, x="allocated_amount", nbins=40,
        color_discrete_sequence=["#C47629"],
        labels={"allocated_amount": "₹ Crores"},
        height=320,
    )
    fig4.update_layout(margin=dict(t=5,b=5,l=5,r=5),
                       yaxis_title="Tenders", bargap=0.05)
    st.plotly_chart(fig4, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# SEARCHABLE PAGINATED DATA TABLE
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(f"### 📄 Tender Records — {len(df):,} results")

TABLE_COLS = {
    "tender_id":        "Tender ID",
    "title":            "Project Title",
    "sector":           "Sector",
    "department":       "Department",
    "allocated_amount": "₹ Crores",
    "state":            "State",
    "district":         "District",
    "block":            "Block",
    "status":           "Status",
    "contractor_name":  "Contractor",
    "start_date":       "Start Date",
    "end_date":         "End Date",
}

# Ensure new lifecycle columns exist even if loaded from older sources
for _c in ("contractor_name", "start_date", "end_date"):
    if _c not in df.columns:
        df[_c] = "—"
    df[_c] = df[_c].fillna("—").replace("", "—")

# Pagination
PAGE_SIZE = 200
total_pages = max(1, (len(df) - 1) // PAGE_SIZE + 1)

pcol1, pcol2, pcol3 = st.columns([2, 1, 2])
with pcol2:
    page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1)

start = (page - 1) * PAGE_SIZE
end   = start + PAGE_SIZE

df_page = (
    df.iloc[start:end][list(TABLE_COLS.keys())]
    .rename(columns=TABLE_COLS)
    .copy()
)
df_page["₹ Crores"] = df_page["₹ Crores"].apply(lambda x: f"₹{x:,.2f}")
st.caption(f"Showing rows {start+1}–{min(end, len(df))} of {len(df):,}   |   Page {page} / {total_pages}")

st.dataframe(df_page, use_container_width=True, height=380, hide_index=True)

# Download full filtered set
csv_data = (
    df[list(TABLE_COLS.keys())]
    .rename(columns=TABLE_COLS)
    .to_csv(index=False)
)
dl1, dl2 = st.columns([1, 4])
with dl1:
    st.download_button(
        "⬇️ Download CSV",
        data=csv_data,
        file_name=f"divyadrishti_tenders_{drill_level}.csv",
        mime="text/csv",
        use_container_width=True,
    )
with dl2:
    st.caption(f"Full filtered dataset: {len(df):,} rows · {len(TABLE_COLS)} columns")
