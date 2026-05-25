"""
services/aggregator.py — Data loading, coordinate resolution, and aggregation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT THIS FILE DOES (plain English)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This is the "data kitchen" — the layer between the raw database and the
Streamlit dashboard (app.py).

When the dashboard starts, it calls load_enterprise_tender_stream() which:
  1. Tries to read REAL scraped data from tenders.db
  2. Falls back to generated_tenders.csv if the DB is empty
  3. Generates 10,000 synthetic records if there's no file either

After loading, the data is:
  • Coordinates fixed — tenders without GPS coords get placed at their
    district/state centre (with small random jitter so they don't all stack)
  • Re-classified — sectors are re-checked by the reclassifier for accuracy
  • Memory-optimised — string columns stored as Categorical to use less RAM
    (42,000 rows with full strings ≈ 80 MB; with Categorical ≈ 18 MB)

KEY FUNCTIONS FOR THE DASHBOARD
─────────────────────────────────
  load_enterprise_tender_stream() → pd.DataFrame
      The main entry point. Returns ALL tenders as a DataFrame.

  load_health_log()              → pd.DataFrame | None
      Returns the scraping health log (which portals were scraped, when,
      how many records each returned, and whether they errored).

  get_full_hierarchy(df)         → nested dict
      Sector → Department → State → District → [Blocks].
      Powers the sidebar drill-down filters.

  server_side_aggregate(df, col) → pd.DataFrame
      Groups by any column and computes sum/count/centroid.
      Used by the map to show one bubble per district/state instead of
      42,000 individual dots (which would be slow to render).

  get_view_config(df, state, district) → {lat, lon, zoom}
      Computes where the map should centre when a filter is applied.

COORDINATE RESOLUTION PRIORITY
────────────────────────────────
  1. Block-level coordinates (most precise, from config/geography.py table)
  2. District-level coordinates (offset by ≤5 km random jitter)
  3. State-level centre (offset by ≤20 km random jitter)

Jitter is deterministic (seeded by tender_id hash) so the map looks
stable across dashboard refreshes — dots don't "bounce".
"""

import logging
import math
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config.sectors import SECTOR_DEPARTMENTS, SECTOR_COLORS
from config.geography import (
    STATES_DATA, STATE_CENTERS, DISTRICT_COORDINATES, BLOCK_COORDINATES,
    LINEAR_KEYWORDS, TITLE_TEMPLATES, SECTOR_WEIGHTS,
)
from models.tender import _stable_hash, is_linear_title, linear_endpoints

logger = logging.getLogger("tender_pipeline")

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Sector constants used by the synthetic data generator ──────────────────────
# Order matters — must match SECTOR_WEIGHTS in config/geography.py

_SECTOR_LIST: List[str] = [
    "Infrastructure",
    "Health",
    "Education",
    "Agriculture",
    "MSME",
    "Energy",
    "Water & Sanitation",
    "Urban Development",
    "Rural Development",
    "Minority Affairs",
    "Social Welfare",
    "Digital & IT",
]

# Short codes used as part of synthetic tender IDs (e.g. "GEM/2026/INF/100001")
_SECTOR_ABBREV: Dict[str, str] = {
    "Infrastructure":     "INF",
    "Health":             "HLT",
    "Education":          "EDU",
    "Agriculture":        "AGR",
    "MSME":               "MSM",
    "Energy":             "ENR",
    "Water & Sanitation": "WAS",
    "Urban Development":  "URB",
    "Rural Development":  "RUR",
    "Minority Affairs":   "MIN",
    "Social Welfare":     "SWL",
    "Digital & IT":       "DIG",
}


# ── Coordinate resolution ──────────────────────────────────────────────────────

def _district_coords(state: str, district: str) -> Optional[Dict[str, float]]:
    """
    Look up GPS coordinates for a district centre from the pre-built table.
    Tries exact match first, then Title Case, then case-insensitive.
    Returns None if the district isn't in our table (e.g. very small UTs).
    """
    if state not in DISTRICT_COORDINATES:
        return None
    state_dict = DISTRICT_COORDINATES[state]
    # Try exact match, then title-case, then full lowercase scan
    if district in state_dict:
        return state_dict[district]
    title = district.title()
    if title in state_dict:
        return state_dict[title]
    dl = district.lower()
    for k, v in state_dict.items():
        if k.lower() == dl:
            return v
    return None


