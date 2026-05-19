"""
DivyaDrishti — Divine Procurement Intelligence Engine  v4.0
Pan-India Public Expenditure & Tender Analytics · दिव्यदृष्टि

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VISUALIZATION REQUIREMENTS  (v4.0)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
R-01  Auto-Narrative Engine
      Generate 4–5 sentence contextual insight from current filter state.
      Surfaces top spender, dominant sector, outlier districts, latest portal.

R-02  KPI Pulse Strip
      6 metric cards with colour-coded borders + delta indicators.

R-03  Dual-Mode Adaptive Map
      Scatter (≤5000 pts) ↔ Aggregated bubble (>5000 pts).
      Linear features drawn as coloured lines with midpoint hover.

R-04  Treemap Intelligence
      Hierarchical area view: State → Sector → spend.
      Instantly shows WHERE money concentrates across 42k+ tenders.

R-05  Sankey Budget Flow
      Source Portal → State → Sector money river.
      Reveals which portals fund which states and which sectors.

R-06  Sector × State Heatmap Matrix
      Grid (top states × 12 sectors) coloured by ₹ crores.
      Spot under-invested sectors in any state at a glance.

R-07  Bubble Pack by Sector
      Packed circles — sector size = total budget.
      Gives visceral sense of relative sector weight.

R-08  Source Portal Contribution Ring
      Which scraping source contributes how many tenders and what ₹ value.

R-09  Budget Waterfall
      Cumulative step-down from grand total to each sector contribution.

R-10  Timeline Pulse
      Tender activity area chart by start_date/scraped_at.
      Shows procurement velocity through the year.

R-11  Top-N Leader Boards
      Fast ranked-bar charts: departments, states, contractors.

R-12  Insight Spotlight Cards
      Auto-computed: 🏆 Top State · 🔥 Hottest Sector · 💎 Biggest Tender · 🆕 Latest Source

R-13  Paginated Data Vault
      Full filtered table + CSV download + portal health log.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from pipeline import (
    DISTRICT_COORDINATES,
    SECTOR_COLORS,
    SECTOR_DEPARTMENTS,
    STATE_CENTERS,
    get_full_hierarchy,
    get_view_config,
    load_enterprise_tender_stream,
    load_health_log,
    server_side_aggregate,
)

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DivyaDrishti — Procurement Intelligence",
    page_icon="🪷",
    layout="wide",
    initial_sidebar_state="expanded",
)

ALL = "All"
SCATTER_LIMIT = 5_000
STATUS_COLORS = {"Active": "#2E7D52", "Awarded": "#C47629", "Completed": "#1A4A7A"}

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap');

:root {
  --saffron:#C47629; --gold:#A8821E; --maroon:#7B2D42;
  --ink:#2C1810;     --muted:#6B5C4A; --ivory:#FEFDF7;
  --cream:#F8F2E4;   --border:#E4D9C5;
}
html, body, [class*="css"] { font-family:'Inter',sans-serif !important; }

/* ── Brand header ── */
.brand-name { font-family:'Rajdhani',sans-serif; font-size:2.4rem;
              font-weight:700; line-height:1.05; letter-spacing:0.5px; }
.divya   { color:#C47629; }
.drishti { color:#7B2D42; }
.brand-sanskrit { font-size:.9rem; color:#A8821E; letter-spacing:3px; margin-top:3px; }
.brand-tagline  { font-size:.78rem; color:#6B5C4A; margin-top:4px; }

/* ── KPI cards ── */
div[data-testid="metric-container"] {
  background:linear-gradient(145deg,#FEFDF7,#F5EDD8);
  border:1px solid #E4D9C5; border-radius:12px; padding:14px 18px;
  border-left:4px solid var(--saffron);
}

/* ── Insight narrative card ── */
.insight-card {
  background:linear-gradient(135deg,#FFFBF2,#FFF3E0);
  border:1px solid #E8D5B0; border-left:5px solid #C47629;
  border-radius:12px; padding:18px 22px; margin:12px 0;
}
.insight-card h4 { color:#7B2D42; margin:0 0 8px 0; font-size:1rem; }
.insight-card p  { color:#3D2B1A; line-height:1.65; margin:0; font-size:.88rem; }

/* ── Spotlight cards ── */
.spotlight-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:14px 0; }
.spotlight      { background:#FEFDF7; border:1px solid #E4D9C5; border-radius:14px;
                  padding:16px 18px; text-align:center; }
.spotlight-icon { font-size:2rem; display:block; margin-bottom:6px; }
.spotlight-val  { font-family:'Rajdhani',sans-serif; font-size:1.4rem;
                  font-weight:700; color:#7B2D42; display:block; }
.spotlight-lbl  { font-size:.75rem; color:#6B5C4A; margin-top:4px; }
.spotlight-desc { font-size:.72rem; color:#9B8B78; margin-top:6px; line-height:1.4; }

/* ── Section labels ── */
.section-label {
  font-family:'Rajdhani',sans-serif; font-size:1.05rem; font-weight:600;
  color:#7B2D42; letter-spacing:0.3px; margin:4px 0 2px 0;
}
.section-desc { font-size:.78rem; color:#6B5C4A; margin-bottom:6px; line-height:1.5; }

/* ── Tab style ── */
button[data-baseweb="tab"] { font-family:'Rajdhani',sans-serif !important;
  font-size:.95rem !important; font-weight:600 !important; }

/* ── Sidebar ── */
section[data-testid="stSidebar"]>div:first-child {
  background:linear-gradient(180deg,#1C0F08 0%,#2C1810 60%,#1A0A05 100%); }
section[data-testid="stSidebar"] * { color:#F0E8D8 !important; }
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] select {
  background:#3D2416 !important; border-color:#6B4C2A !important; }

/* ── Table ── */
thead tr th { background:#7B2D42 !important; color:white !important; }

/* ── Badge ── */
.badge {
  display:inline-block; padding:3px 14px; border-radius:20px;
  background:linear-gradient(135deg,#C47629,#7B2D42);
  color:white; font-size:.78rem; font-weight:600; letter-spacing:.5px;
}

/* ── Agg warn ── */
.agg-warn { background:#FFF3CD; border:1px solid #FFEAA7; border-radius:8px;
            padding:8px 14px; font-size:.82rem; color:#7B6B3A; margin-bottom:8px; }

/* ── Waterfall positive/negative ── */
.wf-pos { color:#2E7D52; } .wf-neg { color:#C62828; }
</style>
""", unsafe_allow_html=True)

# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def get_data() -> pd.DataFrame:
    raw = load_enterprise_tender_stream()
    # Cast all object/category columns to plain str so Plotly groupby max() never
    # hits "Cannot perform max with non-ordered Categorical".
    for col in ["sector", "state", "district", "department", "source",
                "status", "contractor_name", "block", "title"]:
        if col in raw.columns:
            raw[col] = raw[col].astype(str).replace("nan", "")
    return raw

@st.cache_data(ttl=3600, show_spinner=False)
def get_hierarchy(_df: pd.DataFrame) -> dict:
    return get_full_hierarchy(_df)

with st.spinner("🔄 Loading enterprise tender database…"):
    df_master   = get_data()
    hierarchy   = get_hierarchy(df_master)
    all_sectors = sorted(df_master["sector"].dropna().unique().tolist())

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:18px 0 12px 0;text-align:center;">
      <div style="font-family:'Rajdhani',sans-serif;font-size:1.6rem;font-weight:700;
                  background:linear-gradient(135deg,#C47629,#F5C97E);
                  -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
        🪷 DivyaDrishti
      </div>
      <div style="font-size:.7rem;letter-spacing:3px;color:#C4A882;margin-top:4px;">
        DIVINE PROCUREMENT VISION
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.caption(f"**{len(df_master):,}** tenders · {df_master['state'].nunique()} states · 12 sectors")
    st.markdown("---")
    st.markdown("#### 🔍 Global Search")
    search_query = st.text_input("Keyword", placeholder="road, hospital, school…", label_visibility="collapsed")
    st.markdown("---")
    st.markdown("#### 📊 Drill-Down Filters")

    selected_sector = st.selectbox("Sector", [ALL] + all_sectors)

    dept_options = [ALL]
    if selected_sector != ALL:
        dept_options += sorted(df_master[df_master["sector"] == selected_sector]["department"].dropna().unique().tolist())
    selected_dept = st.selectbox("Department", dept_options)

    state_options = [ALL]
    _sd = df_master if selected_sector == ALL else df_master[df_master["sector"] == selected_sector]
    if selected_dept != ALL:
        _sd = _sd[_sd["department"] == selected_dept]
    state_options += sorted(_sd["state"].dropna().unique().tolist())
    selected_state = st.selectbox("State / UT", state_options)

    district_options = [ALL]
    _dd = _sd if selected_state == ALL else _sd[_sd["state"] == selected_state]
    district_options += sorted(_dd["district"].dropna().unique().tolist())
    selected_district = st.selectbox("District", district_options)

    block_options = [ALL]
    _bd = _dd if selected_district == ALL else _dd[_dd["district"] == selected_district]
    block_options += sorted(_bd["block"].dropna().unique().tolist())
    selected_block = st.selectbox("Block / Taluka", block_options)

    st.markdown("---")
    st.markdown("#### ⚙️ Additional Filters")
    all_statuses     = sorted(df_master["status"].dropna().unique().tolist())
    selected_statuses = st.multiselect("Status", all_statuses, default=all_statuses)
    _amt = df_master["allocated_amount"]
    budget_range = st.slider(
        "Budget Range (₹ Cr)", float(_amt.min()), float(_amt.max()),
        (float(_amt.min()), float(_amt.max())), step=0.1,
    )
    st.markdown("---")

    with st.expander("⚙️ Advanced Settings", expanded=False):
        try:
            from repository.db import DB_PATH
            _cnt = __import__("sqlite3").connect(DB_PATH).execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
            st.success(f"📡 Real Data — {_cnt:,} scraped tenders in DB")
        except Exception:
            st.warning("🧪 Preview mode — seed data.")

        st.markdown("#### 🔄 Run Live Scraper")
        _sources = st.multiselect(
            "Sources",
            ["cppp","gem","states","datagov","pmgsy","biharv2","cgstate",
             "up_misc","up_sectors","up_power","psu_html","ongc","nhai","coal_india"],
            default=["cppp","gem"],
        )
        _pages   = st.number_input("Pages per portal", min_value=1, max_value=200, value=10)
        _api_key = st.text_input("data.gov.in API Key", type="password", placeholder="Optional")
        if st.button("▶ Start Scraping", type="primary", use_container_width=True):
            import subprocess
            cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"),
                   "--sources", ",".join(_sources), "--pages", str(_pages)]
            if _api_key:
                cmd += ["--api-key", _api_key]
            with st.spinner("Scraping live portals…"):
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                if result.returncode == 0:
                    st.success("✅ Scraping complete")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Scraper error")
                    st.code((result.stderr or result.stdout)[-3000:])

        if st.button("🔄 Refresh Display", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown("---")
        st.markdown("#### 🔍 Re-classify Sector / Location")
        if st.button("🔍 Reclassify Database", use_container_width=True):
            import subprocess
            cmd = [sys.executable, str(Path(__file__).parent / "scraper_v3.py"), "--reclassify"]
            with st.spinner("Reclassifying records…"):
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                st.success("✅ Reclassification complete") if result.returncode == 0 else st.error("Failed")
                st.cache_data.clear()
                st.rerun()

    # ── Data source health ─────────────────────────────────────────────────────
    with st.expander("📡 Portal Health Log", expanded=False):
        try:
            _health = load_health_log()
            if _health is not None and not _health.empty:
                ok  = int((_health["status"] == "ok").sum())
                bad = int((_health["status"] != "ok").sum())
                st.metric("OK / Failed", f"{ok} / {bad}")
                st.dataframe(
                    _health[["source","status","records_fetched","logged_at"]].tail(20),
                    use_container_width=True, hide_index=True,
                )
        except Exception:
            st.caption("No health log yet.")

# ── Apply filters ─────────────────────────────────────────────────────────────
df = df_master.copy()
if selected_sector   != ALL: df = df[df["sector"]   == selected_sector]
if selected_dept     != ALL: df = df[df["department"]== selected_dept]
if selected_state    != ALL: df = df[df["state"]     == selected_state]
if selected_district != ALL: df = df[df["district"]  == selected_district]
if selected_block    != ALL: df = df[df["block"]     == selected_block]
df = df[df["status"].isin(selected_statuses) & df["allocated_amount"].between(*budget_range)]
if search_query.strip():
    q    = search_query.strip().lower()
    mask = (df["title"].str.lower().str.contains(q, na=False) |
            df["department"].str.lower().str.contains(q, na=False) |
            df["tender_id"].str.lower().str.contains(q, na=False))
    df = df[mask]

# ── Drill level ────────────────────────────────────────────────────────────────
if   selected_state    == ALL: drill_level, level_label = "national", "🌏 National View — All States & Sectors"
elif selected_district == ALL: drill_level, level_label = "state",    f"📍 State View — {selected_state}"
elif selected_block    == ALL: drill_level, level_label = "district",  f"🏙️ District View — {selected_district}, {selected_state}"
else:                          drill_level, level_label = "block",     f"🔍 Block View — {selected_block}, {selected_district}"

render_mode = "scatter" if len(df) <= SCATTER_LIMIT else "aggregated"

# ── KPIs ──────────────────────────────────────────────────────────────────────
total_funds  = float(df["allocated_amount"].sum())
active_count = int((df["status"] == "Active").sum())
avg_cost     = float(df["allocated_amount"].mean()) if len(df) else 0
top_row      = df.loc[df["allocated_amount"].idxmax()] if len(df) else None
sector_count = df["sector"].nunique()
source_count = df["source"].nunique()

# ── Auto-Narrative Engine  (R-01) ──────────────────────────────────────────────
def build_narrative(df: pd.DataFrame, level: str, state: str, district: str) -> str:
    """
    Generate 4–5 sentences of contextual procurement intelligence
    from the current filtered dataset.  Pure Python logic — no LLM needed.
    """
    if df.empty:
        return "No tenders match the current filters. Please broaden your selection."

    n          = len(df)
    total_cr   = df["allocated_amount"].sum()
    top_sector = df.groupby("sector")["allocated_amount"].sum().idxmax()
    top_sector_pct = (df[df["sector"] == top_sector]["allocated_amount"].sum() / max(total_cr, 1) * 100)
    top_state_name = (df.groupby("state")["allocated_amount"].sum().idxmax()
                      if "state" in df.columns and level == "national" else state)
    top_dept   = df.groupby("department")["allocated_amount"].sum().idxmax()
    active_pct = active_count / max(n, 1) * 100
    top_tender_title = df.loc[df["allocated_amount"].idxmax(), "title"] if len(df) else "—"
    top_tender_amt   = float(df["allocated_amount"].max()) if len(df) else 0
    sources_list     = ", ".join(df["source"].value_counts().head(3).index.tolist())

    loc_phrase = (
        f"Across India's {df['state'].nunique()} scraped states and UTs"
        if level == "national" else
        f"Within {state}" if level == "state" else
        f"In {district} district"
    )

    line1 = (
        f"{loc_phrase}, **{n:,} active procurement tenders** worth "
        f"**₹{total_cr:,.1f} Crores** are currently in scope."
    )
    line2 = (
        f"**{top_sector}** dominates at **{top_sector_pct:.0f}%** of total allocated budget, "
        f"driven largely by *{top_dept[:50]}*."
    )
    line3 = (
        f"**{active_pct:.0f}%** of tenders are in Active status, "
        f"indicating robust current procurement activity."
    )
    line4 = (
        f"The single highest-value tender — *\"{top_tender_title[:60]}…\"* — "
        f"is valued at **₹{top_tender_amt:,.1f} Cr**, setting the scale ceiling for this view."
    )
    line5 = (
        f"Data sourced from **{source_count}** portal(s) including {sources_list}, "
        f"providing broad cross-sector coverage."
    )
    return f"{line1}<br><br>{line2} {line3}<br><br>{line4}<br><br>{line5}"

narrative_html = build_narrative(df, drill_level, selected_state, selected_district)

# ── PAGE HEADER ───────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="display:flex;align-items:center;gap:20px;padding:8px 0 4px 0;">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 72" width="68" height="68">
    <circle cx="36" cy="36" r="33" fill="none" stroke="#A8821E" stroke-width="1.5" opacity="0.5"/>
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
    <path d="M8,36 Q36,14 64,36 Q36,58 8,36 Z" fill="#FFFBF0"/>
    <path d="M8,36 Q36,14 64,36 Q36,58 8,36 Z" fill="none" stroke="#7B2D42" stroke-width="1.8"/>
    <defs>
      <radialGradient id="iris" cx="40%" cy="40%">
        <stop offset="0%" stop-color="#D4902E"/>
        <stop offset="100%" stop-color="#7B5010"/>
      </radialGradient>
    </defs>
    <circle cx="36" cy="36" r="13" fill="url(#iris)"/>
    <circle cx="36" cy="36" r="7.5" fill="#7B2D42"/>
    <circle cx="36" cy="36" r="3" fill="#A8821E"/>
    <circle cx="36" cy="36" r="1.2" fill="#FFFBF0"/>
  </svg>
  <div>
    <div class="brand-name"><span class="divya">Divya</span><span class="drishti">Drishti</span></div>
    <div class="brand-sanskrit">दिव्यदृष्टि</div>
    <div class="brand-tagline">Pan-India Procurement Intelligence · 12 Sectors · {df_master['state'].nunique()} States/UTs · {len(df_master):,} Tenders</div>
  </div>
</div>
<span class="badge">{level_label}</span>
""", unsafe_allow_html=True)

st.markdown("<div style='margin:6px 0'></div>", unsafe_allow_html=True)

if df.empty:
    st.warning("⚠️ No tenders match the current filter combination.")
    st.stop()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TABS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
tab1, tab2, tab3, tab4 = st.tabs([
    "🌐 Mission Control",
    "🔬 Intelligence Suite",
    "📊 Sector Lens",
    "📄 Data Vault",
])

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 1 · MISSION CONTROL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab1:

    # ── KPI Strip (R-02) ──────────────────────────────────────────────────────
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("💰 Total Budget",   f"₹{total_funds:,.1f} Cr")
    c2.metric("📋 Tenders",        f"{len(df):,}", delta=f"{active_count} Active", delta_color="off")
    c3.metric("📊 Avg per Tender", f"₹{avg_cost:,.1f} Cr")
    if top_row is not None:
        _top_val   = f"₹{float(top_row['allocated_amount']):,.1f} Cr"
        _top_delta = str(top_row["sector"])
        c4.metric("🏆 Largest Tender", _top_val, delta=_top_delta, delta_color="off")
    else:
        c4.metric("🏆 Largest Tender", "—")
    c5.metric("🏭 Sectors",        f"{sector_count}")
    c6.metric("🔌 Data Sources",   f"{source_count}")

    # ── Spotlight Cards (R-12) ────────────────────────────────────────────────
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    top_state_by_amt  = df.groupby("state")["allocated_amount"].sum().idxmax() if "state" in df.columns else "—"
    top_state_val     = df.groupby("state")["allocated_amount"].sum().max() if "state" in df.columns else 0
    hot_sector        = df.groupby("sector")["allocated_amount"].sum().idxmax()
    hot_sector_cnt    = int((df["sector"] == hot_sector).sum())
    big_tender_title  = df.loc[df["allocated_amount"].idxmax(), "title"][:42] + "…" if len(df) else "—"
    big_tender_amt    = float(df["allocated_amount"].max()) if len(df) else 0
    latest_source     = df.groupby("source")["allocated_amount"].count().idxmax() if len(df) else "—"
    latest_source_cnt = int(df["source"].value_counts().max()) if len(df) else 0

    st.markdown(f"""
    <div class="spotlight-grid">
      <div class="spotlight">
        <span class="spotlight-icon">🏆</span>
        <span class="spotlight-val">{str(top_state_by_amt)[:18]}</span>
        <div class="spotlight-lbl">Top State by Budget</div>
        <div class="spotlight-desc">₹{top_state_val:,.0f} Cr total allocation —<br>leads all states in procurement spend</div>
      </div>
      <div class="spotlight">
        <span class="spotlight-icon">🔥</span>
        <span class="spotlight-val">{hot_sector}</span>
        <div class="spotlight-lbl">Hottest Sector</div>
        <div class="spotlight-desc">{hot_sector_cnt:,} tenders and counting —<br>highest budget concentration in this view</div>
      </div>
      <div class="spotlight">
        <span class="spotlight-icon">💎</span>
        <span class="spotlight-val">₹{big_tender_amt:,.0f} Cr</span>
        <div class="spotlight-lbl">Biggest Single Tender</div>
        <div class="spotlight-desc">{big_tender_title}<br>the single largest procurement event</div>
      </div>
      <div class="spotlight">
        <span class="spotlight-icon">🔌</span>
        <span class="spotlight-val">{str(latest_source)[:18]}</span>
        <div class="spotlight-lbl">Most Active Portal</div>
        <div class="spotlight-desc">{latest_source_cnt:,} tenders sourced —<br>highest-volume procurement gateway</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Auto-Narrative (R-01) ─────────────────────────────────────────────────
    st.markdown(f"""
    <div class="insight-card">
      <h4>🧠 Procurement Intelligence Briefing</h4>
      <p>{narrative_html}</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── Map (R-03) ────────────────────────────────────────────────────────────
    st.markdown('<div class="section-label">🗺️ Procurement Geography Map</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">Every bubble is a tender. Size = budget. Colour = sector. '
        'Zoom in to district level for project-site precision. Roads and pipelines render as coloured lines.</div>',
        unsafe_allow_html=True,
    )

    map_col, info_col = st.columns([4, 1])
    view = get_view_config(df, selected_state if selected_state != ALL else None,
                           selected_district if selected_district != ALL else None)

    with map_col:
        if render_mode == "aggregated":
            st.markdown('<div class="agg-warn">⚡ Aggregated view — narrow filters to enter deep-dive scatter mode.</div>',
                        unsafe_allow_html=True)
            agg_col   = "state" if drill_level in ("national","state") else "district"
            agg_df    = server_side_aggregate(df, agg_col)
            if agg_col == "state":
                agg_df["lat"] = agg_df["state"].map(lambda s: STATE_CENTERS.get(s,{}).get("lat",22.5))
                agg_df["lon"] = agg_df["state"].map(lambda s: STATE_CENTERS.get(s,{}).get("lon",82.5))
            fig_map = px.scatter_mapbox(agg_df, lat="lat", lon="lon",
                size="total_amount", color="total_amount",
                color_continuous_scale="YlOrRd",
                hover_name=agg_col, size_max=60, height=520,
                mapbox_style="open-street-map",
                center={"lat":view["lat"],"lon":view["lon"]}, zoom=view["zoom"],
                hover_data={"total_amount":":.1f","count":True,"lat":False,"lon":False},
                labels={"total_amount":"₹ Cr","count":"Tenders"},
            )
            fig_map.update_coloraxes(colorbar_title="₹ Cr")
        else:
            df_plot = df.copy()
            a_min, a_max = float(df_plot["allocated_amount"].min()), float(df_plot["allocated_amount"].max())
            df_plot["bubble"] = ((df_plot["allocated_amount"]-a_min)/max(a_max-a_min,1))*(38-14)+14
            df_plot["amt_fmt"] = df_plot["allocated_amount"].apply(lambda x: f"₹{x:,.2f} Cr")
            for col in ("contractor_name","start_date","end_date"):
                if col not in df_plot.columns: df_plot[col] = "—"
                df_plot[col] = df_plot[col].fillna("—").replace("","—")

            if "latitude2" in df_plot.columns:
                linear_mask = df_plot["latitude2"].notna() & df_plot["longitude2"].notna()
            else:
                linear_mask = pd.Series([False]*len(df_plot), index=df_plot.index)
            df_lines  = df_plot[linear_mask]
            df_points = df_plot[~linear_mask]
            base_df   = df_points if not df_points.empty else df_plot

            fig_map = px.scatter_mapbox(base_df, lat="latitude", lon="longitude",
                size="bubble", color="sector",
                color_discrete_map=SECTOR_COLORS,
                hover_name="title", height=520,
                mapbox_style="open-street-map",
                center={"lat":view["lat"],"lon":view["lon"]}, zoom=view["zoom"],
                hover_data={"department":True,"amt_fmt":True,"status":True,
                            "state":True,"district":True,"block":True,
                            "contractor_name":True,"start_date":True,"end_date":True,
                            "bubble":False,"latitude":False,"longitude":False},
                labels={"amt_fmt":"Allocated","department":"Dept","status":"Status",
                        "sector":"Sector","contractor_name":"Contractor",
                        "start_date":"Start","end_date":"End"},
            )
            fig_map.update_traces(marker=dict(opacity=0.85))

            if not df_lines.empty:
                for sector, grp in df_lines.groupby("sector", observed=True):
                    color   = SECTOR_COLORS.get(str(sector),"#888")
                    lats,lons = [],[]
                    for _,r in grp.iterrows():
                        lats.extend([float(r["latitude"]),float(r["latitude2"]),None])
                        lons.extend([float(r["longitude"]),float(r["longitude2"]),None])
                    fig_map.add_trace(go.Scattermapbox(lat=lats,lon=lons,mode="lines",
                        line=dict(width=5,color=color),opacity=0.75,
                        hoverinfo="skip",showlegend=False))
                    mid_lat = [(float(r["latitude"])+float(r["latitude2"]))/2 for _,r in grp.iterrows()]
                    mid_lon = [(float(r["longitude"])+float(r["longitude2"]))/2 for _,r in grp.iterrows()]
                    fig_map.add_trace(go.Scattermapbox(lat=mid_lat,lon=mid_lon,mode="markers",
                        marker=dict(size=10,color=color,opacity=0.95),
                        hovertext=[f"<b>{r['title']}</b><br>₹{r['amt_fmt']}<br>{r['block']}, {r['district']}"
                                   for _,r in grp.iterrows()],
                        hoverinfo="text",showlegend=False))

            if drill_level in ("district","block") and selected_state in DISTRICT_COORDINATES:
                if selected_district in DISTRICT_COORDINATES[selected_state]:
                    c = DISTRICT_COORDINATES[selected_state][selected_district]
                    r_km = 25 if drill_level=="district" else 8
                    r_lat = r_km/111.0
                    r_lon = r_km/(111.0*math.cos(math.radians(c["lat"])))
                    clats = [c["lat"]+r_lat*math.sin(t) for t in np.linspace(0,2*math.pi,60)]
                    clons = [c["lon"]+r_lon*math.cos(t) for t in np.linspace(0,2*math.pi,60)]
                    fig_map.add_trace(go.Scattermapbox(lat=clats,lon=clons,mode="lines",
                        line=dict(width=2,color="rgba(196,118,41,0.6)"),
                        fill="toself",fillcolor="rgba(196,118,41,0.06)",
                        hoverinfo="skip",showlegend=False))

        fig_map.update_layout(margin=dict(l=0,r=0,t=0,b=0),
                               legend=dict(orientation="h",yanchor="bottom",y=1.01,
                                           xanchor="right",x=1,font=dict(size=10)))
        st.plotly_chart(fig_map, use_container_width=True)

    with info_col:
        st.markdown("#### 📌 View Info")
        st.markdown(f"**Mode:** `{render_mode}`")
        st.markdown(f"**Records:** `{len(df):,}`")
        st.markdown("---")
        if render_mode == "scatter":
            st.markdown("**Sectors**")
            for sec in sorted(df["sector"].unique()):
                col  = SECTOR_COLORS.get(sec,"#999")
                cnt  = int((df["sector"]==sec).sum())
                st.markdown(
                    f'<span style="background:{col};border-radius:50%;display:inline-block;'
                    f'width:10px;height:10px;margin-right:4px;"></span>{sec[:14]} ({cnt})',
                    unsafe_allow_html=True)
        else:
            grp  = "state" if drill_level in ("national","state") else "district"
            top5 = df.groupby(grp)["allocated_amount"].sum().nlargest(5)
            st.markdown(f"**Top {grp.title()}s**")
            for name,amt in top5.items():
                st.caption(f"{str(name)[:18]}: ₹{amt:,.0f} Cr")
        st.markdown("---")
        st.markdown("**Status**")
        for s,col in STATUS_COLORS.items():
            cnt = int((df["status"]==s).sum())
            if cnt:
                st.markdown(f'<span style="color:{col};font-weight:700;">●</span> {s}: {cnt:,}',
                            unsafe_allow_html=True)

    # ── Source Portal Ring (R-08) ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">🔌 Data Source Contribution</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">Which government procurement portals are feeding this dashboard? '
        'Each slice shows one scraping source. A broad spread means diverse portal coverage; '
        'a single dominant slice signals a data gap — other portals may need scraping.</div>',
        unsafe_allow_html=True,
    )

    src_ring_col, src_bar_col = st.columns([1, 2])
    src_counts = df.groupby("source").agg(
        Tenders=("tender_id","count"),
        Budget=("allocated_amount","sum")
    ).reset_index().sort_values("Tenders", ascending=False)

    with src_ring_col:
        fig_ring = px.pie(src_counts, names="source", values="Tenders",
                          hole=0.55, height=340,
                          color_discrete_sequence=px.colors.qualitative.Set2)
        fig_ring.update_traces(textposition="outside", textinfo="label+percent")
        fig_ring.update_layout(showlegend=False, margin=dict(t=10,b=10,l=10,r=10))
        st.plotly_chart(fig_ring, use_container_width=True)

    with src_bar_col:
        src_counts_sorted = src_counts.sort_values("Budget")
        fig_srcbar = px.bar(src_counts_sorted, x="Budget", y="source", orientation="h",
                            color="Budget", color_continuous_scale=["#F8E8CC","#C47629","#7B2D42"],
                            text_auto=".0f", height=340,
                            labels={"Budget":"₹ Crores","source":"Portal"})
        fig_srcbar.update_layout(coloraxis_showscale=False,
                                  margin=dict(t=10,b=10,l=5,r=5),
                                  yaxis=dict(tickfont=dict(size=9)))
        st.plotly_chart(fig_srcbar, use_container_width=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 2 · INTELLIGENCE SUITE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab2:

    # ── Treemap (R-04) ────────────────────────────────────────────────────────
    st.markdown('<div class="section-label">🌳 Procurement Hierarchy Treemap</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Every rectangle is a State → Sector combination. Area = total ₹ Crores allocated. '
        'Larger rectangles mean more money concentrated there. '
        'Use this to instantly see where India\'s government spending is heaviest — '
        'and which sector+state pairs are under-resourced (tiny boxes).'
        '</div>', unsafe_allow_html=True,
    )

    treemap_df = (
        df.groupby(["state","sector"])["allocated_amount"]
        .sum().reset_index()
        .rename(columns={"allocated_amount":"₹ Cr"})
    )
    treemap_df = treemap_df[treemap_df["₹ Cr"] > 0]

    if not treemap_df.empty:
        fig_tree = px.treemap(
            treemap_df,
            path=[px.Constant("India"),"state","sector"],
            values="₹ Cr",
            color="sector",
            color_discrete_map=SECTOR_COLORS,
            hover_data={"₹ Cr":":.1f"},
            height=500,
        )
        fig_tree.update_traces(
            texttemplate="<b>%{label}</b><br>₹%{value:.0f} Cr",
            textfont=dict(size=12),
            marker=dict(cornerradius=4),
        )
        fig_tree.update_layout(margin=dict(t=10,b=10,l=10,r=10))
        st.plotly_chart(fig_tree, use_container_width=True)
    else:
        st.info("Not enough data for treemap with current filters.")

    # ── Sankey (R-05) ────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">🌊 Budget Flow — Portal → State → Sector</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Follow every rupee\'s journey: which <b>procurement portal</b> captured it, '
        'which <b>state</b> it belongs to, and which <b>sector</b> it ultimately funds. '
        'Wide rivers = large money flows. Thin streams = niche allocations. '
        'This reveals whether any state relies too heavily on a single portal '
        'or whether certain sectors are systematically under-funded.'
        '</div>', unsafe_allow_html=True,
    )

    # Build Sankey nodes and links — cap at top-8 sources and top-10 states for legibility
    top_sources = df.groupby("source")["allocated_amount"].sum().nlargest(8).index.tolist()
    top_states  = df.groupby("state")["allocated_amount"].sum().nlargest(10).index.tolist()
    df_sk = df[df["source"].isin(top_sources) & df["state"].isin(top_states)].copy()
    df_sk["source_grp"] = df_sk["source"].apply(lambda x: x if x in top_sources else "Others")

    # Node list: sources + states + sectors
    all_sectors_sk = sorted(df_sk["sector"].dropna().unique().tolist())
    node_labels    = top_sources + top_states + all_sectors_sk
    node_idx       = {n: i for i, n in enumerate(node_labels)}

    # Links: source → state
    sk_links = []
    for (src, st_), grp in df_sk.groupby(["source","state"]):
        if src in node_idx and st_ in node_idx:
            sk_links.append((node_idx[src], node_idx[st_], float(grp["allocated_amount"].sum())))

    # Links: state → sector
    for (st_, sec), grp in df_sk.groupby(["state","sector"]):
        if st_ in node_idx and sec in node_idx:
            sk_links.append((node_idx[st_], node_idx[sec], float(grp["allocated_amount"].sum())))

    sk_links = [(s,t,v) for s,t,v in sk_links if v > 0]

    if sk_links:
        # Colour nodes: saffron for sources, teal for states, sector-colour for sectors
        node_colors = (
            ["rgba(196,118,41,0.8)"] * len(top_sources) +
            ["rgba(123,45,66,0.7)"]  * len(top_states)  +
            [SECTOR_COLORS.get(s,"#888") for s in all_sectors_sk]
        )
        fig_sankey = go.Figure(go.Sankey(
            node=dict(
                pad=14, thickness=22,
                line=dict(color="#E4D9C5", width=0.5),
                label=node_labels,
                color=node_colors,
                hovertemplate="%{label}<br>₹%{value:.1f} Cr<extra></extra>",
            ),
            link=dict(
                source=[s for s,t,v in sk_links],
                target=[t for s,t,v in sk_links],
                value =[v for s,t,v in sk_links],
                color ="rgba(196,118,41,0.18)",
                hovertemplate="%{source.label} → %{target.label}<br>₹%{value:.1f} Cr<extra></extra>",
            ),
        ))
        fig_sankey.update_layout(
            height=480,
            font=dict(size=11, family="Inter"),
            margin=dict(t=10,b=10,l=10,r=10),
        )
        st.plotly_chart(fig_sankey, use_container_width=True)
    else:
        st.info("Not enough overlapping data for Sankey. Broaden filters.")

    # ── Sector × State Heatmap (R-06) ────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">🌡️ Sector × State Investment Heatmap</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Each cell shows the total ₹ Crores flowing into a specific <b>Sector × State</b> combination. '
        'Dark red = heavy investment. Pale yellow = light spend. '
        'Empty (white) cells reveal procurement blind-spots — states that have invested '
        '<b>nothing</b> in a particular sector. These are the most actionable insights for policy makers.'
        '</div>', unsafe_allow_html=True,
    )

    top_hm_states  = df.groupby("state")["allocated_amount"].sum().nlargest(15).index.tolist()
    hm_df = (df[df["state"].isin(top_hm_states)]
             .groupby(["state","sector"])["allocated_amount"].sum()
             .unstack(fill_value=0))
    hm_df = hm_df.reindex(index=top_hm_states, fill_value=0)

    if not hm_df.empty:
        fig_hm = go.Figure(go.Heatmap(
            z=hm_df.values,
            x=[str(c) for c in hm_df.columns],
            y=[str(r) for r in hm_df.index],
            colorscale=[
                [0,    "#FFFBF2"],
                [0.2,  "#F5C97E"],
                [0.5,  "#C47629"],
                [0.8,  "#7B2D42"],
                [1.0,  "#2C0F18"],
            ],
            hovertemplate="<b>%{y} — %{x}</b><br>₹%{z:,.1f} Cr<extra></extra>",
            text=[[f"₹{v:,.0f}" if v>0 else "" for v in row] for row in hm_df.values],
            texttemplate="%{text}",
            textfont=dict(size=9),
            colorbar=dict(title="₹ Cr", thickness=14),
        ))
        fig_hm.update_layout(
            height=440,
            margin=dict(t=10,b=10,l=120,r=10),
            xaxis=dict(tickfont=dict(size=10), tickangle=-35),
            yaxis=dict(tickfont=dict(size=10)),
        )
        st.plotly_chart(fig_hm, use_container_width=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 3 · SECTOR LENS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab3:

    # ── Bubble Pack by Sector (R-07) ─────────────────────────────────────────
    st.markdown('<div class="section-label">🫧 Sector Budget Bubble Pack</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Each bubble represents one procurement sector. <b>Bubble size = total ₹ Crores</b>. '
        'This is the most visceral way to feel the relative weight of each sector '
        'in the current filtered view — one glance tells you which sector dominates '
        'and which barely registers in government spending.'
        '</div>', unsafe_allow_html=True,
    )

    sec_bubble = (df.groupby("sector")
                    .agg(Budget=("allocated_amount","sum"), Count=("tender_id","count"))
                    .reset_index()
                    .sort_values("Budget", ascending=False))

    # Manual circular packing — evenly space along an ellipse for simple layout
    n_sec   = len(sec_bubble)
    angles  = np.linspace(0, 2*np.pi, n_sec, endpoint=False)
    # Radius proportional to budget for spacing
    max_b   = sec_bubble["Budget"].max() if not sec_bubble.empty else 1
    radii   = np.sqrt(sec_bubble["Budget"].values / max(max_b,1)) * 5  # scale for marker size (px)
    xs      = np.cos(angles) * 3
    ys      = np.sin(angles) * 2

    fig_bubble = go.Figure()
    for i, row in sec_bubble.iterrows():
        idx  = list(sec_bubble.index).index(i)
        siz  = max(float(np.sqrt(row["Budget"]/max(max_b,1)))*120, 20)
        fig_bubble.add_trace(go.Scatter(
            x=[xs[idx]], y=[ys[idx]],
            mode="markers+text",
            marker=dict(
                size=siz,
                color=SECTOR_COLORS.get(row["sector"],"#888"),
                opacity=0.88,
                line=dict(width=2, color="white"),
            ),
            text=[row["sector"]],
            textposition="middle center",
            textfont=dict(size=max(9, min(13, int(siz/12))), color="white", family="Rajdhani"),
            hovertemplate=(
                f"<b>{row['sector']}</b><br>"
                f"Budget: ₹{row['Budget']:,.1f} Cr<br>"
                f"Tenders: {row['Count']:,}<extra></extra>"
            ),
            showlegend=False,
        ))

    fig_bubble.update_layout(
        height=440, xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor="rgba(254,253,247,1)", plot_bgcolor="rgba(254,253,247,1)",
        margin=dict(t=10,b=10,l=10,r=10),
    )
    st.plotly_chart(fig_bubble, use_container_width=True)

    # ── Budget Waterfall (R-09) ───────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">📉 Sector Budget Waterfall</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'The waterfall shows how the <b>total procurement budget erodes sector by sector</b>. '
        'Start from the grand total (leftmost bar) and watch each sector\'s share step down '
        'cumulatively to the right. This makes it easy to see which sectors consume '
        'the first 50% of all spending, and which account for the long tail.'
        '</div>', unsafe_allow_html=True,
    )

    wf_data = (df.groupby("sector")["allocated_amount"].sum()
                 .sort_values(ascending=False).reset_index())
    wf_data.columns = ["Sector","Amount"]
    wf_measures = ["absolute"] + ["relative"] * len(wf_data) + ["total"]
    wf_x        = ["Grand Total"] + wf_data["Sector"].tolist() + ["Remainder"]
    wf_y        = [total_funds] + (-wf_data["Amount"]).tolist() + [0]
    wf_text     = [f"₹{total_funds:,.0f} Cr"] + \
                  [f"-₹{v:,.0f} Cr" for v in wf_data["Amount"]] + [""]
    wf_colors   = (["#7B2D42"] +
                   [SECTOR_COLORS.get(s,"#C47629") for s in wf_data["Sector"]] +
                   ["#A8821E"])

    fig_wf = go.Figure(go.Waterfall(
        orientation="v",
        measure=wf_measures,
        x=wf_x, y=wf_y,
        text=wf_text, textposition="outside",
        textfont=dict(size=9),
        connector=dict(line=dict(color="rgba(168,130,30,0.3)", width=1, dash="dot")),
        increasing=dict(marker=dict(color="#2E7D52")),
        decreasing=dict(marker=dict(color="#C47629")),
        totals=dict(marker=dict(color="#7B2D42")),
    ))
    fig_wf.update_layout(
        height=400,
        margin=dict(t=30,b=10,l=10,r=10),
        xaxis=dict(tickangle=-30, tickfont=dict(size=10)),
        yaxis=dict(title="₹ Crores", tickfont=dict(size=10)),
        showlegend=False,
        paper_bgcolor="rgba(254,253,247,0)",
        plot_bgcolor="rgba(254,253,247,0)",
    )
    st.plotly_chart(fig_wf, use_container_width=True)

    # ── Timeline Pulse (R-10) ─────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">⏱️ Procurement Timeline Pulse</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Each spike in this area chart shows a burst of procurement activity on that date. '
        'The colour gradient (light → dark saffron) shows accelerating spend. '
        'Flat periods indicate procurement freezes or data gaps. '
        'Use this to identify whether your district or state goes through cyclic tender bursts '
        '(common before financial year-end in March) or maintains steady activity.'
        '</div>', unsafe_allow_html=True,
    )

    # Use start_date as proxy; fall back to scraped_at
    tl_df = df.copy()
    tl_df["date_col"] = pd.to_datetime(tl_df["start_date"], errors="coerce")
    tl_df = tl_df.dropna(subset=["date_col"])
    if tl_df.empty:
        # Fallback: scraped_at
        tl_df = df.copy()
        tl_df["date_col"] = pd.to_datetime(tl_df["scraped_at"], errors="coerce")
        tl_df = tl_df.dropna(subset=["date_col"])

    if not tl_df.empty:
        tl_agg = (tl_df.groupby(tl_df["date_col"].dt.to_period("M").astype(str))
                       .agg(Tenders=("tender_id","count"),
                            Budget=("allocated_amount","sum"))
                       .reset_index()
                       .rename(columns={"date_col":"Month"}))
        tl_agg = tl_agg[tl_agg["Month"].str.match(r"\d{4}")]  # drop weird period labels

        fig_tl = go.Figure()
        fig_tl.add_trace(go.Scatter(
            x=tl_agg["Month"], y=tl_agg["Tenders"],
            mode="lines",
            fill="tozeroy",
            fillgradient=dict(type="vertical",
                              colorscale=[[0,"rgba(196,118,41,0.05)"],
                                          [1,"rgba(196,118,41,0.55)"]]),
            line=dict(color="#C47629", width=2),
            hovertemplate="<b>%{x}</b><br>Tenders: %{y:,}<extra></extra>",
            name="Tenders",
        ))
        fig_tl.update_layout(
            height=300,
            margin=dict(t=10,b=10,l=10,r=10),
            xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
            yaxis=dict(title="Tender Count"),
            paper_bgcolor="rgba(254,253,247,0)",
            plot_bgcolor="rgba(254,253,247,0)",
            showlegend=False,
        )
        st.plotly_chart(fig_tl, use_container_width=True)
    else:
        st.info("No date data available for timeline in current filter.")

    # ── Leader Boards (R-11) ──────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">🏅 Leader Boards — Departments & Contractors</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Ranked bar charts showing the heaviest spenders (departments) and '
        'the most-awarded contractors. Use these to identify concentrated procurement power — '
        'a single department dominating a district\'s budget may indicate '
        'siloed planning that could benefit from cross-sector coordination.'
        '</div>', unsafe_allow_html=True,
    )

    lb1, lb2 = st.columns(2)

    with lb1:
        st.markdown("**🏢 Top 10 Departments by Budget**")
        dept_lb = (df.groupby("department")["allocated_amount"].sum()
                     .nlargest(10).reset_index()
                     .rename(columns={"allocated_amount":"₹ Cr","department":"Dept"})
                     .sort_values("₹ Cr"))
        dept_lb["Dept"] = dept_lb["Dept"].str[:35]
        fig_dept = px.bar(dept_lb, x="₹ Cr", y="Dept", orientation="h",
                          text_auto=".0f", height=380,
                          color="₹ Cr",
                          color_continuous_scale=["#F8E8CC","#C47629","#7B2D42"])
        fig_dept.update_layout(coloraxis_showscale=False,
                                margin=dict(t=5,b=5,l=5,r=5),
                                yaxis=dict(tickfont=dict(size=9)))
        st.plotly_chart(fig_dept, use_container_width=True)

    with lb2:
        st.markdown("**👷 Top Contractors by Awarded Value**")
        contr_df = df[df["contractor_name"].notna() & (df["contractor_name"] != "—") & (df["contractor_name"] != "")]
        if not contr_df.empty:
            contr_lb = (contr_df.groupby("contractor_name")["allocated_amount"].sum()
                                .nlargest(10).reset_index()
                                .rename(columns={"allocated_amount":"₹ Cr","contractor_name":"Contractor"})
                                .sort_values("₹ Cr"))
            contr_lb["Contractor"] = contr_lb["Contractor"].str[:35]
            fig_con = px.bar(contr_lb, x="₹ Cr", y="Contractor", orientation="h",
                             text_auto=".0f", height=380,
                             color="₹ Cr",
                             color_continuous_scale=["#E8F5E9","#27AE60","#145A32"])
            fig_con.update_layout(coloraxis_showscale=False,
                                   margin=dict(t=5,b=5,l=5,r=5),
                                   yaxis=dict(tickfont=dict(size=9)))
            st.plotly_chart(fig_con, use_container_width=True)
        else:
            st.info("No contractor data in current filter set.")

    # ── Status Split + Budget Distribution (original charts, refreshed) ───────
    st.markdown("---")
    rc1, rc2 = st.columns(2)
    with rc1:
        st.markdown("**📊 Status Split**")
        st.caption("The share of tenders that are Active, Awarded, or Completed. "
                   "High Active % = live procurement opportunity. High Completed = historical record.")
        stat_df = df["status"].value_counts().reset_index()
        stat_df.columns = ["Status","Count"]
        fig_status = px.pie(stat_df, names="Status", values="Count",
                            color="Status", color_discrete_map=STATUS_COLORS,
                            hole=0.52, height=320)
        fig_status.update_traces(textposition="outside", textinfo="percent+label")
        fig_status.update_layout(showlegend=False, margin=dict(t=5,b=5,l=5,r=5))
        st.plotly_chart(fig_status, use_container_width=True)

    with rc2:
        st.markdown("**📈 Budget Distribution**")
        st.caption("How tenders distribute by size (₹ Crores). A left-skewed peak means many "
                   "small tenders with a few large outliers — typical of government procurement.")
        fig_hist = px.histogram(df, x="allocated_amount", nbins=50,
                                color_discrete_sequence=["#C47629"],
                                labels={"allocated_amount":"₹ Crores"},
                                height=320)
        fig_hist.update_layout(margin=dict(t=5,b=5,l=5,r=5),
                                yaxis_title="Tenders", bargap=0.04)
        st.plotly_chart(fig_hist, use_container_width=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 4 · DATA VAULT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab4:

    st.markdown('<div class="section-label">📄 Full Tender Registry</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Every tender matching your current filters, with full metadata: '
        'title, sector, department, budget, geography (state → district → block), '
        'status, contractor, and dates. Use the Download button to export for '
        'offline analysis, legal review, or reporting to stakeholders.'
        '</div>', unsafe_allow_html=True,
    )

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
        "source":           "Portal",
        "contractor_name":  "Contractor",
        "start_date":       "Start Date",
        "end_date":         "End Date",
    }
    for _c in ("contractor_name","start_date","end_date"):
        if _c not in df.columns: df[_c] = "—"
        df[_c] = df[_c].fillna("—").replace("","—")

    PAGE_SIZE   = 200
    total_pages = max(1,(len(df)-1)//PAGE_SIZE+1)
    pcol1,pcol2,pcol3 = st.columns([2,1,2])
    with pcol2:
        page = st.number_input("Page",min_value=1,max_value=total_pages,value=1,step=1)

    start = (page-1)*PAGE_SIZE
    end   = start+PAGE_SIZE
    df_page = (df.iloc[start:end][list(TABLE_COLS.keys())]
                 .rename(columns=TABLE_COLS).copy())
    df_page["₹ Crores"] = df_page["₹ Crores"].apply(lambda x: f"₹{x:,.2f}")

    st.caption(f"Showing {start+1}–{min(end,len(df))} of {len(df):,}   |   Page {page} / {total_pages}")
    st.dataframe(df_page, use_container_width=True, height=400, hide_index=True)

    csv_data = (df[list(TABLE_COLS.keys())]
                  .rename(columns=TABLE_COLS)
                  .to_csv(index=False))
    dl1, dl2 = st.columns([1,4])
    with dl1:
        st.download_button("⬇️ Download CSV", data=csv_data,
                           file_name=f"divyadrishti_{drill_level}.csv",
                           mime="text/csv", use_container_width=True)
    with dl2:
        st.caption(f"Full filtered dataset: {len(df):,} rows · {len(TABLE_COLS)} columns")

    # ── Portal Health Table ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">📡 Portal Health Log</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Every scraping run is logged here — portal name, success/failure status, '
        'how many tenders were retrieved, and when. '
        'Use this to monitor which portals are consistently returning data '
        'and which need attention (CAPTCHA changes, DNS failures, layout updates).'
        '</div>', unsafe_allow_html=True,
    )
    try:
        _health = load_health_log()
        if _health is not None and not _health.empty:
            st.dataframe(
                _health[["source","domain","status","records_fetched","error_msg","logged_at"]]
                       .sort_values("logged_at", ascending=False)
                       .head(50),
                use_container_width=True, height=340, hide_index=True,
            )
        else:
            st.info("No health log entries yet. Run a scraper from the sidebar.")
    except Exception:
        st.info("Health log unavailable.")
