"""
pipeline.py — Production Data Layer for Pan-India Tender Tracker

Load priority:
  1. tenders.json  (output from scraper.py — live portal data)
  2. data/pan_india_tenders.csv  (curated seed dataset)

Provides:
  - load_production_pipeline_data()  → master DataFrame
  - get_hierarchy()                  → {state: {district: [blocks]}}
  - get_view_config()                → zoom + center for any drill-down level
"""

import json
import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

BASE_DIR    = Path(__file__).parent
JSON_FILE   = BASE_DIR / "tenders.json"
CSV_FILE    = BASE_DIR / "data" / "pan_india_tenders.csv"

REQUIRED_COLS = [
    "tender_id", "title", "category", "allocated_amount",
    "state", "district", "block",
    "latitude", "longitude", "status", "department",
]

# ── Geographic centres for auto-zoom ──────────────────────────────────────

INDIA_CENTER = {"lat": 22.5, "lon": 82.5}
INDIA_ZOOM   = 4

# State-level centres (capital / geographic centroid)
STATE_CENTERS: dict[str, dict] = {
    "Andhra Pradesh":     {"lat": 15.9129, "lon": 79.7400, "zoom": 6},
    "Arunachal Pradesh":  {"lat": 27.0844, "lon": 93.6053, "zoom": 6},
    "Assam":              {"lat": 26.2006, "lon": 92.9376, "zoom": 7},
    "Bihar":              {"lat": 25.6, "lon": 85.6, "zoom": 7},
    "Chhattisgarh":       {"lat": 21.2787, "lon": 81.8661, "zoom": 6},
    "Goa":                {"lat": 15.2993, "lon": 74.1240, "zoom": 9},
    "Gujarat":            {"lat": 22.2587, "lon": 71.1924, "zoom": 6},
    "Haryana":            {"lat": 29.0588, "lon": 76.0856, "zoom": 7},
    "Himachal Pradesh":   {"lat": 31.1048, "lon": 77.1734, "zoom": 7},
    "Jharkhand":          {"lat": 23.6102, "lon": 85.2799, "zoom": 7},
    "Karnataka":          {"lat": 15.3173, "lon": 75.7139, "zoom": 6},
    "Kerala":             {"lat": 10.8505, "lon": 76.2711, "zoom": 7},
    "Madhya Pradesh":     {"lat": 22.9734, "lon": 78.6569, "zoom": 6},
    "Maharashtra":        {"lat": 19.7515, "lon": 75.7139, "zoom": 6},
    "Manipur":            {"lat": 24.6637, "lon": 93.9063, "zoom": 8},
    "Meghalaya":          {"lat": 25.4670, "lon": 91.3662, "zoom": 8},
    "Mizoram":            {"lat": 23.1645, "lon": 92.9376, "zoom": 8},
    "Nagaland":           {"lat": 26.1584, "lon": 94.5624, "zoom": 8},
    "Odisha":             {"lat": 20.9517, "lon": 85.0985, "zoom": 6},
    "Punjab":             {"lat": 31.1471, "lon": 75.3412, "zoom": 7},
    "Rajasthan":          {"lat": 27.0238, "lon": 74.2179, "zoom": 6},
    "Sikkim":             {"lat": 27.5330, "lon": 88.5122, "zoom": 9},
    "Tamil Nadu":         {"lat": 11.1271, "lon": 78.6569, "zoom": 6},
    "Telangana":          {"lat": 18.1124, "lon": 79.0193, "zoom": 7},
    "Tripura":            {"lat": 23.9408, "lon": 91.9882, "zoom": 8},
    "Uttar Pradesh":      {"lat": 26.8467, "lon": 80.9462, "zoom": 6},
    "Uttarakhand":        {"lat": 30.0668, "lon": 79.0193, "zoom": 7},
    "West Bengal":        {"lat": 22.9868, "lon": 87.8550, "zoom": 7},
    "Delhi":              {"lat": 28.6139, "lon": 77.2090, "zoom": 10},
    "Jammu & Kashmir":    {"lat": 33.7782, "lon": 76.5762, "zoom": 7},
    "Ladakh":             {"lat": 34.1526, "lon": 77.5770, "zoom": 7},
}


