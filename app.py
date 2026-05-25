"""
DivyaDrishti — Divine Procurement Intelligence Engine  v5.0
Pan-India Public Expenditure & Tender Analytics · दिव्यदृष्टि

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PM REVIEW v5.0 — DEFECTS FIXED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIX-01  Budget unit corrected: amounts stored in raw ₹ Rupees, now
        displayed as ₹ Crores everywhere (÷ 1,00,00,000).

FIX-02  Budget filter no longer silently drops 80% of tenders.
        Replaced slider with an opt-in "Budget only" toggle.
        Valid budget threshold: > ₹10,000 (filters year/garbage values).

FIX-03  Source ring chart was unreadable with 1,095 sources.
        Grouped into Top 15 portals + "All Others" bucket.

FIX-04  "Other" and "Works" are unclassified catch-alls, not real
        government sectors. Labelled as "Unclassified" in charts and
        placed at the bottom of all sector lists.

FIX-05  KPI "Avg per Tender" was misleading (80% have no budget).
        Replaced with "Budget Coverage %" — clearly shows data quality.

FIX-06  State Explorer tab added: state comparison bar + heatmap by
        TENDER COUNT (budget too sparse to be the primary metric).

FIX-07  Budget histogram/waterfall only used for tenders with valid
        budget amounts, clearly labelled as a subset of all data.

FIX-08  Sankey and Treemap now primary by COUNT (hover shows budget).
        More data density; not distorted by budget data gaps.

FIX-09  Timeline axis fixed to show only real date range (not 1970s
        fallback when scraped_at is blank).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TAB STRUCTURE v5.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Tab 1 — 🌐 Overview       KPIs, spotlights, narrative, map
  Tab 2 — 📍 State Explorer  State comparison, sector×state heatmap
  Tab 3 — 📊 Sector & Trends Treemap, sankey, sector bar, timeline, leaderboards
  Tab 4 — 📄 Data & Sources  Table, CSV, portal analysis, health log
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

# ── Constants ──────────────────────────────────────────────────────────────────
ALL               = "All"
SCATTER_LIMIT     = 5_000
RUPEES_PER_CRORE  = 1_00_00_000   # 10 million
# DB has mixed units: Bihar/CHEPS/Coal India store raw Rupees; enrichers store Crores.
# Detection rule: >100,000 → raw Rupees; 0.001–2,000 → already Crores; else garbage.
# Upper limit 2,000 Cr excludes GEM entries where year (2025/2026) was stored as amount.
RUPEES_THRESHOLD  = 100_000       # amounts above this are raw Rupees
CRORE_MAX         = 2_000         # amounts in this range are Crores already
MIN_VALID_AMOUNT  = 10_000        # raw Rupees floor; anything below is noise
STATUS_COLORS     = {"Active": "#1A9E6A", "Awarded": "#E8981E", "Completed": "#0E8C8C"}

# Sectors that are unclassified catch-alls — moved to bottom of filter lists
UNCLASSIFIED_SECTORS = {"Other", "Works", "General"}

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=Inter:wght@400;500;600&display=swap');

:root {
  --navy:#0D1B2A;    --mid-navy:#1B2A3B; --teal:#0E8C8C;
  --amber:#E8981E;   --slate:#3A5068;    --muted:#7A90A4;
  --bg:#EDF2F7;      --card:#FFFFFF;     --border:#B0C8E0;
}
html, body, [class*="css"] { font-family:'Inter',sans-serif !important; }

/* ── KPI metric cards ── */
div[data-testid="metric-container"] {
  background:linear-gradient(145deg,#FFFFFF,#DFF0FA);
  border:1px solid #B0C8E0; border-radius:12px; padding:14px 18px;
  border-left:6px solid #E8981E;
  box-shadow:0 2px 8px rgba(14,140,140,0.12);
}
/* Metric value number — amber */
div[data-testid="metric-container"] [data-testid="metric-value"] > div {
  color:#E8981E !important; font-weight:700 !important;
}
/* Metric label — teal */
div[data-testid="metric-container"] label {
  color:#0E8C8C !important; font-weight:600 !important; font-size:.8rem !important;
}

/* ── Insight / briefing card ── */
.insight-card {
  background:linear-gradient(135deg,#E8F6F6,#D4EDF8);
  border:2px solid #0E8C8C; border-left:6px solid #E8981E;
  border-radius:12px; padding:18px 22px; margin:10px 0;
}
.insight-card h4 { color:#E8981E; margin:0 0 8px 0; font-size:1rem; font-weight:700; }
.insight-card p  { color:#0D1B2A; line-height:1.65; margin:0; font-size:.88rem; }

/* ── Spotlight cards ── */
.spotlight-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:10px 0 14px 0; }
.spotlight {
  background:linear-gradient(160deg,#FFFFFF,#E8F4FB);
  border:1px solid #B0C8E0; border-top:4px solid #0E8C8C;
  border-radius:14px; padding:14px 16px; text-align:center;
  box-shadow:0 2px 6px rgba(13,27,42,0.08);
}
.spotlight-icon { font-size:1.8rem; display:block; margin-bottom:4px; }
.spotlight-val  { font-family:'Rajdhani',sans-serif; font-size:1.3rem;
                  font-weight:700; color:#E8981E; display:block; }
.spotlight-lbl  { font-size:.73rem; color:#0E8C8C; margin-top:3px; font-weight:700;
                  text-transform:uppercase; letter-spacing:.8px; }
.spotlight-desc { font-size:.70rem; color:#3A5068; margin-top:5px; line-height:1.4; }

/* ── Section labels & descriptions ── */
.section-label {
  font-family:'Rajdhani',sans-serif; font-size:1.1rem; font-weight:700;
  color:#E8981E; letter-spacing:0.5px; margin:4px 0 2px 0;
  border-left:3px solid #0E8C8C; padding-left:8px;
}
.section-desc { font-size:.78rem; color:#3A5068; margin-bottom:6px; line-height:1.5; }

/* ── Data note ── */
.data-note { background:#D4EDF8; border:1px solid #0E8C8C; border-radius:6px;
             padding:6px 12px; font-size:.76rem; color:#0D1B2A; margin:4px 0 8px 0; }

/* ── Tabs ── */
button[data-baseweb="tab"] {
  font-family:'Rajdhani',sans-serif !important;
  font-size:.95rem !important; font-weight:700 !important;
  color:#3A5068 !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
  color:#E8981E !important;
  border-bottom:3px solid #E8981E !important;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"]>div:first-child {
  background:linear-gradient(180deg,#050D18 0%,#0D1B2A 60%,#060F1C 100%);
}
section[data-testid="stSidebar"] * { color:#D8E8F5 !important; }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] h4 { color:#E8981E !important; }
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] select {
  background:#142338 !important;
  border:1px solid #0E8C8C !important;
  color:#FFFFFF !important;
}
/* Streamlit BaseWeb selectbox dropdowns in sidebar */
section[data-testid="stSidebar"] [data-baseweb="select"] > div:first-child {
  background:#142338 !important;
  border:1px solid #0E8C8C !important;
  border-radius:8px !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] [data-testid="stWidgetLabel"] {
  color:#E8981E !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] svg {
  fill:#0E8C8C !important;
}
/* Dropdown option list (popover) */
[data-baseweb="popover"] ul, [data-baseweb="menu"] {
  background:#0D1B2A !important;
  border:1px solid #0E8C8C !important;
}
[data-baseweb="popover"] li, [data-baseweb="menu"] li {
  background:#0D1B2A !important;
  color:#D8E8F5 !important;
}
[data-baseweb="popover"] li:hover, [data-baseweb="menu"] li:hover {
  background:#1B3A5C !important;
  color:#E8981E !important;
}
[data-baseweb="option"][aria-selected="true"] {
  background:#1B3A5C !important;
  color:#E8981E !important;
}
section[data-testid="stSidebar"] .stMultiSelect [data-baseweb="tag"] {
  background:#0E8C8C !important;
  color:#FFFFFF !important;
}

/* ── Table header ── */
thead tr th { background:#0D1B2A !important; color:#E8981E !important;
              font-weight:700 !important; letter-spacing:.4px; }
tbody tr:nth-child(even) td { background:#F0F7FC !important; }

/* ── Badge ── */
.badge {
  display:inline-block; padding:4px 16px; border-radius:20px;
  background:linear-gradient(135deg,#E8981E,#0E8C8C);
  color:white; font-size:.78rem; font-weight:700; letter-spacing:.8px;
  box-shadow:0 2px 8px rgba(232,152,30,0.4);
}
/* ── Aggregation warning ── */
.agg-warn { background:#FFF8E6; border:2px solid #E8981E; border-radius:8px;
            padding:8px 14px; font-size:.82rem; color:#5A3A10; margin-bottom:8px; }
</style>
""", unsafe_allow_html=True)