def resolve_coords(state: str, district: str, block: str, rng: np.random.Generator) -> tuple:
    """
    Place a tender at the most precise known GPS coordinate, with small
    random jitter so tenders in the same area don't stack on top of each other.

    Priority:
      1. Block centre  (± 0.005° ≈ ± 500 m) — most precise
      2. District centre (± 0.05° ≈ ± 5 km)
      3. State centre  (± 0.25° ≈ ± 20 km) — coarsest fallback
    """
    # Level 1: block-level precision
    if (state in BLOCK_COORDINATES
            and district in BLOCK_COORDINATES[state]
            and block in BLOCK_COORDINATES[state][district]):
        c = BLOCK_COORDINATES[state][district][block]
        return (c["lat"] + rng.uniform(-0.005, 0.005),
                c["lon"] + rng.uniform(-0.005, 0.005))

    # Level 2: district centre
    c = _district_coords(state, district)
    if c is not None:
        return (c["lat"] + rng.uniform(-0.05, 0.05),
                c["lon"] + rng.uniform(-0.05, 0.05))

    # Level 3: state centre fallback
    c = STATE_CENTERS[state]
    return (c["lat"] + rng.uniform(-0.25, 0.25),
            c["lon"] + rng.uniform(-0.25, 0.25))


def apply_memory_optimization(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reduce DataFrame RAM usage before loading into the dashboard.

    String columns with few unique values (state, sector, etc.) are converted
    to pandas Categorical — this stores the unique strings once and uses
    integer indices for every row, saving ~60% RAM on 42,000+ rows.

    Float columns are downcast to float32 (4 bytes) from float64 (8 bytes)
    since GPS coordinates only need ~6 decimal places of precision.

    NOTE: app.py's get_data() immediately re-casts Categorical back to str
    because Plotly's internal max() on non-ordered Categoricals raises TypeError.
    """
    cat_cols = ["state", "district", "block", "sector", "department", "status"]
    for col in cat_cols:
        if col in df.columns:
            df[col] = pd.Categorical(df[col])

    if "category" in df.columns:
        df["category"] = pd.Categorical(df["category"])

    for col in ["allocated_amount", "latitude", "longitude", "latitude2", "longitude2"]:
        if col in df.columns:
            df[col] = df[col].astype(np.float32)

    logger.info(
        "Memory optimisation applied. Usage: %.2f MB",
        df.memory_usage(deep=True).sum() / (1024 ** 2),
    )
    return df


def _disambiguate_within_district(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fix tenders that have NULL coordinates or that landed exactly on a district
    centre (which happens when the scraper had no GPS info and we fell back to
    the centroid). Both cases result in dozens of dots stacked at one point.

    Solution: scatter them in a deterministic circle around the district centre.
    The angle and radius are derived from the tender_id hash, so the same
    tender always ends up at the same offset — stable across refreshes.
    """
    if df.empty:
        return df

    states    = df["state"].astype(str)    if "state"    in df.columns else None
    districts = df["district"].astype(str) if "district" in df.columns else None

    fixed = 0
    for idx in df.index:
        state    = states[idx]    if states    is not None else None
        district = districts[idx] if districts is not None else None
        lat = df.at[idx, "latitude"]
        lon = df.at[idx, "longitude"]

        # Check whether this tender needs a new position
        needs_fix = False
        d_centre = _district_coords(state, district)
        if pd.isna(lat) or pd.isna(lon):
            needs_fix = True
        elif d_centre is not None:
            # Treat anything within 100 m of the district centroid as "stacked"
            if abs(float(lat) - d_centre["lat"]) < 0.001 and abs(float(lon) - d_centre["lon"]) < 0.001:
                needs_fix = True

        if not needs_fix:
            continue

        # Find the best available centre to scatter around
        if d_centre is not None:
            centre = d_centre
        elif state in STATE_CENTERS:
            centre = STATE_CENTERS[state]
        else:
            centre = {"lat": 22.5, "lon": 82.5}   # geographic centre of India

        # Deterministic jitter: 2–7 km in a hash-derived direction
        tid = str(df.at[idx, "tender_id"]) if "tender_id" in df.columns else f"row{idx}"
        h = _stable_hash(tid)
        angle      = (h % 360) * math.pi / 180
        radius_km  = 2.0 + ((h >> 8) & 0xFF) / 255.0 * 5.0
        lat_off    = (radius_km / 111.0) * math.sin(angle)
        lon_factor = max(0.5, math.cos(math.radians(centre["lat"])))
        lon_off    = (radius_km / (111.0 * lon_factor)) * math.cos(angle)

        df.at[idx, "latitude"]  = round(centre["lat"] + lat_off, 6)
        df.at[idx, "longitude"] = round(centre["lon"] + lon_off, 6)
        fixed += 1

    if fixed:
        logger.info("Disambiguated %d stacked/NaN coords with deterministic jitter", fixed)
    return df


# ── Synthetic data generator ───────────────────────────────────────────────────

def _build_lookup_tables() -> tuple:
    """
    Pre-compute flat arrays from STATES_DATA (which is a nested dict) for
    fast random sampling during synthetic data generation.
    States are weighted by number of districts (more districts = more tenders).
    """
    state_list: List[str] = []
    district_counts: List[int] = []
    district_map: Dict[str, List[str]] = {}
    block_map: Dict[tuple, List[str]] = {}

    for state, districts in STATES_DATA.items():
        state_list.append(state)
        district_counts.append(len(districts))
        district_map[state] = list(districts.keys())
        for district, blocks in districts.items():
            block_map[(state, district)] = blocks

    counts_arr = np.array(district_counts, dtype=np.float64)
    state_probs = counts_arr / counts_arr.sum()   # normalise to probabilities

    return state_list, state_probs, district_map, block_map


# Build lookup tables once at module import (not on every function call)
_STATE_LIST, _STATE_PROBS, _DISTRICT_MAP, _BLOCK_MAP = _build_lookup_tables()


def generate_enterprise_seed_data(n: int = 10_000) -> pd.DataFrame:
    """
    Generate n realistic-looking synthetic government tenders for demo/preview.

    Used only when the real tenders.db is empty or missing. The seed=42 means
    the same records are generated every time — consistent demo data.

    Key design choices:
      - Sector distribution follows SECTOR_WEIGHTS (Infrastructure-heavy, as in reality)
      - State distribution proportional to number of districts
      - Amounts follow a log-normal distribution (many small tenders, few large)
      - 55% Active, 25% Awarded, 20% Completed (typical pipeline mix)
      - Linear tenders (roads, pipelines) get a second GPS endpoint for map lines
    """
    logger.info("Generating %d synthetic tender records ...", n)
    rng = np.random.default_rng(seed=42)   # fixed seed = reproducible output

    # ── Sector, state, district, block ─────────────────────────────────────────
    sector_indices = rng.choice(len(_SECTOR_LIST), size=n, p=SECTOR_WEIGHTS)
    sectors: List[str] = [_SECTOR_LIST[i] for i in sector_indices]

    state_indices = rng.choice(len(_STATE_LIST), size=n, p=_STATE_PROBS)
    states: List[str] = [_STATE_LIST[i] for i in state_indices]

    districts: List[str] = []
    blocks: List[str] = []
    for st in states:
        dist_choices  = _DISTRICT_MAP[st]
        chosen_dist   = dist_choices[int(rng.integers(0, len(dist_choices)))]
        block_choices = _BLOCK_MAP[(st, chosen_dist)]
        chosen_block  = block_choices[int(rng.integers(0, len(block_choices)))]
        districts.append(chosen_dist)
        blocks.append(chosen_block)

    departments: List[str] = []
    for sec in sectors:
        dept_list = SECTOR_DEPARTMENTS[sec]
        departments.append(dept_list[int(rng.integers(0, len(dept_list)))])

    # ── Titles from templates ──────────────────────────────────────────────────
    titles: List[str] = []
    for i in range(n):
        sec      = sectors[i]
        templates = TITLE_TEMPLATES[sec]
        tmpl     = templates[int(rng.integers(0, len(templates)))]
        titles.append(tmpl.format(
            sector=sec, block=blocks[i], district=districts[i], state=states[i],
        ))

    # ── Tender IDs ─────────────────────────────────────────────────────────────
    tender_ids: List[str] = []
    for i in range(n):
        abbrev = _SECTOR_ABBREV[sectors[i]]
        tender_ids.append(f"GEM/2026/{abbrev}/{100000 + i}")

    # ── Amounts — log-normal so most tenders are small, a few are very large ───
    log_amounts      = rng.lognormal(mean=1.5, sigma=1.2, size=n)
    allocated_amounts = np.clip(log_amounts, 0.01, 5000.0)
    allocated_amounts = np.round(allocated_amounts, 2)

    # ── GPS coordinates ────────────────────────────────────────────────────────
    lats  = np.empty(n, dtype=np.float64)
    lons  = np.empty(n, dtype=np.float64)
    lats2 = np.full(n, np.nan, dtype=np.float64)   # second point (linear only)
    lons2 = np.full(n, np.nan, dtype=np.float64)

    for i in range(n):
        lat_i, lon_i = resolve_coords(states[i], districts[i], blocks[i], rng)
        lats[i] = lat_i
        lons[i] = lon_i
        # Road/pipeline/line tenders get an endpoint to draw as a line on the map
        if is_linear_title(titles[i]):
            lat2, lon2 = linear_endpoints(lat_i, lon_i, tender_ids[i])
            lats2[i] = lat2
            lons2[i] = lon2

    lats = np.round(lats, 6)
    lons = np.round(lons, 6)

    # ── Status ─────────────────────────────────────────────────────────────────
    status_choices = ["Active", "Awarded", "Completed"]
    status_probs   = np.array([0.55, 0.25, 0.20])
    status_indices = rng.choice(3, size=n, p=status_probs)
    statuses: List[str] = [status_choices[int(i)] for i in status_indices]

    # Only Awarded/Completed tenders have a contractor name
    CONTRACTORS = [
        "L&T Construction", "Tata Projects Ltd", "Shapoorji Pallonji",
        "Hindustan Construction Co (HCC)", "Gammon India", "IRCON International",
        "Afcons Infrastructure", "NBCC India", "KEC International",
        "Punj Lloyd", "Dilip Buildcon", "GR Infraprojects", "PNC Infratech",
        "Megha Engineering", "Sadbhav Engineering", "Ashoka Buildcon",
        "ITD Cementation", "Reliance Infra", "J Kumar Infraprojects",
        "Local Contractor (TBD)",
    ]
    contractors = np.where(
        np.array(statuses) == "Active",
        "",
        rng.choice(CONTRACTORS, size=n),
    )

    # ── Dates ──────────────────────────────────────────────────────────────────
    today         = pd.Timestamp.today().normalize()
    start_offsets = rng.integers(-540, 60, size=n)       # up to 18 months in the past
    duration_days = rng.integers(365, 365 * 3, size=n)   # 1–3 year contracts
    start_dates   = [(today + pd.Timedelta(days=int(o))).date().isoformat() for o in start_offsets]
    end_dates     = [(today + pd.Timedelta(days=int(o + d))).date().isoformat()
                     for o, d in zip(start_offsets, duration_days)]

    # Completed tenders must have an end date in the past
    for i, s in enumerate(statuses):
        if s == "Completed":
            past = today - pd.Timedelta(days=int(rng.integers(30, 365)))
            end_dates[i] = past.date().isoformat()

    return pd.DataFrame({
        "tender_id":        tender_ids,
        "title":             titles,
        "sector":            sectors,
        "department":        departments,
        "state":             states,
        "district":          districts,
        "block":             blocks,
        "allocated_amount":  allocated_amounts,
        "latitude":          lats,
        "longitude":         lons,
        "latitude2":         lats2,
        "longitude2":        lons2,
        "status":            statuses,
        "contractor_name":   contractors,
        "start_date":        start_dates,
        "end_date":          end_dates,
        "source":            "Seed Data",
        "source_url":        "",
    })


# ── Real data loader ───────────────────────────────────────────────────────────

def _load_from_sqlite() -> Optional[pd.DataFrame]:
    """
    Load all 42,000+ scraped tenders from tenders.db.

    Post-processing steps after reading from DB:
      1. Ensure new columns exist (ALTER TABLE idempotently)
      2. Backfill linear endpoints for road/pipeline titles that lack lat2/lon2
      3. Disambiguate stacked coordinates (district-centre pile-ups)
      4. Re-classify sectors with the latest classifier rules

    Returns None if DB is missing or has fewer than 10 rows (empty/test state).
    """
    db_path = BASE_DIR / "tenders.db"
    if not db_path.exists():
        return None
    try:
        conn  = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        if count < 10:
            conn.close()
            return None

        # Ensure columns added in later migrations exist (safe no-op if they do)
        for col, sql_type in (("latitude2", "REAL"), ("longitude2", "REAL"),
                              ("contractor_name", "TEXT"), ("start_date", "TEXT"),
                              ("end_date", "TEXT"), ("source_url", "TEXT")):
            try:
                conn.execute(f"ALTER TABLE tenders ADD COLUMN {col} {sql_type}")
            except sqlite3.OperationalError:
                pass
        conn.commit()

        df = pd.read_sql(
            "SELECT tender_id, title, sector, department, state, district, block, "
            "       allocated_amount, latitude, longitude, latitude2, longitude2, "
            "       status, source, source_url, contractor_name, start_date, end_date "
            "FROM tenders",
            conn,
        )
        conn.close()
        logger.info("Loaded %d real scraped records from tenders.db", len(df))

        # Backfill second GPS point for linear tenders that were scraped before
        # linear endpoint support was added (lat2 will be NaN for those rows)
        need_classify = df["latitude2"].isna()
        if need_classify.any():
            backfilled = 0
            for idx in df[need_classify].index:
                title = str(df.at[idx, "title"]) if pd.notna(df.at[idx, "title"]) else ""
                if is_linear_title(title):
                    lat = float(df.at[idx, "latitude"]) if pd.notna(df.at[idx, "latitude"]) else None
                    lon = float(df.at[idx, "longitude"]) if pd.notna(df.at[idx, "longitude"]) else None
                    if lat is not None and lon is not None:
                        tid = str(df.at[idx, "tender_id"])
                        lat2, lon2 = linear_endpoints(lat, lon, tid)
                        df.at[idx, "latitude2"]  = lat2
                        df.at[idx, "longitude2"] = lon2
                        backfilled += 1
            if backfilled:
                logger.info("Backfilled %d linear endpoints from titles", backfilled)

        df = _disambiguate_within_district(df)

        # Apply latest classification rules (updates sector column in-place)
        try:
            from services.classifier import reclassify_dataframe
            reclassify_dataframe(df)
        except Exception as e:
            logger.warning("Reclassifier skipped: %s", e)

        return df
    except Exception as e:
        logger.warning("Could not load tenders.db: %s", e)
        return None


def load_health_log() -> Optional[pd.DataFrame]:
    """
    Read the scraping health log — one row per source per scrape session.

    The health log tells you:
      - Which portals were scraped and when (logged_at)
      - Whether they succeeded or failed
      - How many records each returned
      - What error occurred (if any)

    The dashboard uses this for the "Portal Health" table in Tab 4.
    Duplicates are dropped keeping only the most recent entry per source.
    """
    db_path = BASE_DIR / "tenders.db"
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql(
            """SELECT source, domain, status, error_code, error_msg,
                      records_fetched, logged_at
               FROM scraping_health_log
               ORDER BY logged_at DESC""",
            conn,
        )
        conn.close()
        if df.empty:
            return df
        # Keep only the most recent entry per source (shows current health, not history)
        df = df.drop_duplicates(subset=["source", "domain"], keep="first")
        return df.reset_index(drop=True)
    except Exception as e:
        logger.warning("Could not load health log: %s", e)
        return None


def load_enterprise_tender_stream() -> pd.DataFrame:
    """
    Main entry point for the dashboard — returns all tenders as a DataFrame.

    Load priority:
      1. tenders.db         — real scraped data (42,000+ rows if populated)
      2. generated_tenders.csv — cached seed data from a previous run
      3. Generate fresh seed data — last resort for first-time demo

    Returns a memory-optimised DataFrame ready for Streamlit display.

    NOTE: app.py's get_data() immediately converts Categorical columns back
    to str because Plotly's treemap/heatmap internals call max() on them,
    which fails for non-ordered Categoricals (pandas limitation).
    """
    # Try real scraped data first
    df = _load_from_sqlite()
    if df is not None:
        df = apply_memory_optimization(df)
        return df

    # Try the committed Parquet snapshot (real data, used on Streamlit Cloud)
    parquet_file = BASE_DIR / "data" / "tenders_snapshot.parquet"
    if parquet_file.exists():
        logger.info("Parquet snapshot found — reading %s ...", parquet_file)
        try:
            df = pd.read_parquet(parquet_file)
            if len(df) > 100:
                logger.info("Loaded %d rows from Parquet snapshot.", len(df))
                df = apply_memory_optimization(df)
                return df
        except Exception as exc:
            logger.warning("Failed to read Parquet snapshot (%s) — falling back.", exc)

    # Try cached seed data
    csv_file = BASE_DIR / "data" / "generated_tenders.csv"
    if csv_file.exists():
        logger.info("Cache file found at %s — reading ...", csv_file)
        try:
            df = pd.read_csv(csv_file, low_memory=False)
            if len(df) > 100:
                logger.info("Loaded %d rows from cache.", len(df))
                df = apply_memory_optimization(df)
                return df
        except Exception as exc:
            logger.warning("Failed to read cache (%s) — regenerating.", exc)

    # Generate fresh synthetic data
    logger.info("No real data yet — generating seed data for UI preview ...")
    df = generate_enterprise_seed_data(10_000)
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_file, index=False)
    logger.info("Saved %d seed rows to %s", len(df), csv_file)
    df = apply_memory_optimization(df)
    return df


