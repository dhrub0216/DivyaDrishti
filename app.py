"""
Geo-Spatial Public Expenditure & Tender Tracker
Focus: Samastipur District, Bihar, India
"""

import json
import subprocess
import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Samastipur Tender Tracker",
    page_icon="🗺️",
    layout="wide",
)

# ─────────────────────────────────────────────
# MOCK DATA
# ─────────────────────────────────────────────
def load_mock_tender_data() -> pd.DataFrame:
    """Returns a realistic mock dataset of 20 government tenders for Samastipur district."""
    records = [
        # Roads
        {
            "tender_id": "NIT-01/RWD/SAMAS/2026",
            "title": "Construction of Road from Kalyanpur to Warisnagar",
            "category": "Road",
            "allocated_amount": 3.45,
            "location_raw": "Kalyanpur, Samastipur",
            "latitude": 25.8900,
            "longitude": 85.7600,
            "department": "Rural Works Department (RWD)",
            "status": "Active",
        },
        {
            "tender_id": "NIT-02/RWD/SAMAS/2026",
            "title": "Widening of SH-56 through Rosera Town",
            "category": "Road",
            "allocated_amount": 5.20,
            "location_raw": "Rosera, Samastipur",
            "latitude": 25.9700,
            "longitude": 85.9900,
            "department": "State Highway Division",
            "status": "Awarded",
        },
        {
            "tender_id": "NIT-03/RWD/SAMAS/2026",
            "title": "Rural Road Connectivity – Patori to Ujiyarpur",
            "category": "Road",
            "allocated_amount": 2.10,
            "location_raw": "Patori, Samastipur",
            "latitude": 25.9200,
            "longitude": 85.8700,
            "department": "Rural Works Department (RWD)",
            "status": "Active",
        },
        {
            "tender_id": "NIT-04/NH/SAMAS/2026",
            "title": "NH-28 Service Road Construction near Dalsinghsarai",
            "category": "Road",
            "allocated_amount": 8.75,
            "location_raw": "Dalsinghsarai, Samastipur",
            "latitude": 25.6700,
            "longitude": 85.8300,
            "department": "National Highway Authority",
            "status": "Active",
        },
        {
            "tender_id": "NIT-05/RWD/SAMAS/2026",
            "title": "Bituminous Resurfacing of Road: Tajpur-Hasanpur Stretch",
            "category": "Road",
            "allocated_amount": 1.85,
            "location_raw": "Tajpur, Samastipur",
            "latitude": 25.8200,
            "longitude": 85.7000,
            "department": "Rural Works Department (RWD)",
            "status": "Completed",
        },
        {
            "tender_id": "NIT-06/RWD/SAMAS/2025",
            "title": "Village Road: Mohanpur to Bibhutipur",
            "category": "Road",
            "allocated_amount": 0.95,
            "location_raw": "Bibhutipur, Samastipur",
            "latitude": 25.8000,
            "longitude": 85.6500,
            "department": "Rural Works Department (RWD)",
            "status": "Completed",
        },
        # Bridges
        {
            "tender_id": "NIT-07/BR/SAMAS/2026",
            "title": "Construction of Minor Bridge over Budhi Gandak at Warisnagar",
            "category": "Bridge",
            "allocated_amount": 6.80,
            "location_raw": "Warisnagar, Samastipur",
            "latitude": 25.8500,
            "longitude": 85.9100,
            "department": "Bihar Bridge Construction Corporation",
            "status": "Active",
        },
        {
            "tender_id": "NIT-08/BR/SAMAS/2026",
            "title": "High-Level Bridge over Bagmati River near Rosera",
            "category": "Bridge",
            "allocated_amount": 14.30,
            "location_raw": "Rosera, Samastipur",
            "latitude": 25.9800,
            "longitude": 85.9700,
            "department": "Bihar Bridge Construction Corporation",
            "status": "Awarded",
        },
        {
            "tender_id": "NIT-09/BR/SAMAS/2026",
            "title": "Repair & Rehabilitation of Existing Bridge, Singhia Block",
            "category": "Bridge",
            "allocated_amount": 2.60,
            "location_raw": "Singhia, Samastipur",
            "latitude": 25.9000,
            "longitude": 85.6800,
            "department": "State Road Construction Department",
            "status": "Active",
        },
        {
            "tender_id": "NIT-10/BR/SAMAS/2025",
            "title": "Small Bridge over Drain – Morwa Block",
            "category": "Bridge",
            "allocated_amount": 1.20,
            "location_raw": "Morwa, Samastipur",
            "latitude": 25.7500,
            "longitude": 85.8900,
            "department": "Rural Works Department (RWD)",
            "status": "Completed",
        },
        # Water / Drainage
        {
            "tender_id": "NIT-11/WR/SAMAS/2026",
            "title": "Drinking Water Supply Scheme – Kalyanpur Block",
            "category": "Water",
            "allocated_amount": 3.90,
            "location_raw": "Kalyanpur, Samastipur",
            "latitude": 25.8800,
            "longitude": 85.7400,
            "department": "Public Health Engineering Dept (PHED)",
            "status": "Active",
        },
        {
            "tender_id": "NIT-12/WR/SAMAS/2026",
            "title": "Urban Water Distribution Network, Samastipur Town",
            "category": "Water",
            "allocated_amount": 9.50,
            "location_raw": "Samastipur, Bihar",
            "latitude": 25.8624,
            "longitude": 85.7810,
            "department": "Public Health Engineering Dept (PHED)",
            "status": "Active",
        },
        {
            "tender_id": "NIT-13/WR/SAMAS/2025",
            "title": "Flood Drainage Canal – Patori to Shivajinagar",
            "category": "Water",
            "allocated_amount": 4.15,
            "location_raw": "Patori, Samastipur",
            "latitude": 25.9300,
            "longitude": 85.8600,
            "department": "Water Resources Department",
            "status": "Awarded",
        },
        {
            "tender_id": "NIT-14/WR/SAMAS/2025",
            "title": "Hand Pump Installation Drive – Bibhutipur Block",
            "category": "Water",
            "allocated_amount": 0.75,
            "location_raw": "Bibhutipur, Samastipur",
            "latitude": 25.8100,
            "longitude": 85.6600,
            "department": "Public Health Engineering Dept (PHED)",
            "status": "Completed",
        },
        # Buildings
        {
            "tender_id": "NIT-15/BD/SAMAS/2026",
            "title": "Construction of Community Health Centre – Dalsinghsarai",
            "category": "Building",
            "allocated_amount": 7.20,
            "location_raw": "Dalsinghsarai, Samastipur",
            "latitude": 25.6600,
            "longitude": 85.8400,
            "department": "Health & Family Welfare Dept",
            "status": "Active",
        },
        {
            "tender_id": "NIT-16/BD/SAMAS/2026",
            "title": "New Primary School Building – Singhia Block",
            "category": "Building",
            "allocated_amount": 1.60,
            "location_raw": "Singhia, Samastipur",
            "latitude": 25.9100,
            "longitude": 85.6900,
            "department": "Education Department, Bihar",
            "status": "Active",
        },
        {
            "tender_id": "NIT-17/BD/SAMAS/2025",
            "title": "Block Development Office Renovation – Tajpur",
            "category": "Building",
            "allocated_amount": 0.85,
            "location_raw": "Tajpur, Samastipur",
            "latitude": 25.8300,
            "longitude": 85.7100,
            "department": "General Administration Dept",
            "status": "Completed",
        },
        {
            "tender_id": "NIT-18/BD/SAMAS/2026",
            "title": "Anganwadi Centre Construction – Morwa & Ujiyarpur Blocks",
            "category": "Building",
            "allocated_amount": 2.30,
            "location_raw": "Ujiyarpur, Samastipur",
            "latitude": 25.8750,
            "longitude": 85.9300,
            "department": "Integrated Child Development Services",
            "status": "Awarded",
        },
        {
            "tender_id": "NIT-19/BD/SAMAS/2026",
            "title": "Police Station Complex – Warisnagar",
            "category": "Building",
            "allocated_amount": 4.40,
            "location_raw": "Warisnagar, Samastipur",
            "latitude": 25.8550,
            "longitude": 85.9050,
            "department": "Home Department, Bihar",
            "status": "Active",
        },
        {
            "tender_id": "NIT-20/RWD/SAMAS/2026",
            "title": "Solar Street Lighting – Samastipur Urban & Rural Areas",
            "category": "Building",
            "allocated_amount": 3.10,
            "location_raw": "Samastipur, Bihar",
            "latitude": 25.8624,
            "longitude": 85.7810,
            "department": "Energy Department, Bihar",
            "status": "Active",
        },
    ]
    return pd.DataFrame(records)