# ── Load & normalise data ──────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def get_data() -> pd.DataFrame:
    raw = load_enterprise_tender_stream()
    # Cast categorical columns to plain str (Plotly groupby max() fails on unordered Categorical)
    for col in ["sector", "state", "district", "department", "source",
                "status", "contractor_name", "block", "title"]:
        if col in raw.columns:
            raw[col] = raw[col].astype(str).replace("nan", "")
    # DB has mixed units — normalise everything to Crores for display
    def _to_crores(x):
        if x is None or x != x or x == 0:  return 0.0       # None / NaN / zero
        x = float(x)
        if x > RUPEES_THRESHOLD:            return x / RUPEES_PER_CRORE  # raw Rupees
        if x > 0.001:                       return x          # already in Crores
        return 0.0                                            # suspiciously tiny
    raw["amount_cr"]  = raw["allocated_amount"].apply(_to_crores)
    # has_budget = either raw-Rupee format (>100K) or Crore format (0.001–5000)
    raw["has_budget"] = (raw["allocated_amount"] > RUPEES_THRESHOLD) | (
        raw["allocated_amount"].between(0.001, CRORE_MAX, inclusive="both")
    )
    # normalise sector: merge tiny unclassified groups into "Unclassified"
    raw["sector_display"] = raw["sector"].apply(
        lambda s: "Unclassified" if s in UNCLASSIFIED_SECTORS else s
    )
    return raw


@st.cache_data(ttl=3600, show_spinner=False)
def get_hierarchy(_df: pd.DataFrame) -> dict:
    return get_full_hierarchy(_df)


with st.spinner("🔄 Loading enterprise tender database…"):
    df_master = get_data()
    hierarchy  = get_hierarchy(df_master)

# Sector list: classified first (alphabetical), then Unclassified last
_classified   = sorted(s for s in df_master["sector_display"].unique() if s != "Unclassified")
_unclassified = ["Unclassified"] if "Unclassified" in df_master["sector_display"].values else []
all_sectors_ordered = _classified + _unclassified


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:14px 0 10px 0;text-align:center;">
      <div style="font-family:'Rajdhani',sans-serif;font-size:1.6rem;font-weight:700;
                  background:linear-gradient(135deg,#E8981E,#0E8C8C);
                  -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
        🪷 DivyaDrishti
      </div>
      <div style="font-size:.68rem;letter-spacing:3px;color:#7AB8D8;margin-top:3px;">
        PROCUREMENT INTELLIGENCE
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.caption(
        f"**{len(df_master):,}** tenders · "
        f"**{df_master['state'].nunique()}** states · "
        f"**{df_master['has_budget'].sum():,}** with budget data"
    )
    st.markdown("---")

    # ── Search ─────────────────────────────────────────────────────────────────
    st.markdown("#### 🔍 Keyword Search")
    search_query = st.text_input("Search", placeholder="road, hospital, school…",
                                 label_visibility="collapsed")

    st.markdown("---")
    st.markdown("#### 📊 Drill-Down Filters")

    # Sector filter uses display name (classified / Unclassified)
    selected_sector_display = st.selectbox("Sector", [ALL] + all_sectors_ordered)

    # Map display sector back to actual DB values
    if selected_sector_display == ALL:
        _sector_mask = pd.Series([True] * len(df_master), index=df_master.index)
    elif selected_sector_display == "Unclassified":
        _sector_mask = df_master["sector"].isin(UNCLASSIFIED_SECTORS)
    else:
        _sector_mask = df_master["sector_display"] == selected_sector_display

    _sd = df_master[_sector_mask]

    dept_options = [ALL] + sorted(_sd["department"].dropna().unique().tolist())
    selected_dept = st.selectbox("Department", dept_options)
    if selected_dept != ALL:
        _sd = _sd[_sd["department"] == selected_dept]

    state_options = [ALL] + sorted(s for s in _sd["state"].dropna().unique() if s and s != "Central (CPPP)")
    selected_state = st.selectbox("State / UT", state_options)
    if selected_state != ALL:
        _sd = _sd[_sd["state"] == selected_state]

    district_options = [ALL] + sorted(_sd["district"].dropna().unique().tolist())
    selected_district = st.selectbox("District", district_options)
    if selected_district != ALL:
        _sd = _sd[_sd["district"] == selected_district]

    block_options = [ALL] + sorted(_sd["block"].dropna().unique().tolist())
    selected_block = st.selectbox("Block / Taluka", block_options)

    st.markdown("---")
    st.markdown("#### ⚙️ Additional Filters")

    all_statuses      = sorted(df_master["status"].dropna().unique().tolist())
    selected_statuses = st.multiselect("Status", all_statuses, default=all_statuses)

    # FIX-02: opt-in budget filter (avoids silently dropping 80% of tenders)
    budget_only = st.checkbox("Only tenders with reported budget")

    st.markdown("---")

    with st.expander("🛠️ Developer Tools", expanded=False):
        try:
            from repository.db import DB_PATH
            _cnt = __import__("sqlite3").connect(DB_PATH).execute(
                "SELECT COUNT(*) FROM tenders").fetchone()[0]
            st.success(f"📡 Real DB — {_cnt:,} scraped tenders")
        except Exception:
            st.warning("🧪 Preview mode — seed data.")

        st.markdown("**▶ Run Scraper**")
        _sources = st.multiselect(
            "Sources",
            ["cppp","gem","states","datagov","pmgsy","biharv2","cgstate",
             "up_misc","up_sectors","up_power","psu_html","ongc","nhai","coal_india"],
            default=["biharv2","cgstate"],
        )
        _pages   = st.number_input("Pages per portal", 1, 200, 10)
        _api_key = st.text_input("data.gov.in API Key", type="password", placeholder="Optional")
        if st.button("▶ Start Scraping", type="primary", use_container_width=True):
            import subprocess
            cmd = [sys.executable, str(Path(__file__).parent / "cli.py"),
                   "--sources"] + _sources + ["--pages", str(_pages)]
            if _api_key:
                cmd += ["--api-key", _api_key]
            with st.spinner("Scraping live portals…"):
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                if result.returncode == 0:
                    st.success("✅ Complete")
                    st.cache_data.clear(); st.rerun()
                else:
                    st.error("Scraper error")
                    st.code((result.stderr or result.stdout)[-2000:])

        if st.button("🔄 Refresh Display", use_container_width=True):
            st.cache_data.clear(); st.rerun()
        if st.button("🔍 Reclassify DB", use_container_width=True):
            import subprocess
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "cli.py"), "--reclassify"],
                capture_output=True, text=True, timeout=300)
            st.success("✅ Done") if result.returncode == 0 else st.error("Failed")
            st.cache_data.clear(); st.rerun()

    with st.expander("📡 Portal Health", expanded=False):
        try:
            _health = load_health_log()
            if _health is not None and not _health.empty:
                ok  = int((_health["status"] == "ok").sum())
                bad = int((_health["status"] != "ok").sum())
                st.metric("OK / Failed", f"{ok} / {bad}")
                st.dataframe(
                    _health[["source","status","records_fetched","logged_at"]].head(15),
                    use_container_width=True, hide_index=True,
                )
        except Exception:
            st.caption("No health log yet.")