# ── Dashboard helpers ──────────────────────────────────────────────────────────

def get_full_hierarchy(df: pd.DataFrame) -> Dict[str, Dict]:
    """
    Build the full drill-down hierarchy used by sidebar filter dropdowns.

    Returns: { sector → { department → { state → { district → [blocks] } } } }

    Example:
      hierarchy["Health"]["State Health Dept"]["Bihar"]["Samastipur"]
      → ["Block A", "Block B", "Block C"]

    The sidebar uses this to show only relevant options at each level.
    """
    hierarchy: Dict[str, Dict] = {}

    for sector in sorted(df["sector"].unique()):
        hierarchy[sector] = {}
        sector_df = df[df["sector"] == sector]

        for dept in sorted(sector_df["department"].unique()):
            hierarchy[sector][dept] = {}
            dept_df = sector_df[sector_df["department"] == dept]

            for state in sorted(dept_df["state"].unique()):
                hierarchy[sector][dept][state] = {}
                state_df = dept_df[dept_df["state"] == state]

                for district in sorted(state_df["district"].unique()):
                    district_df = state_df[state_df["district"] == district]
                    blocks = sorted(district_df["block"].unique().tolist())
                    hierarchy[sector][dept][state][district] = blocks

    return hierarchy


def server_side_aggregate(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """
    Aggregate tenders by a geographic column (typically "district" or "state").

    Returns one row per group with:
      total_amount  — sum of all allocated_amount values
      count         — number of tenders in this group
      lat / lon     — mean GPS centre of the group (for map bubble placement)

    Used by the map when there are >5,000 tenders visible — too many individual
    dots would be slow to render, so we collapse them to one bubble per area.
    """
    agg_df = (
        df.groupby(group_col, observed=True)
        .agg(
            total_amount=("allocated_amount", "sum"),
            count=("tender_id", "count"),
            lat=("latitude", "mean"),
            lon=("longitude", "mean"),
        )
        .reset_index()
    )
    agg_df["total_amount"] = agg_df["total_amount"].round(2)
    agg_df["lat"]          = agg_df["lat"].round(6)
    agg_df["lon"]          = agg_df["lon"].round(6)
    return agg_df


def get_view_config(
    df_filtered: pd.DataFrame,
    state: Optional[str] = None,
    district: Optional[str] = None,
) -> Dict[str, float]:
    """
    Compute the map viewport — where to centre and how far to zoom — based
    on the currently active sidebar filter.

    Logic:
      • District selected  → zoom to district centre (zoom 11, ~city level)
      • State selected     → zoom to state centre   (zoom 7, ~state level)
      • No filter          → show all India          (zoom 4)

    Returns {lat, lon, zoom} dict consumed by plotly's map layout.
    """
    if district is not None and state is not None:
        c = _district_coords(state, district)
        if c is not None:
            lat, lon = c["lat"], c["lon"]
        elif len(df_filtered) > 0:
            lat = float(df_filtered["latitude"].mean())
            lon = float(df_filtered["longitude"].mean())
        elif state in STATE_CENTERS:
            lat = STATE_CENTERS[state]["lat"]
            lon = STATE_CENTERS[state]["lon"]
        else:
            lat, lon = 22.5, 82.5
        return {"lat": round(lat, 4), "lon": round(lon, 4), "zoom": 11}

    if state is not None:
        if state in STATE_CENTERS:
            center = STATE_CENTERS[state]
            return {"lat": center["lat"], "lon": center["lon"], "zoom": center["zoom"]}
        if len(df_filtered) > 0:
            lat = float(df_filtered["latitude"].mean())
            lon = float(df_filtered["longitude"].mean())
            return {"lat": round(lat, 4), "lon": round(lon, 4), "zoom": 7}

    return {"lat": 22.5, "lon": 82.5, "zoom": 4}   # all-India default
