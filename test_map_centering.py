"""
test_map_centering.py — DivyaDrishti map viewport alignment tests.

Run:  python3 -m pytest test_map_centering.py -v
  or: python3 test_map_centering.py

What is tested
--------------
1. get_view_config returns correct centre for every known district
   (case-insensitive: "AGRA", "agra", "Agra" all must map to ≈27.18°N 78.01°E).
2. State-level centre is sane (within the state's bounding box).
3. National fallback stays over mainland India (20–25°N, 78–85°E).
4. All UP districts in DISTRICT_COORDINATES have realistic coordinates
   (must NOT be the old Samastipur fallback 25.86°N 85.78°E).
5. _district_coords finds districts regardless of capitalisation.
"""

import math
import sys
from pathlib import Path

# ── make sure project root is on the path ────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import pytest

from pipeline import (
    DISTRICT_COORDINATES,
    STATE_CENTERS,
    _district_coords,
    get_view_config,
)

# ── tolerance: centre must be within this many km of the expected coordinate ──
CENTRE_TOL_KM = 30   # map centre must be within 30 km of the real district
STATE_TOL_KM  = 200  # state centre can be up to 200 km from the real city


def _haversine(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def _empty_df(lat=0.0, lon=0.0) -> pd.DataFrame:
    """Minimal DataFrame with one row so get_view_config has data to fall back to."""
    return pd.DataFrame(
        [{"latitude": lat, "longitude": lon, "allocated_amount": 1.0}]
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. District-level centering — key districts across states
# ─────────────────────────────────────────────────────────────────────────────

DISTRICT_CASES = [
    # (state,              district_in_db,    expected_lat, expected_lon,  label)
    ("Uttar Pradesh",  "AGRA",           27.1767,  78.0081,  "Agra uppercase"),
    ("Uttar Pradesh",  "agra",           27.1767,  78.0081,  "Agra lowercase"),
    ("Uttar Pradesh",  "Agra",           27.1767,  78.0081,  "Agra title-case"),
    ("Uttar Pradesh",  "ALIGARH",        27.8974,  78.0880,  "Aligarh uppercase"),
    ("Uttar Pradesh",  "VARANASI",       25.3176,  82.9739,  "Varanasi uppercase"),
    ("Uttar Pradesh",  "GORAKHPUR",      26.7606,  83.3732,  "Gorakhpur uppercase"),
    ("Uttar Pradesh",  "PRAYAGRAJ",      25.4358,  81.8463,  "Prayagraj uppercase"),
    ("Uttar Pradesh",  "LUCKNOW",        26.8467,  80.9462,  "Lucknow uppercase"),
    ("Uttar Pradesh",  "MEERUT",         28.9845,  77.7064,  "Meerut uppercase"),
    ("Uttar Pradesh",  "BAREILLY",       28.3670,  79.4304,  "Bareilly uppercase"),
    ("Uttar Pradesh",  "MATHURA",        27.4924,  77.6737,  "Mathura uppercase"),
    ("Bihar",          "Samastipur",     25.8624,  85.7810,  "Samastipur exact"),
    ("Bihar",          "SAMASTIPUR",     25.8624,  85.7810,  "Samastipur uppercase"),
    ("Bihar",          "Patna",          25.5941,  85.1376,  "Patna exact"),
    ("Bihar",          "PATNA",          25.5941,  85.1376,  "Patna uppercase"),
    ("Maharashtra",    "Mumbai",         19.0760,  72.8777,  "Mumbai exact"),
    ("Maharashtra",    "MUMBAI",         19.0760,  72.8777,  "Mumbai uppercase"),
    ("Karnataka",      "Bangalore Urban",12.9716,  77.5946,  "Bangalore exact"),
]


@pytest.mark.parametrize("state,district,exp_lat,exp_lon,label", DISTRICT_CASES)
def test_district_centre(state, district, exp_lat, exp_lon, label):
    """Map centre must be within CENTRE_TOL_KM of the real district."""
    df = _empty_df(exp_lat, exp_lon)
    cfg = get_view_config(df, state=state, district=district)
    dist = _haversine(cfg["lat"], cfg["lon"], exp_lat, exp_lon)
    assert dist <= CENTRE_TOL_KM, (
        f"{label}: centre ({cfg['lat']:.4f}, {cfg['lon']:.4f}) is "
        f"{dist:.1f} km from expected ({exp_lat}, {exp_lon})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. _district_coords — case-insensitive lookup
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("state,district", [
    ("Uttar Pradesh", "AGRA"),
    ("Uttar Pradesh", "agra"),
    ("Uttar Pradesh", "Agra"),
    ("Uttar Pradesh", "ALIGARH"),
    ("Uttar Pradesh", "Aligarh"),
    ("Bihar",         "SAMASTIPUR"),
    ("Bihar",         "samastipur"),
    ("Maharashtra",   "MUMBAI"),
])
def test_district_coords_case_insensitive(state, district):
    result = _district_coords(state, district)
    assert result is not None, f"_district_coords({state!r}, {district!r}) returned None"
    assert "lat" in result and "lon" in result


def test_district_coords_unknown_returns_none():
    assert _district_coords("Uttar Pradesh", "NonExistentDistrict") is None
    assert _district_coords("UnknownState", "Agra") is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. No UP district uses Samastipur as its coordinate
# ─────────────────────────────────────────────────────────────────────────────

SAMASTIPUR_LAT = 25.8624
SAMASTIPUR_LON = 85.7810

def test_up_districts_not_at_samastipur():
    """Every UP district coordinate must differ from the old Samastipur fallback."""
    up_districts = DISTRICT_COORDINATES.get("Uttar Pradesh", {})
    for dist, c in up_districts.items():
        dist_km = _haversine(c["lat"], c["lon"], SAMASTIPUR_LAT, SAMASTIPUR_LON)
        assert dist_km > 50, (
            f"UP district {dist!r} coordinate ({c['lat']}, {c['lon']}) "
            f"is only {dist_km:.1f} km from Samastipur — looks like a stale fallback"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. State-level centering
# ─────────────────────────────────────────────────────────────────────────────

STATE_CASES = [
    ("Uttar Pradesh",   26.85, 80.91),
    ("Bihar",           25.09, 85.31),
    ("Maharashtra",     19.75, 75.71),
    ("Karnataka",       15.31, 75.71),
    ("Delhi",           28.66, 77.21),
]

@pytest.mark.parametrize("state,exp_lat,exp_lon", STATE_CASES)
def test_state_centre(state, exp_lat, exp_lon):
    df = _empty_df(exp_lat, exp_lon)
    cfg = get_view_config(df, state=state)
    dist = _haversine(cfg["lat"], cfg["lon"], exp_lat, exp_lon)
    assert dist <= STATE_TOL_KM, (
        f"{state}: centre ({cfg['lat']:.4f}, {cfg['lon']:.4f}) is "
        f"{dist:.1f} km from expected ({exp_lat}, {exp_lon})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. National fallback stays over India
# ─────────────────────────────────────────────────────────────────────────────

def test_national_fallback_over_india():
    cfg = get_view_config(_empty_df(22.5, 82.5))
    assert 8 <= cfg["lat"] <= 36,  f"lat {cfg['lat']} outside India bounds"
    assert 68 <= cfg["lon"] <= 97, f"lon {cfg['lon']} outside India bounds"
    assert cfg["zoom"] <= 6,       f"national zoom {cfg['zoom']} too tight"


# ─────────────────────────────────────────────────────────────────────────────
# 6. District zoom is tighter than state zoom
# ─────────────────────────────────────────────────────────────────────────────

def test_district_zoom_tighter_than_state():
    df = _empty_df(27.1767, 78.0081)
    district_cfg = get_view_config(df, state="Uttar Pradesh", district="Agra")
    state_cfg    = get_view_config(df, state="Uttar Pradesh")
    assert district_cfg["zoom"] >= state_cfg["zoom"], (
        f"District zoom {district_cfg['zoom']} should be ≥ state zoom {state_cfg['zoom']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Standalone runner (no pytest required)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = failed = 0

    def run(name, fn, *args):
        global passed, failed
        try:
            fn(*args)
            print(f"  ✅ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {name}\n     {e}")
            failed += 1

    print("\n── District centering ──────────────────────────────────")
    for state, district, lat, lon, label in DISTRICT_CASES:
        run(label, test_district_centre, state, district, lat, lon, label)

    print("\n── Case-insensitive lookup ─────────────────────────────")
    for state, district in [
        ("Uttar Pradesh","AGRA"), ("Uttar Pradesh","agra"),
        ("Bihar","SAMASTIPUR"), ("Maharashtra","MUMBAI"),
    ]:
        run(f"_district_coords({district})", test_district_coords_case_insensitive, state, district)
    run("unknown returns None", test_district_coords_unknown_returns_none)

    print("\n── No UP district uses Samastipur fallback ─────────────")
    run("UP district coords", test_up_districts_not_at_samastipur)

    print("\n── State centering ─────────────────────────────────────")
    for state, lat, lon in STATE_CASES:
        run(state, test_state_centre, state, lat, lon)

    print("\n── National fallback ───────────────────────────────────")
    run("national over India", test_national_fallback_over_india)

    print("\n── Zoom levels ─────────────────────────────────────────")
    run("district zoom tighter", test_district_zoom_tighter_than_state)

    print(f"\n{'─'*50}")
    print(f"  {passed} passed  {failed} failed")
    print(f"{'─'*50}\n")
    sys.exit(0 if failed == 0 else 1)
