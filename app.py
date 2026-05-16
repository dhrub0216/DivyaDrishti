"""
National Geo-Spatial Public Expenditure & Tender Tracker  v2.0
Pan-India | Hierarchical Drill-Down: National → State → District → Block
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from pipeline import (
    load_production_pipeline_data,
    get_hierarchy,
    get_view_config,
    STATE_CENTERS,
    INDIA_CENTER,
    INDIA_ZOOM,
)

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="India Tender Tracker",
    page_icon="🇮🇳",
    layout="wide",
)

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
CATEGORY_COLORS = {
    "Road":     "#E74C3C",
    "Bridge":   "#3498DB",
    "Water":    "#27AE60",
    "Building": "#F39C12",
    "Other":    "#9B59B6",
}

STATUS_COLORS = {
    "Active":    "#27AE60",
    "Awarded":   "#F39C12",
    "Completed": "#3498DB",
}

ALL_STATES    = "All States"
ALL_DISTRICTS = "All Districts"
ALL_BLOCKS    = "All Blocks"

# ─────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
    .hero-title  { font-size:1.9rem; font-weight:700; color:#0D1B2A; margin-bottom:2px; }
    .hero-sub    { font-size:.95rem; color:#666; margin-top:0; }
    .level-badge {
        display:inline-block; padding:3px 10px; border-radius:12px;
        font-size:.75rem; font-weight:600; margin-bottom:8px;
        background:#EBF5FB; color:#1A5276;
    }
    div[data-testid="metric-container"] { border-left:4px solid #3498DB; border-radius:6px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# DATA LOAD
# ─────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def load_data() -> pd.DataFrame:
    return load_production_pipeline_data()

with st.spinner("Loading national tender database…"):
    try:
        df_master = load_data()
    except FileNotFoundError as e:
        st.error(f"**Data not found.** {e}")
        st.stop()

hierarchy = get_hierarchy(df_master)

# ─────────────────────────────────────────────
# SIDEBAR — Cascading Filters
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🇮🇳 India Tender Tracker")
    st.markdown("---")

    # ── Level 1: State ──
    st.markdown("#### 📍 Drill-Down Filters")
    state_options = [ALL_STATES] + sorted(hierarchy.keys())
    selected_state = st.selectbox("State / UT", state_options, index=0)

    # ── Level 2: District (cascades from state) ──
    if selected_state != ALL_STATES:
        district_options = [ALL_DISTRICTS] + sorted(hierarchy[selected_state].keys())
    else:
        district_options = [ALL_DISTRICTS]
    selected_district = st.selectbox("District", district_options, index=0)

    # ── Level 3: Block (cascades from district) ──
    if selected_state != ALL_STATES and selected_district != ALL_DISTRICTS:
        block_options = [ALL_BLOCKS] + sorted(hierarchy[selected_state][selected_district])
    else:
        block_options = [ALL_BLOCKS]
    selected_block = st.selectbox("Block / Taluka", block_options, index=0)

    st.markdown("---")

    # ── Category filter ──
    all_cats = sorted(df_master["category"].unique().tolist())
    selected_cats = st.multiselect("Category", all_cats, default=all_cats)

    # ── Status filter ──
    all_statuses = sorted(df_master["status"].unique().tolist())
    selected_statuses = st.multiselect("Status", all_statuses, default=all_statuses)

    # ── Budget slider ──
    amt_min = float(df_master["allocated_amount"].min())
    amt_max = float(df_master["allocated_amount"].max())
    budget_range = st.slider(
        "Budget Range (₹ Crores)",
        min_value=amt_min, max_value=amt_max,
        value=(amt_min, amt_max), step=1.0,
        format="₹%.0f Cr",
    )

    st.markdown("---")
    if st.button("🔄 Refresh Data Cache", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.caption(f"Total records in DB: **{len(df_master):,}**")
    st.caption("Source: CPPP + State Portals + Seed Dataset")

# ─────────────────────────────────────────────
# DETERMINE DRILL-DOWN LEVEL
# ─────────────────────────────────────────────
if selected_state == ALL_STATES:
    drill_level = "national"
    level_label = "🌏 National View — All States"
elif selected_district == ALL_DISTRICTS:
    drill_level = "state"
    level_label = f"📍 State View — {selected_state}"
elif selected_block == ALL_BLOCKS:
    drill_level = "district"
    level_label = f"🏙️ District View — {selected_district}, {selected_state}"
else:
    drill_level = "block"
    level_label = f"🔍 Block View — {selected_block}, {selected_district}"

# ─────────────────────────────────────────────
# FILTER DATA
# ─────────────────────────────────────────────
df = df_master.copy()

if selected_state != ALL_STATES:
    df = df[df["state"] == selected_state]
if selected_district != ALL_DISTRICTS:
    df = df[df["district"] == selected_district]
if selected_block != ALL_BLOCKS:
    df = df[df["block"] == selected_block]

df = df[
    df["category"].isin(selected_cats) &
    df["status"].isin(selected_statuses) &
    df["allocated_amount"].between(budget_range[0], budget_range[1])
]

# ─────────────────────────────────────────────
# PAGE HEADER
# ─────────────────────────────────────────────
st.markdown('<p class="hero-title">🗺️ National Public Expenditure & Tender Tracker</p>', unsafe_allow_html=True)
st.markdown('<p class="hero-sub">Real-time transparency dashboard for government infrastructure spending across India</p>', unsafe_allow_html=True)
st.markdown(f'<span class="level-badge">{level_label}</span>', unsafe_allow_html=True)
st.markdown("---")

# ─────────────────────────────────────────────
# EMPTY STATE GUARD
# ─────────────────────────────────────────────
if df.empty:
    st.warning("⚠️ No tenders match the current filters. Please adjust your selections.")
    st.stop()

# ─────────────────────────────────────────────
# KPI CARDS  (dynamically recalculate at every level)
# ─────────────────────────────────────────────
total_funds  = df["allocated_amount"].sum()
active_count = df[df["status"] == "Active"].shape[0]
avg_cost     = df["allocated_amount"].mean()
top_row      = df.loc[df["allocated_amount"].idxmax()]
state_count  = df["state"].nunique()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("💰 Total Funds", f"₹{total_funds:,.2f} Cr")
c2.metric("📋 Active Projects", f"{active_count:,}")
c3.metric("📊 Avg per Project", f"₹{avg_cost:,.2f} Cr")
c4.metric("🏆 Largest Tender", f"₹{top_row['allocated_amount']:,.2f} Cr",
          delta=top_row["title"][:30] + "…", delta_color="off")
c5.metric("🗺️ States Covered", f"{state_count}")
st.markdown("---")

# ─────────────────────────────────────────────
# MAP VISUALIZATION — Adaptive by drill level
# ─────────────────────────────────────────────
view = get_view_config(df, selected_state, selected_district)

map_col, info_col = st.columns([4, 1])

with map_col:

    # ── NATIONAL VIEW: aggregate by state, bubble per state ──────────────
    if drill_level == "national":
        state_agg = (
            df.groupby("state")
            .agg(
                total_amount=("allocated_amount", "sum"),
                count=("tender_id", "count"),
                lat=("latitude", "mean"),
                lon=("longitude", "mean"),
            )
            .reset_index()
        )
        # Use state centres when available (more accurate than data mean)
        state_agg["lat"] = state_agg["state"].map(
            lambda s: STATE_CENTERS.get(s, {}).get("lat", state_agg.loc[state_agg["state"] == s, "lat"].values[0])
        )
        state_agg["lon"] = state_agg["state"].map(
            lambda s: STATE_CENTERS.get(s, {}).get("lon", state_agg.loc[state_agg["state"] == s, "lon"].values[0])
        )
        state_agg["label"] = state_agg.apply(
            lambda r: f"{r['state']}<br>₹{r['total_amount']:,.1f} Cr | {r['count']} tenders", axis=1
        )

        fig = px.scatter_mapbox(
            state_agg,
            lat="lat", lon="lon",
            size="total_amount",
            color="total_amount",
            color_continuous_scale="YlOrRd",
            hover_name="state",
            hover_data={"total_amount": ":.2f", "count": True, "lat": False, "lon": False},
            labels={"total_amount": "₹ Crores", "count": "Tenders"},
            mapbox_style="open-street-map",
            center={"lat": INDIA_CENTER["lat"], "lon": INDIA_CENTER["lon"]},
            zoom=INDIA_ZOOM,
            height=560,
            size_max=60,
        )
        fig.update_coloraxes(colorbar_title="₹ Crores")

    # ── STATE VIEW: aggregate by district ────────────────────────────────
    elif drill_level == "state":
        dist_agg = (
            df.groupby("district")
            .agg(
                total_amount=("allocated_amount", "sum"),
                count=("tender_id", "count"),
                lat=("latitude", "mean"),
                lon=("longitude", "mean"),
            )
            .reset_index()
        )
        dist_agg["size_col"] = dist_agg["total_amount"].clip(lower=1)

        fig = px.scatter_mapbox(
            dist_agg,
            lat="lat", lon="lon",
            size="size_col",
            color="total_amount",
            color_continuous_scale="Blues",
            hover_name="district",
            hover_data={"total_amount": ":.2f", "count": True, "lat": False, "lon": False, "size_col": False},
            labels={"total_amount": "₹ Crores", "count": "Tenders"},
            mapbox_style="open-street-map",
            center={"lat": view["lat"], "lon": view["lon"]},
            zoom=view["zoom"],
            height=560,
            size_max=55,
        )

    # ── DISTRICT / BLOCK VIEW: individual scatter points ─────────────────
    else:
        # Scale bubble size min-max proportional to amount
        a_min, a_max = df["allocated_amount"].min(), df["allocated_amount"].max()
        df = df.copy()
        df["bubble"] = (
            ((df["allocated_amount"] - a_min) / (a_max - a_min + 1e-9)) * 40 + 10
        )
        df["amt_fmt"] = df["allocated_amount"].apply(lambda x: f"₹{x:,.2f} Crores")

        fig = px.scatter_mapbox(
            df,
            lat="latitude", lon="longitude",
            size="bubble",
            color="category",
            color_discrete_map=CATEGORY_COLORS,
            hover_name="title",
            hover_data={
                "department": True,
                "amt_fmt": True,
                "status": True,
                "state": True,
                "district": True,
                "block": True,
                "bubble": False,
                "latitude": False,
                "longitude": False,
            },
            labels={"amt_fmt": "Allocated", "department": "Dept", "status": "Status"},
            mapbox_style="open-street-map",
            center={"lat": view["lat"], "lon": view["lon"]},
            zoom=view["zoom"],
            height=560,
        )
        fig.update_traces(
            marker=dict(opacity=0.85, sizemode="area"),
        )

    fig.update_layout(
        margin=dict(l=0, r=0, t=5, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)

with info_col:
    st.markdown("#### 🔍 Current View")
    st.markdown(f"**Level:** {drill_level.capitalize()}")
    st.markdown(f"**Tenders shown:** `{len(df):,}`")
    st.markdown("---")

    if drill_level in ("district", "block"):
        st.markdown("**By Category**")
        for cat, color in CATEGORY_COLORS.items():
            count = (df["category"] == cat).sum()
            if count:
                st.markdown(
                    f'<span style="background:{color};border-radius:50%;display:inline-block;'
                    f'width:10px;height:10px;margin-right:5px;"></span> {cat} ({count})',
                    unsafe_allow_html=True,
                )
    else:
        # Show top states or districts in current view
        group_col = "state" if drill_level == "national" else "district"
        top5 = (
            df.groupby(group_col)["allocated_amount"]
            .sum().sort_values(ascending=False).head(5)
        )
        st.markdown(f"**Top {group_col.capitalize()}s**")
        for name, amt in top5.items():
            st.caption(f"{name[:20]}: ₹{amt:,.1f} Cr")

    st.markdown("---")
    st.markdown("**Status**")
    for status, color in STATUS_COLORS.items():
        cnt = (df["status"] == status).sum()
        st.markdown(
            f'<span style="color:{color};font-weight:600;">●</span> {status}: {cnt}',
            unsafe_allow_html=True,
        )

# ─────────────────────────────────────────────
# ANALYTICS CHARTS
# ─────────────────────────────────────────────
st.markdown("---")
ch1, ch2, ch3 = st.columns(3)

with ch1:
    st.subheader("💹 Funds by Category")
    cat_df = (
        df.groupby("category")["allocated_amount"]
        .sum().reset_index()
        .rename(columns={"allocated_amount": "₹ Crores"})
        .sort_values("₹ Crores", ascending=False)
    )
    fig_bar = px.bar(
        cat_df, x="category", y="₹ Crores",
        color="category", color_discrete_map=CATEGORY_COLORS,
        text_auto=".1f",
    )
    fig_bar.update_layout(showlegend=False, margin=dict(t=10, b=10))
    st.plotly_chart(fig_bar, use_container_width=True)

with ch2:
    st.subheader("📊 Status Split")
    stat_df = df["status"].value_counts().reset_index()
    stat_df.columns = ["Status", "Count"]
    fig_pie = px.pie(
        stat_df, names="Status", values="Count",
        color="Status", color_discrete_map=STATUS_COLORS,
        hole=0.45,
    )
    fig_pie.update_traces(textposition="outside", textinfo="percent+label")
    fig_pie.update_layout(margin=dict(t=10, b=10), showlegend=False)
    st.plotly_chart(fig_pie, use_container_width=True)

with ch3:
    # Varies by drill level — top aggregation
    if drill_level == "national":
        group_label = "State"
        top_df = (
            df.groupby("state")["allocated_amount"]
            .sum().nlargest(8).reset_index()
            .rename(columns={"state": "State", "allocated_amount": "₹ Crores"})
        )
        st.subheader("🏅 Top States by Spend")
        fig_top = px.bar(
            top_df, x="₹ Crores", y="State",
            orientation="h", text_auto=".0f",
            color="₹ Crores", color_continuous_scale="YlOrRd",
        )
    elif drill_level == "state":
        top_df = (
            df.groupby("district")["allocated_amount"]
            .sum().nlargest(8).reset_index()
            .rename(columns={"district": "District", "allocated_amount": "₹ Crores"})
        )
        st.subheader(f"🏅 Top Districts — {selected_state}")
        fig_top = px.bar(
            top_df, x="₹ Crores", y="District",
            orientation="h", text_auto=".0f",
            color="₹ Crores", color_continuous_scale="Blues",
        )
    else:
        top_df = (
            df.nlargest(8, "allocated_amount")[["title", "allocated_amount"]]
            .rename(columns={"title": "Project", "allocated_amount": "₹ Crores"})
        )
        top_df["Project"] = top_df["Project"].str[:30]
        st.subheader("🏅 Top Tenders")
        fig_top = px.bar(
            top_df, x="₹ Crores", y="Project",
            orientation="h", text_auto=".1f",
            color="₹ Crores", color_continuous_scale="Greens",
        )

    fig_top.update_layout(
        showlegend=False, coloraxis_showscale=False,
        margin=dict(t=10, b=10), yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig_top, use_container_width=True)

# ─────────────────────────────────────────────
# SEARCHABLE DATA TABLE
# ─────────────────────────────────────────────
st.markdown("---")
st.subheader("📄 Tender Details")

show_cols = {
    "tender_id":        "Tender ID",
    "title":            "Project Title",
    "category":         "Category",
    "allocated_amount": "Amount (₹ Cr)",
    "state":            "State",
    "district":         "District",
    "block":            "Block",
    "status":           "Status",
    "department":       "Department",
}

df_table = df[list(show_cols.keys())].rename(columns=show_cols).copy()
df_table["Amount (₹ Cr)"] = df_table["Amount (₹ Cr)"].apply(lambda x: f"₹{x:,.2f}")

st.dataframe(df_table, use_container_width=True, height=340, hide_index=True)

csv = df[list(show_cols.keys())].rename(columns=show_cols).to_csv(index=False)
st.download_button(
    "⬇️ Download Filtered Data (CSV)",
    data=csv,
    file_name=f"india_tenders_{drill_level}.csv",
    mime="text/csv",
)
