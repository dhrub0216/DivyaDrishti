"""
Pan-India Multi-Department Public Expenditure & Tender Analytics Engine  v3.0
Hierarchical Drill-Down: Sector → Department → State → District → Block
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
    page_title="India Tender Analytics",
    page_icon="🇮🇳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Sentinel values ───────────────────────────────────────────────────────────
ALL = "All"

# Threshold above which we switch to aggregated map (performance guard)
SCATTER_LIMIT = 5_000

STATUS_COLORS = {"Active": "#27AE60", "Awarded": "#F39C12", "Completed": "#3498DB"}

# ─── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .hero { font-size:1.85rem; font-weight:700; color:#0D1B2A; }
    .sub  { font-size:.9rem; color:#666; margin-top:-6px; }
    .badge {
        display:inline-block; padding:3px 12px; border-radius:14px;
        font-size:.75rem; font-weight:600;
        background:#EAF2FF; color:#1A4E8A; margin-bottom:6px;
    }
    .agg-warn {
        padding:6px 12px; background:#FFF8E1; border-left:4px solid #F39C12;
        border-radius:4px; font-size:.82rem; color:#7D5A00; margin-bottom:8px;
    }
    div[data-testid="metric-container"] {
        border-left:4px solid #3498DB; border-radius:6px; padding:6px;
    }
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
    st.markdown("## 🇮🇳 India Tender Analytics")
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
        "Sources", ["cppp", "gem", "states", "datagov"],
        default=["cppp", "gem"],
        help="cppp=Central portal, gem=GeM bids, states=all state NIC portals, datagov=data.gov.in API",
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

    # ── System Health (failed_domains visibility) ─────────────────────────
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
st.markdown('<p class="hero">🗺️ Pan-India Public Expenditure & Tender Analytics Engine</p>', unsafe_allow_html=True)
st.markdown('<p class="sub">Multi-department transparency dashboard — 12 sectors · 25 states/UTs · All administrative tiers</p>', unsafe_allow_html=True)
st.markdown(f'<span class="badge">{level_label}</span>', unsafe_allow_html=True)
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
c2.metric("📋 Active Tenders", f"{active_count:,}")
c3.metric("📊 Avg per Tender", f"₹{avg_cost:,.2f} Cr")
c4.metric("🏆 Largest Tender", f"₹{float(top_row['allocated_amount']):,.1f} Cr",
          delta=str(top_row["sector"]), delta_color="off")
c5.metric("🏭 Sectors Active", f"{sector_count}")
c6.metric("🏢 Departments", f"{dept_count}")
st.markdown("---")

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
        df_plot["bubble"] = (
            ((df_plot["allocated_amount"] - a_min) / max(a_max - a_min, 1)) * 40 + 10
        )
        df_plot["amt_fmt"] = df_plot["allocated_amount"].apply(lambda x: f"₹{x:,.2f} Cr")

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
        fig.update_traces(marker=dict(opacity=0.82, sizemode="area"))

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
                    line=dict(width=2, color="rgba(52, 152, 219, 0.6)"),
                    fill="toself",
                    fillcolor="rgba(52, 152, 219, 0.06)",
                    hoverinfo="skip",
                    showlegend=False,
                    name=f"{selected_district} boundary",
                ))
                # Marker at district centre
                fig.add_trace(go.Scattermapbox(
                    lat=[c["lat"]], lon=[c["lon"]],
                    mode="markers+text",
                    marker=dict(size=14, color="#1A5276", symbol="circle"),
                    text=[f"📍 {selected_district}"],
                    textposition="top right",
                    textfont=dict(size=11, color="#1A5276"),
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
        color="₹ Cr", color_continuous_scale="Blues",
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
        color_discrete_sequence=["#3498DB"],
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
st.subheader(f"📄 Tender Records — {len(df):,} results")

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
        file_name=f"india_tenders_{drill_level}.csv",
        mime="text/csv",
        use_container_width=True,
    )
with dl2:
    st.caption(f"Full filtered dataset: {len(df):,} rows · {len(TABLE_COLS)} columns")