# ── Apply filters ──────────────────────────────────────────────────────────────
df = df_master.copy()

# Sector filter
if selected_sector_display == "Unclassified":
    df = df[df["sector"].isin(UNCLASSIFIED_SECTORS)]
elif selected_sector_display != ALL:
    df = df[df["sector_display"] == selected_sector_display]

if selected_dept     != ALL: df = df[df["department"] == selected_dept]
if selected_state    != ALL: df = df[df["state"]      == selected_state]
if selected_district != ALL: df = df[df["district"]   == selected_district]
if selected_block    != ALL: df = df[df["block"]      == selected_block]

df = df[df["status"].isin(selected_statuses)]
if budget_only:
    df = df[df["has_budget"]]   # FIX-02: opt-in, not default

if search_query.strip():
    q    = search_query.strip().lower()
    mask = (df["title"].str.lower().str.contains(q, na=False) |
            df["department"].str.lower().str.contains(q, na=False) |
            df["tender_id"].str.lower().str.contains(q, na=False))
    df = df[mask]

# ── Drill level ────────────────────────────────────────────────────────────────
if   selected_state    == ALL: drill_level, level_label = "national", "🌏 National — All States"
elif selected_district == ALL: drill_level, level_label = "state",    f"📍 {selected_state}"
elif selected_block    == ALL: drill_level, level_label = "district",  f"🏙️ {selected_district}, {selected_state}"
else:                          drill_level, level_label = "block",     f"🔍 {selected_block}, {selected_district}"

render_mode = "scatter" if len(df) <= SCATTER_LIMIT else "aggregated"

# ── KPIs ───────────────────────────────────────────────────────────────────────
total_count     = len(df)
active_count    = int((df["status"] == "Active").sum())
awarded_count   = int((df["status"] == "Awarded").sum())
budget_df       = df[df["has_budget"]]
budget_coverage = int(df["has_budget"].sum())
budget_pct      = budget_coverage / max(total_count, 1) * 100
top_budget_cr   = float(budget_df["amount_cr"].max()) if not budget_df.empty else 0
top_row         = budget_df.loc[budget_df["amount_cr"].idxmax()] if not budget_df.empty else None
sector_count    = df["sector_display"].nunique()
state_count     = df[df["state"] != "Central (CPPP)"]["state"].nunique()


# ── Auto-Narrative Engine ──────────────────────────────────────────────────────
def build_narrative(df: pd.DataFrame, level: str, state: str, district: str) -> str:
    if df.empty:
        return "No tenders match the current filters. Please broaden your selection."

    n          = len(df)
    # Use sector_display for cleaner labelling
    top_sector = df.groupby("sector_display").size().idxmax()
    top_sector_pct = df["sector_display"].value_counts(normalize=True).iloc[0] * 100
    top_state_name = (df.groupby("state").size().idxmax()
                      if level == "national" else state)
    active_pct = active_count / max(n, 1) * 100

    b_df = df[df["has_budget"]]
    budget_note = (
        f"Budget data is available for {len(b_df):,} of these ({len(b_df)/max(n,1)*100:.0f}%),"
        f" totalling ₹{b_df['amount_cr'].sum():,.1f} Cr."
        if not b_df.empty else "Budget amounts are not yet reported for most tenders in this view."
    )

    top_dept = df.groupby("department").size().idxmax() if n > 0 else "—"
    sources_list = ", ".join(df["source"].value_counts().head(3).index.tolist())

    loc_phrase = (
        f"Across {df['state'].nunique()} states and UTs" if level == "national" else
        f"Within {state}" if level == "state" else
        f"In {district} district"
    )

    line1 = f"{loc_phrase}, **{n:,} government procurement tenders** are in scope — **{active_pct:.0f}% Active**."
    line2 = f"**{top_sector}** is the dominant sector at **{top_sector_pct:.0f}%** of all tenders, led by *{top_dept[:50]}*."
    line3 = budget_note
    line4 = (f"Data flows from **{df['source'].nunique()}** portal(s) including {sources_list}."
             if df["source"].nunique() > 0 else "")

    return f"{line1}<br><br>{line2}<br><br>{line3}<br><br>{line4}"


narrative_html = build_narrative(df, drill_level, selected_state, selected_district)


