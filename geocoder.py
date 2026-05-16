"""
Module: geocoder.py
Converts raw location strings (block/village names) to lat/lon coordinates.
Uses Nominatim (OSM) with a local JSON cache to avoid redundant API calls.
Fallback: Samastipur district centre if the geocoder cannot resolve a name.
"""

import json
import time
import logging
from pathlib import Path
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

logger = logging.getLogger(__name__)

# Samastipur district centre — used as fallback
SAMASTIPUR_LAT = 25.8624
SAMASTIPUR_LON = 85.7810

# Append this suffix to every raw location before querying
LOCATION_SUFFIX = "Samastipur, Bihar, India"

# Path for persistent cache (JSON file next to this module)
CACHE_FILE = Path(__file__).parent / "geocache.json"


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.write_text(
            json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as e:
        logger.warning("Could not save geocache: %s", e)


def geocode_location(location_raw: str, geolocator: Nominatim, cache: dict) -> tuple[float, float]:
    """
    Returns (latitude, longitude) for a raw location string.
    Checks cache first; hits Nominatim only on a cache miss.
    Falls back to Samastipur centre on any failure.
    """
    query = f"{location_raw.strip()}, {LOCATION_SUFFIX}"

    # Cache hit
    if query in cache:
        entry = cache[query]
        return entry["lat"], entry["lon"]

    # Live geocoding attempt (with 1-second polite delay for Nominatim ToS)
    time.sleep(1)
    try:
        result = geolocator.geocode(query, timeout=10)
        if result:
            lat, lon = result.latitude, result.longitude
            logger.info("Geocoded '%s' → (%.4f, %.4f)", query, lat, lon)
        else:
            logger.warning("No result for '%s' — using district centre", query)
            lat, lon = SAMASTIPUR_LAT, SAMASTIPUR_LON

    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.warning("Geocoder error for '%s': %s — using district centre", query, e)
        lat, lon = SAMASTIPUR_LAT, SAMASTIPUR_LON

    # Sanity check: reject coordinates clearly outside Bihar (approx bounding box)
    if not (24.0 <= lat <= 27.5 and 83.0 <= lon <= 88.5):
        logger.warning(
            "Coordinates (%.4f, %.4f) outside Bihar bounds — resetting to district centre",
            lat, lon,
        )
        lat, lon = SAMASTIPUR_LAT, SAMASTIPUR_LON

    cache[query] = {"lat": lat, "lon": lon}
    return lat, lon


def geocode_dataframe(df, location_col: str = "location_raw"):
    """
    Adds 'latitude' and 'longitude' columns to a DataFrame in-place.
    Skips rows that already have non-null coordinates.
    Returns the modified DataFrame and saves the updated cache to disk.
    """
    import pandas as pd

    cache = _load_cache()
    geolocator = Nominatim(user_agent="samastipur_tender_tracker_v1")

    needs_geocoding = (
        df["latitude"].isna() | df["longitude"].isna()
        if "latitude" in df.columns and "longitude" in df.columns
        else pd.Series([True] * len(df))
    )

    total = needs_geocoding.sum()
    logger.info("Geocoding %d locations…", total)

    for idx in df[needs_geocoding].index:
        raw = df.at[idx, location_col]
        lat, lon = geocode_location(raw, geolocator, cache)
        df.at[idx, "latitude"]  = lat
        df.at[idx, "longitude"] = lon

    _save_cache(cache)
    return df


# ── Quick CLI test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_locations = [
        "Kalyanpur",
        "Rosera",
        "Patori",
        "Dalsinghsarai",
        "Warisnagar",
        "Singhia",
        "Morwa",
        "Bibhutipur",
        "Tajpur",
        "Ujiyarpur",
        "XYZNonExistentVillage123",   # should fall back to centre
    ]

    cache = _load_cache()
    geo = Nominatim(user_agent="samastipur_tender_tracker_v1")

    print(f"\n{'Location':<30} {'Latitude':>10} {'Longitude':>11}")
    print("-" * 55)
    for loc in test_locations:
        lat, lon = geocode_location(loc, geo, cache)
        print(f"{loc:<30} {lat:>10.4f} {lon:>11.4f}")

    _save_cache(cache)
    print(f"\nCache saved → {CACHE_FILE}")