# ── Data Loader ───────────────────────────────────────────────────────────

def _validate_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure schema, coerce types, drop unresolvable rows."""
    for col in REQUIRED_COLS:
        if col not in df.columns:
            df[col] = None

    df["allocated_amount"] = pd.to_numeric(df["allocated_amount"], errors="coerce").fillna(0.0)
    df["latitude"]         = pd.to_numeric(df["latitude"],         errors="coerce")
    df["longitude"]        = pd.to_numeric(df["longitude"],        errors="coerce")

    # Fill missing lat/lon with state centre
    for idx, row in df[df["latitude"].isna()].iterrows():
        c = STATE_CENTERS.get(str(row.get("state", "")), {})
        df.at[idx, "latitude"]  = c.get("lat", 22.5)
        df.at[idx, "longitude"] = c.get("lon", 82.5)

    df["state"]    = df["state"].fillna("Unknown").str.strip()
    df["district"] = df["district"].fillna("Unknown").str.strip()
    df["block"]    = df["block"].fillna("Unknown").str.strip()
    df["status"]   = df["status"].fillna("Active").str.strip()
    df["category"] = df["category"].fillna("Other").str.strip()

    return df.dropna(subset=["latitude", "longitude"])


def load_production_pipeline_data() -> pd.DataFrame:
    """
    Load tender data from the best available source.
    Returns a clean, schema-validated DataFrame.
    """
    # 1 — Try live scraped JSON
    if JSON_FILE.exists():
        try:
            records = json.loads(JSON_FILE.read_text(encoding="utf-8"))
            if records:
                df = pd.DataFrame(records)
                # Only use if it has national columns; else fall through
                if "state" in df.columns and df["state"].notna().any():
                    logger.info("Loaded %d records from %s", len(df), JSON_FILE)
                    return _validate_and_clean(df)
        except Exception as e:
            logger.warning("Could not load tenders.json: %s", e)

    # 2 — Seed CSV
    if CSV_FILE.exists():
        try:
            df = pd.read_csv(CSV_FILE, dtype=str)
            logger.info("Loaded %d records from seed CSV", len(df))
            return _validate_and_clean(df)
        except Exception as e:
            logger.warning("Could not load seed CSV: %s", e)

    raise FileNotFoundError(
        "No data source found. Run `python3 scraper.py` or ensure "
        f"{CSV_FILE} exists."
    )


# ── Hierarchy Builder ─────────────────────────────────────────────────────

def get_hierarchy(df: pd.DataFrame) -> dict:
    """
    Returns nested dict: {state → {district → [blocks]}}
    Sorted alphabetically at every level.
    """
    hierarchy: dict = {}
    for state, grp in df.groupby("state"):
        hierarchy[state] = {}
        for district, sub in grp.groupby("district"):
            hierarchy[state][district] = sorted(sub["block"].unique().tolist())
    return dict(sorted(hierarchy.items()))


# ── View Config (auto-zoom) ───────────────────────────────────────────────

def get_view_config(
    df_filtered: pd.DataFrame,
    state: str = None,
    district: str = None,
) -> dict:
    """
    Returns {"lat": ..., "lon": ..., "zoom": ...} based on drill-down level.
    Falls back to mean of filtered data coordinates when centroid unknown.
    """
    if state and state != "All States":
        if district and district != "All Districts":
            # District view — centre on filtered data
            lat = df_filtered["latitude"].mean()
            lon = df_filtered["longitude"].mean()
            return {"lat": lat, "lon": lon, "zoom": 9}

        # State view
        cfg = STATE_CENTERS.get(state, {})
        return {"lat": cfg.get("lat", 22.5), "lon": cfg.get("lon", 82.5), "zoom": cfg.get("zoom", 7)}

    # National view
    return {**INDIA_CENTER, "zoom": INDIA_ZOOM}