# ── PAGE HEADER ────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="display:flex;align-items:center;gap:16px;padding:6px 0 4px 0;">
  <div style="font-size:3rem;line-height:1;">🪷</div>
  <div>
    <div style="font-family:'Rajdhani',sans-serif;font-size:2.2rem;font-weight:700;
                line-height:1.05;">
      <span style="color:#E8981E;">Divya</span><span style="color:#0D1B2A;">Drishti</span>
    </div>
    <div style="font-size:.78rem;color:#0E8C8C;letter-spacing:2px;">दिव्यदृष्टि</div>
    <div style="font-size:.73rem;color:#3A5068;margin-top:2px;">
      Pan-India Procurement Intelligence · {df_master["state"].nunique()} States/UTs · {len(df_master):,} Tenders
    </div>
  </div>
  <div style="margin-left:auto;">
    <span class="badge">{level_label}</span>
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown("<div style='margin:4px 0'></div>", unsafe_allow_html=True)

if df.empty:
    st.warning("⚠️ No tenders match the current filter combination.")
    st.stop()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TABS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
tab1, tab2, tab3, tab4 = st.tabs([
    "🌐 Overview",
    "📍 State Explorer",
    "📊 Sector & Trends",
    "📄 Data & Sources",
])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 1 · OVERVIEW
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab1:

    # ── KPI Strip ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("📋 Total Tenders",   f"{total_count:,}")
    c2.metric("✅ Active",          f"{active_count:,}")
    c3.metric("🏅 Awarded",         f"{awarded_count:,}")
    c4.metric("🗺️ States Covered",  f"{state_count}")
    c5.metric("📂 Sectors",         f"{sector_count}")
    _cov_delta = f"{budget_coverage:,} tenders"
    c6.metric("💰 Budget Coverage", f"{budget_pct:.0f}%", delta=_cov_delta, delta_color="off")

    st.markdown("<div style='margin:8px 0'></div>", unsafe_allow_html=True)

    # ── Spotlight Cards ───────────────────────────────────────────────────────
    top_state_by_cnt   = df.groupby("state").size().idxmax() if total_count else "—"
    top_state_cnt      = int(df.groupby("state").size().max()) if total_count else 0
    top_sector_by_cnt  = df.groupby("sector_display").size().idxmax() if total_count else "—"
    top_sector_cnt_val = int(df.groupby("sector_display").size().max()) if total_count else 0
    big_tender_title   = str(top_row["title"])[:40] + "…" if top_row is not None else "—"
    top_portal         = df["source"].value_counts().index[0] if total_count else "—"
    top_portal_cnt     = int(df["source"].value_counts().iloc[0]) if total_count else 0
    # Shorten long portal codes for display
    top_portal_short   = str(top_portal).split("/")[0][:16] if "/" in str(top_portal) else str(top_portal)[:16]

    st.markdown(f"""
    <div class="spotlight-grid">
      <div class="spotlight">
        <span class="spotlight-icon">🏆</span>
        <span class="spotlight-val">{str(top_state_by_cnt)[:16]}</span>
        <div class="spotlight-lbl">Top State</div>
        <div class="spotlight-desc">{top_state_cnt:,} tenders — most active<br>procurement geography</div>
      </div>
      <div class="spotlight">
        <span class="spotlight-icon">🔥</span>
        <span class="spotlight-val">{str(top_sector_by_cnt)[:18]}</span>
        <div class="spotlight-lbl">Hottest Sector</div>
        <div class="spotlight-desc">{top_sector_cnt_val:,} tenders — highest<br>volume in current view</div>
      </div>
      <div class="spotlight">
        <span class="spotlight-icon">💎</span>
        <span class="spotlight-val">₹{top_budget_cr:,.1f} Cr</span>
        <div class="spotlight-lbl">Biggest Tender</div>
        <div class="spotlight-desc">{big_tender_title}</div>
      </div>
      <div class="spotlight">
        <span class="spotlight-icon">🔌</span>
        <span class="spotlight-val">{top_portal_short}</span>
        <div class="spotlight-lbl">Most Active Portal</div>
        <div class="spotlight-desc">{top_portal_cnt:,} tenders —<br>highest-volume gateway</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Narrative ─────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="insight-card">
      <h4>🧠 Procurement Intelligence Briefing</h4>
      <p>{narrative_html}</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='margin:4px 0'></div>", unsafe_allow_html=True)

    # ── Map ───────────────────────────────────────────────────────────────────
    st.markdown('<div class="section-label">🗺️ Procurement Geography Map</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">Every dot is a tender. Colour = sector. '
        'Roads and pipelines draw as coloured lines. '
        'Zoom in to district level for project-site precision.</div>',
        unsafe_allow_html=True,
    )

    map_col, info_col = st.columns([4, 1])
    view = get_view_config(
        df,
        selected_state    if selected_state    != ALL else None,
        selected_district if selected_district != ALL else None,
    )

    with map_col:
        if render_mode == "aggregated":
            st.markdown(
                '<div class="agg-warn">⚡ Aggregated view — narrow filters to enter scatter mode.</div>',
                unsafe_allow_html=True)
            agg_col = "state" if drill_level in ("national","state") else "district"
            agg_df  = server_side_aggregate(df, agg_col)
            if agg_col == "state":
                agg_df["lat"] = agg_df["state"].map(lambda s: STATE_CENTERS.get(s,{}).get("lat",22.5))
                agg_df["lon"] = agg_df["state"].map(lambda s: STATE_CENTERS.get(s,{}).get("lon",82.5))
            fig_map = px.scatter_mapbox(
                agg_df, lat="lat", lon="lon",
                size="count", color="count",
                color_continuous_scale="YlOrRd",
                hover_name=agg_col, size_max=55, height=520,
                mapbox_style="open-street-map",
                center={"lat":view["lat"],"lon":view["lon"]}, zoom=view["zoom"],
                hover_data={"count":True,"lat":False,"lon":False},
                labels={"count":"Tenders"},
            )
            fig_map.update_coloraxes(colorbar_title="Tenders")
        else:
            df_plot = df.copy()
            df_plot["bubble"] = 14.0
            df_plot["amt_fmt"] = df_plot.apply(
                lambda r: f"₹{r['amount_cr']:,.2f} Cr" if r["has_budget"] else "Not reported", axis=1)
            for col in ("contractor_name","start_date","end_date"):
                if col not in df_plot.columns: df_plot[col] = "—"
                df_plot[col] = df_plot[col].fillna("—").replace("","—")

            linear_mask = (df_plot.get("latitude2", pd.Series(dtype=float)).notna() &
                           df_plot.get("longitude2", pd.Series(dtype=float)).notna())
            df_lines  = df_plot[linear_mask] if "latitude2" in df_plot.columns else df_plot.iloc[0:0]
            df_points = df_plot[~linear_mask] if "latitude2" in df_plot.columns else df_plot

            fig_map = px.scatter_mapbox(
                df_points if not df_points.empty else df_plot,
                lat="latitude", lon="longitude",
                size="bubble", color="sector_display",
                color_discrete_map={**SECTOR_COLORS, "Unclassified":"#AAAAAA"},
                hover_name="title", height=520,
                mapbox_style="open-street-map",
                center={"lat":view["lat"],"lon":view["lon"]}, zoom=view["zoom"],
                hover_data={"department":True,"amt_fmt":True,"status":True,
                            "state":True,"district":True,
                            "bubble":False,"latitude":False,"longitude":False},
                labels={"amt_fmt":"Budget","sector_display":"Sector"},
            )
            fig_map.update_traces(marker=dict(opacity=0.85))

            if not df_lines.empty:
                for sector, grp in df_lines.groupby("sector_display", observed=True):
                    color = SECTOR_COLORS.get(str(sector),"#AAAAAA")
                    lats, lons = [], []
                    for _, r in grp.iterrows():
                        lats.extend([float(r["latitude"]), float(r["latitude2"]), None])
                        lons.extend([float(r["longitude"]),float(r["longitude2"]),None])
                    fig_map.add_trace(go.Scattermapbox(
                        lat=lats, lon=lons, mode="lines",
                        line=dict(width=4, color=color), opacity=0.75,
                        hoverinfo="skip", showlegend=False))

            # District boundary ring when zoomed in
            if drill_level in ("district","block") and selected_state in DISTRICT_COORDINATES:
                if selected_district in DISTRICT_COORDINATES[selected_state]:
                    c = DISTRICT_COORDINATES[selected_state][selected_district]
                    r_km = 25 if drill_level == "district" else 8
                    r_lat = r_km / 111.0
                    r_lon = r_km / (111.0 * math.cos(math.radians(c["lat"])))
                    clats = [c["lat"] + r_lat*math.sin(t) for t in np.linspace(0, 2*math.pi, 60)]
                    clons = [c["lon"] + r_lon*math.cos(t) for t in np.linspace(0, 2*math.pi, 60)]
                    fig_map.add_trace(go.Scattermapbox(
                        lat=clats, lon=clons, mode="lines",
                        line=dict(width=2, color="rgba(196,118,41,0.6)"),
                        fill="toself", fillcolor="rgba(196,118,41,0.05)",
                        hoverinfo="skip", showlegend=False))

        fig_map.update_layout(
            margin=dict(l=0,r=0,t=0,b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.01,
                        xanchor="right", x=1, font=dict(size=10)))
        st.plotly_chart(fig_map, use_container_width=True)

    with info_col:
        st.markdown("#### 📌 View Info")
        st.markdown(f"**Mode:** `{render_mode}`")
        st.markdown(f"**Records:** `{total_count:,}`")
        st.markdown("---")
        st.markdown("**Status**")
        for s, col in STATUS_COLORS.items():
            cnt = int((df["status"] == s).sum())
            if cnt:
                st.markdown(f'<span style="color:{col};font-weight:700;">●</span> {s}: {cnt:,}',
                            unsafe_allow_html=True)
        st.markdown("---")
        if render_mode == "scatter":
            st.markdown("**Sectors**")
            for sec in sorted(df["sector_display"].unique()):
                col = SECTOR_COLORS.get(sec,"#AAAAAA")
                cnt = int((df["sector_display"] == sec).sum())
                st.markdown(
                    f'<span style="background:{col};border-radius:50%;display:inline-block;'
                    f'width:9px;height:9px;margin-right:4px;"></span>{sec[:16]} ({cnt})',
                    unsafe_allow_html=True)
        else:
            grp  = "state" if drill_level in ("national","state") else "district"
            top5 = df.groupby(grp).size().nlargest(5)
            st.markdown(f"**Top {grp.title()}s**")
            for name, cnt in top5.items():
                st.caption(f"{str(name)[:18]}: {cnt:,}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 2 · STATE EXPLORER  (new tab)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab2:

    # ── State Comparison Bar ───────────────────────────────────────────────────
    st.markdown('<div class="section-label">🏛️ State Comparison — Tender Volume</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Top 20 states ranked by number of tenders. Bar colour shows the dominant sector in that state. '
        'Hover to see the budget amount where available. '
        'States with few tenders may indicate limited portal coverage, not low activity.'
        '</div>', unsafe_allow_html=True)

    state_agg = (df[df["state"] != "Central (CPPP)"]
                 .groupby("state")
                 .agg(Tenders=("tender_id","count"),
                      Budget_Cr=("amount_cr","sum"),
                      Top_Sector=("sector_display", lambda x: x.value_counts().index[0]))
                 .reset_index()
                 .sort_values("Tenders", ascending=False)
                 .head(20))

    if not state_agg.empty:
        fig_state = px.bar(
            state_agg.sort_values("Tenders"),
            x="Tenders", y="state", orientation="h",
            color="Top_Sector",
            color_discrete_map={**SECTOR_COLORS, "Unclassified":"#AAAAAA"},
            text="Tenders",
            hover_data={"Budget_Cr":":.1f","Top_Sector":True,"Tenders":True},
            labels={"state":"State","Budget_Cr":"Budget (₹ Cr)","Top_Sector":"Dominant Sector"},
            height=520,
        )
        fig_state.update_traces(texttemplate="%{text:,}", textposition="outside")
        fig_state.update_layout(
            margin=dict(t=10,b=10,l=10,r=60),
            xaxis=dict(title="Number of Tenders"),
            yaxis=dict(tickfont=dict(size=10)),
            legend=dict(orientation="v", x=1.02, y=1, font=dict(size=9)),
            showlegend=True,
        )
        st.plotly_chart(fig_state, use_container_width=True)

    # ── Sector × State Activity Heatmap ───────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">🌡️ Sector × State Activity Heatmap</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Each cell = number of tenders for that State × Sector combination. '
        'Dark = high activity. White = zero tenders (a procurement blind-spot). '
        'Primary metric is <b>tender count</b> — more reliable than budget '
        'since 80% of tenders do not report a budget amount.'
        '</div>', unsafe_allow_html=True)
    st.markdown('<div class="data-note">📊 Count-based (not budget) — budget data available for only 20% of tenders.</div>',
                unsafe_allow_html=True)

    top_hm_states = (df[df["state"] != "Central (CPPP)"]
                     .groupby("state").size().nlargest(15).index.tolist())
    hm_df = (df[df["state"].isin(top_hm_states)]
             .groupby(["state","sector_display"])
             .size().unstack(fill_value=0))
    hm_df = hm_df.reindex(index=top_hm_states, fill_value=0)

    if not hm_df.empty:
        fig_hm = go.Figure(go.Heatmap(
            z=hm_df.values,
            x=[str(c) for c in hm_df.columns],
            y=[str(r) for r in hm_df.index],
            colorscale=[
                [0,    "#F4F7FB"],
                [0.2,  "#A8D4E8"],
                [0.5,  "#0E8C8C"],
                [0.8,  "#0D1B2A"],
                [1.0,  "#060F1C"],
            ],
            hovertemplate="<b>%{y} — %{x}</b><br>%{z:,} tenders<extra></extra>",
            text=[[str(int(v)) if v > 0 else "" for v in row] for row in hm_df.values],
            texttemplate="%{text}",
            textfont=dict(size=9),
            colorbar=dict(title="Tenders", thickness=14),
        ))
        fig_hm.update_layout(
            height=460,
            margin=dict(t=10,b=10,l=130,r=10),
            xaxis=dict(tickfont=dict(size=10), tickangle=-35),
            yaxis=dict(tickfont=dict(size=10)),
        )
        st.plotly_chart(fig_hm, use_container_width=True)

    # ── Top Districts (within selected state) ──────────────────────────────────
    if selected_state != ALL:
        st.markdown("---")
        st.markdown(f'<div class="section-label">📍 Top Districts in {selected_state}</div>',
                    unsafe_allow_html=True)
        dist_agg = (df[df["state"] == selected_state]
                    .groupby("district")
                    .agg(Tenders=("tender_id","count"),
                         Budget_Cr=("amount_cr","sum"),
                         Sectors=("sector_display","nunique"))
                    .reset_index()
                    .sort_values("Tenders", ascending=False)
                    .head(15))
        if not dist_agg.empty:
            fig_dist = px.bar(
                dist_agg.sort_values("Tenders"),
                x="Tenders", y="district", orientation="h",
                color="Budget_Cr", color_continuous_scale=["#D4EAF7","#0E8C8C","#0D1B2A"],
                text="Tenders",
                hover_data={"Budget_Cr":":.1f","Sectors":True},
                labels={"district":"District","Budget_Cr":"Budget (₹ Cr)"},
                height=max(350, len(dist_agg)*28),
            )
            fig_dist.update_traces(texttemplate="%{text:,}", textposition="outside")
            fig_dist.update_layout(
                margin=dict(t=10,b=10,l=5,r=60),
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig_dist, use_container_width=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 3 · SECTOR & TRENDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab3:

    # ── Sector Breakdown Bar ───────────────────────────────────────────────────
    st.markdown('<div class="section-label">📊 Sector Breakdown</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'All 14 sector buckets ranked by tender count. "Unclassified" groups tenders '
        'tagged as Other/Works/General — areas where the classifier needs improvement. '
        'Bar length = tender volume; the secondary label shows budget where available.'
        '</div>', unsafe_allow_html=True)

    sec_agg = (df.groupby("sector_display")
               .agg(Tenders=("tender_id","count"),
                    Budget_Cr=("amount_cr","sum"),
                    has_budget_count=("has_budget","sum"))
               .reset_index()
               .sort_values("Tenders", ascending=False))
    sec_agg["Budget_Label"] = sec_agg["Budget_Cr"].apply(
        lambda x: f"₹{x:,.0f} Cr" if x > 0 else "—")

    fig_sec = px.bar(
        sec_agg.sort_values("Tenders"),
        x="Tenders", y="sector_display", orientation="h",
        color="sector_display",
        color_discrete_map={**SECTOR_COLORS, "Unclassified":"#AAAAAA"},
        text="Tenders",
        hover_data={"Budget_Label":True,"has_budget_count":True},
        labels={"sector_display":"Sector","Budget_Label":"Budget","has_budget_count":"With Budget"},
        height=430,
    )
    fig_sec.update_traces(texttemplate="%{text:,}", textposition="outside")
    fig_sec.update_layout(
        showlegend=False,
        margin=dict(t=10,b=10,l=5,r=60),
        xaxis=dict(title="Number of Tenders"),
    )
    st.plotly_chart(fig_sec, use_container_width=True)

    # ── Treemap (where budget available) ──────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">🌳 Budget Treemap — State → Sector</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Area = total ₹ Crores for tenders that reported a budget amount. '
        'Only the 8,355 tenders (20%) with valid budget data appear here. '
        'Bihar and Coal India dominate because those portals report amounts more consistently.'
        '</div>', unsafe_allow_html=True)
    st.markdown('<div class="data-note">📊 Shows only the 20% of tenders that report a budget amount.</div>',
                unsafe_allow_html=True)

    treemap_df = (
        budget_df
        .groupby(["state","sector_display"])["amount_cr"]
        .sum().reset_index()
        .rename(columns={"amount_cr":"₹ Cr","sector_display":"Sector"})
    )
    treemap_df = treemap_df[treemap_df["₹ Cr"] > 0.01]

    if not treemap_df.empty:
        fig_tree = px.treemap(
            treemap_df,
            path=[px.Constant("India"), "state", "Sector"],
            values="₹ Cr",
            color="Sector",
            color_discrete_map={**SECTOR_COLORS, "Unclassified":"#AAAAAA"},
            hover_data={"₹ Cr":":.2f"},
            height=480,
        )
        fig_tree.update_traces(
            texttemplate="<b>%{label}</b><br>₹%{value:.1f} Cr",
            textfont=dict(size=11),
            marker=dict(cornerradius=4),
        )
        fig_tree.update_layout(margin=dict(t=10,b=10,l=10,r=10))
        st.plotly_chart(fig_tree, use_container_width=True)
    else:
        st.info("No budget data with current filters.")

    # ── Sankey (by count) ─────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">🌊 Budget Flow — Portal → State → Sector</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Follow the procurement journey: which <b>portal</b> captured it, '
        'which <b>state</b> it belongs to, and which <b>sector</b> it funds. '
        'Width of each flow = number of tenders (using count, not budget, for completeness).'
        '</div>', unsafe_allow_html=True)

    # Group long source codes into readable names
    def _shorten_source(s: str) -> str:
        parts = s.split("/")
        if len(parts) >= 2:
            return f"{parts[-1][:14]}" if parts[-1] else parts[0][:14]
        return s[:16]

    top_src_raw  = df.groupby("source").size().nlargest(8).index.tolist()
    top_states_sk = df.groupby("state").size().nlargest(10).index.tolist()
    df_sk = df[df["source"].isin(top_src_raw) & df["state"].isin(top_states_sk)].copy()
    df_sk["src_label"] = df_sk["source"].apply(_shorten_source)
    df_sk["sec_label"]  = df_sk["sector_display"]

    src_labels   = df_sk.groupby("source")["src_label"].first().reindex(top_src_raw).tolist()
    all_secs_sk  = sorted(df_sk["sec_label"].unique().tolist())
    node_labels  = src_labels + top_states_sk + all_secs_sk
    node_idx     = {n: i for i, n in enumerate(node_labels)}
    src_to_label = {src: lbl for src, lbl in zip(top_src_raw, src_labels)}

    sk_links = []
    for (src, st_), grp in df_sk.groupby(["source","state"]):
        lbl = src_to_label.get(src, src[:14])
        if lbl in node_idx and st_ in node_idx:
            sk_links.append((node_idx[lbl], node_idx[st_], len(grp)))
    for (st_, sec), grp in df_sk.groupby(["state","sec_label"]):
        if st_ in node_idx and sec in node_idx:
            sk_links.append((node_idx[st_], node_idx[sec], len(grp)))
    sk_links = [(s,t,v) for s,t,v in sk_links if v > 0]

    if sk_links:
        node_colors = (
            ["rgba(196,118,41,0.8)"] * len(src_labels) +
            ["rgba(123,45,66,0.7)"]  * len(top_states_sk) +
            [SECTOR_COLORS.get(s,"#AAAAAA") for s in all_secs_sk]
        )
        fig_sankey = go.Figure(go.Sankey(
            node=dict(
                pad=12, thickness=20,
                line=dict(color="#C4D4E3", width=0.5),
                label=node_labels,
                color=node_colors,
                hovertemplate="%{label}<br>%{value:,} tenders<extra></extra>",
            ),
            link=dict(
                source=[s for s,t,v in sk_links],
                target=[t for s,t,v in sk_links],
                value =[v for s,t,v in sk_links],
                color ="rgba(196,118,41,0.15)",
                hovertemplate="%{source.label} → %{target.label}<br>%{value:,} tenders<extra></extra>",
            ),
        ))
        fig_sankey.update_layout(
            height=460, font=dict(size=11, family="Inter"),
            margin=dict(t=10,b=10,l=10,r=10))
        st.plotly_chart(fig_sankey, use_container_width=True)
    else:
        st.info("Not enough overlapping data for Sankey. Broaden filters.")

    # ── Timeline ──────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">⏱️ Tender Activity Timeline</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Monthly tender count based on start_date (falls back to scraped_at if start_date missing). '
        'Peaks indicate procurement bursts — common before March financial year-end.'
        '</div>', unsafe_allow_html=True)

    tl_df = df.copy()
    tl_df["date_col"] = pd.to_datetime(tl_df["start_date"], errors="coerce")
    if tl_df["date_col"].isna().all():
        tl_df["date_col"] = pd.to_datetime(tl_df.get("scraped_at",""), errors="coerce")
    tl_df = tl_df.dropna(subset=["date_col"])
    # Filter to plausible years only (avoid 1970 epoch fallback)
    tl_df = tl_df[tl_df["date_col"].dt.year.between(2020, 2027)]

    if not tl_df.empty:
        tl_agg = (tl_df.groupby(tl_df["date_col"].dt.to_period("M").astype(str))
                       .size().reset_index(name="Tenders")
                       .rename(columns={"date_col":"Month"})
                       .sort_values("Month"))

        fig_tl = px.area(
            tl_agg, x="Month", y="Tenders",
            color_discrete_sequence=["#0E8C8C"],
            height=280,
            labels={"Tenders":"Tender Count","Month":"Month"},
        )
        fig_tl.update_traces(
            fill="tozeroy",
            line=dict(color="#0E8C8C", width=2),
            fillcolor="rgba(196,118,41,0.25)",
        )
        fig_tl.update_layout(
            margin=dict(t=10,b=10,l=10,r=10),
            xaxis=dict(tickangle=-45, tickfont=dict(size=9)),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_tl, use_container_width=True)
    else:
        st.info("No date data in range 2020–2027 for this filter. Most scraped records lack start_date.")

    # ── Leader Boards ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">🏅 Leader Boards</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Top departments by tender count (left) and top awarded contractors by budget (right). '
        'A single department dominating a region may signal siloed planning.'
        '</div>', unsafe_allow_html=True)

    lb1, lb2 = st.columns(2)

    with lb1:
        st.markdown("**🏢 Top 10 Departments by Tender Count**")
        dept_lb = (df.groupby("department").size()
                     .nlargest(10).reset_index(name="Tenders")
                     .rename(columns={"department":"Dept"})
                     .sort_values("Tenders"))
        dept_lb["Dept"] = dept_lb["Dept"].str[:35]
        fig_dept = px.bar(dept_lb, x="Tenders", y="Dept", orientation="h",
                          text="Tenders", height=380,
                          color="Tenders",
                          color_continuous_scale=["#D4EAF7","#0E8C8C","#0D1B2A"])
        fig_dept.update_traces(texttemplate="%{text:,}", textposition="outside")
        fig_dept.update_layout(coloraxis_showscale=False,
                                margin=dict(t=5,b=5,l=5,r=40),
                                yaxis=dict(tickfont=dict(size=9)))
        st.plotly_chart(fig_dept, use_container_width=True)

    with lb2:
        st.markdown("**👷 Top Contractors by Awarded Budget (₹ Cr)**")
        contr_df = budget_df[
            budget_df["contractor_name"].notna() &
            (budget_df["contractor_name"] != "—") &
            (budget_df["contractor_name"] != "")]
        if not contr_df.empty:
            contr_lb = (contr_df.groupby("contractor_name")["amount_cr"].sum()
                                .nlargest(10).reset_index()
                                .rename(columns={"amount_cr":"₹ Cr","contractor_name":"Contractor"})
                                .sort_values("₹ Cr"))
            contr_lb["Contractor"] = contr_lb["Contractor"].str[:35]
            fig_con = px.bar(contr_lb, x="₹ Cr", y="Contractor", orientation="h",
                             text_auto=".1f", height=380,
                             color="₹ Cr",
                             color_continuous_scale=["#E8F5E9","#27AE60","#145A32"])
            fig_con.update_layout(coloraxis_showscale=False,
                                   margin=dict(t=5,b=5,l=5,r=40),
                                   yaxis=dict(tickfont=dict(size=9)))
            st.plotly_chart(fig_con, use_container_width=True)
        else:
            st.info("No contractor data with valid budget in current filter.")

    # ── Status + Budget histogram ──────────────────────────────────────────────
    st.markdown("---")
    rc1, rc2 = st.columns(2)
    with rc1:
        st.markdown("**📊 Tender Status Split**")
        st.caption("Share of Active / Awarded / Completed tenders.")
        stat_df = df["status"].value_counts().reset_index()
        stat_df.columns = ["Status","Count"]
        fig_status = px.pie(stat_df, names="Status", values="Count",
                            color="Status", color_discrete_map=STATUS_COLORS,
                            hole=0.52, height=300)
        fig_status.update_traces(textposition="outside", textinfo="percent+label")
        fig_status.update_layout(showlegend=False, margin=dict(t=5,b=5,l=5,r=5))
        st.plotly_chart(fig_status, use_container_width=True)

    with rc2:
        st.markdown("**📈 Budget Distribution (₹ Cr)**")
        st.caption(f"Only the {len(budget_df):,} tenders with reported budget. "
                   "Typical log-normal: many small, a few very large.")
        if not budget_df.empty:
            fig_hist = px.histogram(budget_df, x="amount_cr", nbins=40,
                                    color_discrete_sequence=["#0E8C8C"],
                                    labels={"amount_cr":"₹ Crores"},
                                    height=300)
            fig_hist.update_layout(margin=dict(t=5,b=5,l=5,r=5),
                                    yaxis_title="Tenders", bargap=0.05)
            st.plotly_chart(fig_hist, use_container_width=True)
        else:
            st.info("No budget data in current filter.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 4 · DATA & SOURCES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab4:

    # ── Source Portal Analysis (FIX-03: top 15 + Others) ──────────────────────
    st.markdown('<div class="section-label">🔌 Portal Coverage Analysis</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Which portals feed this dashboard? Top 15 by volume shown individually; '
        'remaining portals grouped as "All Others". '
        'A diverse spread means broad geographic coverage; a dominant single portal '
        'signals a data concentration risk.'
        '</div>', unsafe_allow_html=True)

    # Group by top 15 + Others
    src_vol = df.groupby("source").size().sort_values(ascending=False)
    top15   = src_vol.head(15)
    others_cnt = int(src_vol.iloc[15:].sum()) if len(src_vol) > 15 else 0

    src_display = top15.copy()
    if others_cnt > 0:
        src_display["All Others"] = others_cnt
    src_display = src_display.reset_index()
    src_display.columns = ["Portal","Tenders"]
    src_display["Portal_Short"] = src_display["Portal"].apply(
        lambda s: ("All Others" if s == "All Others" else
                   s.split("/")[-1][:18] if "/" in s else s[:18]))

    ring_col, bar_col = st.columns([1, 2])

    with ring_col:
        fig_ring = px.pie(
            src_display, names="Portal_Short", values="Tenders",
            hole=0.52, height=360,
            color_discrete_sequence=px.colors.qualitative.Set3,
        )
        fig_ring.update_traces(
            textposition="outside", textinfo="percent",
            hovertemplate="<b>%{label}</b><br>%{value:,} tenders (%{percent})<extra></extra>",
        )
        fig_ring.update_layout(showlegend=False, margin=dict(t=10,b=10,l=10,r=10))
        st.plotly_chart(fig_ring, use_container_width=True)

    with bar_col:
        fig_srcbar = px.bar(
            src_display.sort_values("Tenders"),
            x="Tenders", y="Portal_Short", orientation="h",
            color="Tenders", color_continuous_scale=["#D4EAF7","#0E8C8C","#0D1B2A"],
            text="Tenders", height=360,
            labels={"Tenders":"Tender Count","Portal_Short":"Portal"},
        )
        fig_srcbar.update_traces(texttemplate="%{text:,}", textposition="outside")
        fig_srcbar.update_layout(
            coloraxis_showscale=False,
            margin=dict(t=10,b=10,l=5,r=50),
            yaxis=dict(tickfont=dict(size=9)),
        )
        st.plotly_chart(fig_srcbar, use_container_width=True)

    # ── Full Tender Table ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">📄 Full Tender Registry</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Every tender in the current filter. Budget shown in ₹ Crores '
        '(÷ 1,00,00,000 from raw rupees). "—" means amount was not published on the portal. '
        'Download as CSV for offline analysis or stakeholder reporting.'
        '</div>', unsafe_allow_html=True)

    TABLE_COLS = {
        "tender_id":       "Tender ID",
        "title":           "Project Title",
        "sector_display":  "Sector",
        "department":      "Department",
        "amount_cr":       "₹ Crores",
        "state":           "State",
        "district":        "District",
        "block":           "Block",
        "status":          "Status",
        "source":          "Portal",
        "contractor_name": "Contractor",
        "start_date":      "Start Date",
        "end_date":        "End Date",
    }
    df_table = df.copy()
    for _c in ("contractor_name","start_date","end_date"):
        if _c not in df_table.columns: df_table[_c] = "—"
        df_table[_c] = df_table[_c].fillna("—").replace("","—")

    PAGE_SIZE   = 200
    total_pages = max(1, (len(df_table)-1)//PAGE_SIZE + 1)
    pcol1, pcol2, pcol3 = st.columns([2,1,2])
    with pcol2:
        page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1)

    start   = (page - 1) * PAGE_SIZE
    end     = start + PAGE_SIZE
    df_page = (df_table.iloc[start:end][list(TABLE_COLS.keys())]
                       .rename(columns=TABLE_COLS).copy())
    # Format budget column
    df_page["₹ Crores"] = df_page["₹ Crores"].apply(
        lambda x: f"₹{float(x):,.2f}" if pd.notna(x) and float(x) > (MIN_VALID_AMOUNT/RUPEES_PER_CRORE) else "—")

    st.caption(f"Showing {start+1}–{min(end,len(df_table))} of {len(df_table):,}  |  Page {page} / {total_pages}")
    st.dataframe(df_page, use_container_width=True, height=420, hide_index=True)

    # Download exports raw amounts in Crores
    csv_df = df_table[list(TABLE_COLS.keys())].rename(columns=TABLE_COLS).copy()
    csv_df["₹ Crores"] = csv_df["₹ Crores"].apply(
        lambda x: round(float(x), 4) if pd.notna(x) else "")
    csv_data = csv_df.to_csv(index=False)

    dl1, dl2 = st.columns([1,4])
    with dl1:
        st.download_button("⬇️ Download CSV", data=csv_data,
                           file_name=f"divyadrishti_{drill_level}.csv",
                           mime="text/csv", use_container_width=True)
    with dl2:
        st.caption(f"Full filtered dataset: {len(df_table):,} rows · {len(TABLE_COLS)} columns · "
                   f"Budget reported for {df_table['has_budget'].sum():,} rows")

    # ── Portal Health Log ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">📡 Portal Health Log</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">'
        'Each scraping run is logged: portal, success/failure, records retrieved, and timestamp. '
        'Use this to track which portals need attention — CAPTCHA changes, DNS failures, or layout updates.'
        '</div>', unsafe_allow_html=True)
    try:
        _health = load_health_log()
        if _health is not None and not _health.empty:
            _health_disp = _health[["source","status","records_fetched","error_msg","logged_at"]].copy()
            _health_disp["status"] = _health_disp["status"].apply(
                lambda s: "✅ ok" if s == "ok" else f"❌ {s}")
            st.dataframe(
                _health_disp.sort_values("logged_at", ascending=False).head(50),
                use_container_width=True, height=340, hide_index=True,
            )
        else:
            st.info("No health log entries yet. Run a scraper from the sidebar.")
    except Exception:
        st.info("Health log unavailable.")