# ─────────────────────────────────────────────
# STYLING CONSTANTS
# ─────────────────────────────────────────────
CATEGORY_COLORS = {
    "Road":     "#E74C3C",   # Red
    "Bridge":   "#3498DB",   # Blue
    "Water":    "#27AE60",   # Green
    "Building": "#F39C12",   # Amber
}

STATUS_SYMBOLS = {
    "Active":    "🟢",
    "Awarded":   "🟡",
    "Completed": "✅",
}


# ─────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────
st.markdown(
    """
    <style>
        .main-title  { font-size:2rem; font-weight:700; color:#1A1A2E; }
        .sub-title   { font-size:1rem; color:#555; margin-top:-10px; }
        .kpi-label   { font-size:0.75rem; color:#888; text-transform:uppercase; }
        .stMetric    { background:#F7F9FC; border-radius:10px; padding:10px; }
        div[data-testid="metric-container"] { border-left: 4px solid #3498DB; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# LOAD DATA  (live → cached JSON → mock fallback)
# ─────────────────────────────────────────────

TENDERS_JSON = Path(__file__).parent / "tenders.json"


@st.cache_data(ttl=3600, show_spinner=False)
def load_data() -> pd.DataFrame:
    """
    Priority:
      1. tenders.json  (written by scraper.py — real portal data)
      2. load_mock_tender_data() (built-in fallback)
    """
    if TENDERS_JSON.exists():
        try:
            records = json.loads(TENDERS_JSON.read_text(encoding="utf-8"))
            if records:
                df = pd.DataFrame(records)
                # Ensure required columns exist
                for col in ["latitude", "longitude"]:
                    if col not in df.columns:
                        df[col] = None
                df["latitude"]  = pd.to_numeric(df["latitude"],  errors="coerce")
                df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
                df["allocated_amount"] = pd.to_numeric(
                    df["allocated_amount"], errors="coerce"
                ).fillna(0.0)
                return df
        except (json.JSONDecodeError, KeyError):
            pass
    return load_mock_tender_data()


df_raw = load_data()

# Data source indicator shown in sidebar
_data_source = "📡 Live (tenders.json)" if TENDERS_JSON.exists() else "🧪 Mock / Demo Data"


# ─────────────────────────────────────────────
# SIDEBAR FILTERS
# ─────────────────────────────────────────────
with st.sidebar:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3f/Emblem_of_Bihar.svg/200px-Emblem_of_Bihar.svg.png",
        width=80,
    )
    st.title("🔍 Filter Tenders")
    st.markdown("---")

    # Category multi-select
    all_categories = sorted(df_raw["category"].unique().tolist())
    selected_categories = st.multiselect(
        "Infrastructure Category",
        options=all_categories,
        default=all_categories,
        help="Select one or more project types to display on the map.",
    )

    # Status filter
    all_statuses = sorted(df_raw["status"].unique().tolist())
    selected_statuses = st.multiselect(
        "Project Status",
        options=all_statuses,
        default=all_statuses,
    )

    # Budget range slider
    min_amt = float(df_raw["allocated_amount"].min())
    max_amt = float(df_raw["allocated_amount"].max())
    budget_range = st.slider(
        "Budget Range (₹ Crores)",
        min_value=min_amt,
        max_value=max_amt,
        value=(min_amt, max_amt),
        step=0.10,
        format="₹%.2f Cr",
    )

    st.markdown("---")
    st.caption(f"Data: {_data_source}")
    st.caption("© 2026 Transparency Initiative, Samastipur")

    st.markdown("---")
    st.markdown("#### 🔄 Refresh Live Data")
    st.caption("Scrapes Bihar portal + CPPP, then geocodes new locations.")

    run_mock = st.checkbox("Use mock data (offline mode)", value=not TENDERS_JSON.exists())

    if st.button("▶ Run Scraper Pipeline", type="primary", use_container_width=True):
        cmd = ["python3", str(Path(__file__).parent / "scraper.py")]
        if run_mock:
            cmd.append("--mock")
        with st.spinner("Running scraper… (this may take 1–2 minutes)"):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            st.success("✅ Pipeline complete — reloading data")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("Pipeline failed. See logs below.")
            st.code(result.stderr[-2000:] if result.stderr else result.stdout[-2000:])


# ─────────────────────────────────────────────
# APPLY FILTERS
# ─────────────────────────────────────────────
df = df_raw[
    df_raw["category"].isin(selected_categories)
    & df_raw["status"].isin(selected_statuses)
    & df_raw["allocated_amount"].between(budget_range[0], budget_range[1])
].copy()


# ─────────────────────────────────────────────
# PAGE HEADER
# ─────────────────────────────────────────────
st.markdown(
    '<p class="main-title">🗺️ Samastipur Public Expenditure & Tender Tracker</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="sub-title">Real-time visibility into government infrastructure spending — Samastipur District, Bihar</p>',
    unsafe_allow_html=True,
)
st.markdown("---")


# ─────────────────────────────────────────────
# KPI METRICS
# ─────────────────────────────────────────────
if df.empty:
    st.warning("⚠️ No tenders match the selected filters. Please adjust your criteria in the sidebar.")
    st.stop()

total_funds   = df["allocated_amount"].sum()
active_count  = df[df["status"] == "Active"].shape[0]
avg_cost      = df["allocated_amount"].mean()
top_project   = df.loc[df["allocated_amount"].idxmax()]

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="💰 Total Funds Tracked",
        value=f"₹{total_funds:.2f} Cr",
        help="Sum of all filtered tender allocations",
    )
with col2:
    st.metric(
        label="📋 Active Projects",
        value=f"{active_count}",
        help="Count of tenders currently in 'Active' status",
    )
with col3:
    st.metric(
        label="📊 Avg Cost / Project",
        value=f"₹{avg_cost:.2f} Cr",
        help="Mean allocation across all filtered tenders",
    )
with col4:
    st.metric(
        label="🏆 Highest Funded",
        value=f"₹{top_project['allocated_amount']:.2f} Cr",
        delta=top_project["title"][:35] + "…",
        delta_color="off",
        help="Single largest tender in current filter",
    )

st.markdown("---")


# ─────────────────────────────────────────────
# PREPARE MAP DATA
# ─────────────────────────────────────────────

# Build a formatted hover label column
df["amount_fmt"]  = df["allocated_amount"].apply(lambda x: f"₹{x:.2f} Crores")
df["status_icon"] = df["status"].map(STATUS_SYMBOLS)
df["hover_label"] = (
    "<b>" + df["title"] + "</b><br>"
    + "🏢 " + df["department"] + "<br>"
    + "💰 " + df["amount_fmt"] + "<br>"
    + "📌 " + df["status_icon"] + " " + df["status"]
)

# Scale bubble size — min 10, max 50 proportional to amount
size_min, size_max = 10, 50
amt_min = df["allocated_amount"].min()
amt_max = df["allocated_amount"].max()
if amt_max > amt_min:
    df["bubble_size"] = (
        (df["allocated_amount"] - amt_min) / (amt_max - amt_min)
        * (size_max - size_min)
        + size_min
    )
else:
    df["bubble_size"] = (size_min + size_max) / 2


# ─────────────────────────────────────────────
# INTERACTIVE MAP
# ─────────────────────────────────────────────
map_col, legend_col = st.columns([4, 1])

with map_col:
    fig = px.scatter_mapbox(
        df,
        lat="latitude",
        lon="longitude",
        size="bubble_size",
        color="category",
        color_discrete_map=CATEGORY_COLORS,
        hover_name="title",
        hover_data={
            "department":        True,
            "amount_fmt":        True,
            "status":            True,
            "bubble_size":       False,   # hide raw size value
            "latitude":          False,
            "longitude":         False,
        },
        labels={
            "amount_fmt":  "Allocated",
            "department":  "Department",
            "status":      "Status",
            "category":    "Category",
        },
        mapbox_style="open-street-map",
        center={"lat": 25.86, "lon": 85.78},
        zoom=9,
        height=540,
        title="",
    )

    fig.update_traces(
        marker=dict(opacity=0.80, sizemode="area"),
        hovertemplate=(
            "<b>%{hovertext}</b><br>"
            "🏢 %{customdata[0]}<br>"
            "💰 %{customdata[1]}<br>"
            "📌 %{customdata[2]}<extra></extra>"
        ),
    )

    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(
            title="Category",
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="right",
            x=1,
        ),
    )

    st.plotly_chart(fig, use_container_width=True)

with legend_col:
    st.markdown("#### 📌 Legend")
    st.markdown("**By Category**")
    for cat, color in CATEGORY_COLORS.items():
        st.markdown(
            f'<span style="background:{color};border-radius:50%;display:inline-block;'
            f'width:12px;height:12px;margin-right:6px;"></span> {cat}',
            unsafe_allow_html=True,
        )
    st.markdown("---")
    st.markdown("**By Status**")
    for status, icon in STATUS_SYMBOLS.items():
        st.markdown(f"{icon} {status}")
    st.markdown("---")
    st.markdown("**Bubble Size**")
    st.caption("Larger bubble = Higher budget allocation")
    st.markdown("---")
    st.markdown(f"**Showing**")
    st.markdown(f"`{len(df)}` of `{len(df_raw)}` tenders")


# ─────────────────────────────────────────────
# DATA TABLE
# ─────────────────────────────────────────────
st.markdown("---")
st.subheader("📄 Filtered Tender Details")

display_cols = {
    "tender_id":        "Tender ID",
    "title":            "Project Title",
    "category":         "Category",
    "allocated_amount": "Amount (₹ Cr)",
    "location_raw":     "Location",
    "status":           "Status",
    "department":       "Department",
}

df_display = df[list(display_cols.keys())].rename(columns=display_cols).copy()
df_display["Amount (₹ Cr)"] = df_display["Amount (₹ Cr)"].apply(lambda x: f"₹{x:.2f} Cr")

st.dataframe(
    df_display,
    use_container_width=True,
    height=320,
    hide_index=True,
)

# Download button
csv_data = df[list(display_cols.keys())].rename(columns=display_cols).to_csv(index=False)
st.download_button(
    label="⬇️ Download Filtered Data (CSV)",
    data=csv_data,
    file_name="samastipur_tenders_filtered.csv",
    mime="text/csv",
)


# ─────────────────────────────────────────────
# CATEGORY BREAKDOWN CHART
# ─────────────────────────────────────────────
st.markdown("---")
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("💹 Funds by Category")
    cat_summary = (
        df.groupby("category")["allocated_amount"]
        .sum()
        .reset_index()
        .rename(columns={"allocated_amount": "Total (₹ Cr)"})
    )
    bar_fig = px.bar(
        cat_summary,
        x="category",
        y="Total (₹ Cr)",
        color="category",
        color_discrete_map=CATEGORY_COLORS,
        text_auto=".2f",
        labels={"category": "Category", "Total (₹ Cr)": "₹ Crores"},
    )
    bar_fig.update_layout(showlegend=False, margin=dict(t=20, b=20))
    st.plotly_chart(bar_fig, use_container_width=True)

with chart_col2:
    st.subheader("📊 Status Distribution")
    status_summary = df["status"].value_counts().reset_index()
    status_summary.columns = ["Status", "Count"]
    pie_fig = px.pie(
        status_summary,
        names="Status",
        values="Count",
        color="Status",
        color_discrete_map={
            "Active":    "#27AE60",
            "Awarded":   "#F39C12",
            "Completed": "#3498DB",
        },
        hole=0.45,
    )
    pie_fig.update_traces(textposition="outside", textinfo="percent+label")
    pie_fig.update_layout(margin=dict(t=20, b=20), showlegend=True)
    st.plotly_chart(pie_fig, use_container_width=True)
