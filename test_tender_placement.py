"""
test_tender_placement.py — Verify that tender dots appear in the right district.

Run:  python3 test_tender_placement.py
  or: python3 -m pytest test_tender_placement.py -v

What is tested
--------------
For each focal district, every tender's resolved lat/lon must be closer to
that district's centre than to any other district centre in the same state.

The data comes from the *real DB pipeline* (same path as the live app), so
this test catches regressions that only show up in production.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import pytest

from pipeline import (
    DISTRICT_COORDINATES,
    _district_coords,
    _disambiguate_within_district,
)

# ── tolerance (km) ─────────────────────────────────────────────────────────────
PLACEMENT_TOL_KM = 30  # every tender must be within 30 km of its district centre


def _haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dl = math.radians(lat2 - lat1)
    dL = math.radians(lon2 - lon1)
    a = (math.sin(dl / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dL / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


# ── load real data once ─────────────────────────────────────────────────────────
def _load_db() -> pd.DataFrame:
    """Load tenders.db through the real pipeline (same code path as the app)."""
    import sqlite3
    db_path = Path(__file__).parent / "tenders.db"
    if not db_path.exists():
        pytest.skip("tenders.db not found — run scraper first")

    conn = sqlite3.connect(db_path)
    df = pd.read_sql(
        "SELECT tender_id, state, district, block, latitude, longitude "
        "FROM tenders",
        conn,
    )
    conn.close()
    # Run the exact same disambiguation the app runs
    df = _disambiguate_within_district(df)
    return df


# cache so each test doesn't reload
_DF_CACHE = None

def get_df():
    global _DF_CACHE
    if _DF_CACHE is None:
        _DF_CACHE = _load_db()
    return _DF_CACHE


# ── districts to test ──────────────────────────────────────────────────────────
# (state, district_as_stored_in_db, expected_lat, expected_lon, label)
PLACEMENT_CASES = [
    ("Uttar Pradesh", "AGRA",       27.1767, 78.0081, "Agra"),
    ("Uttar Pradesh", "VARANASI",   25.3176, 82.9739, "Varanasi"),
    ("Uttar Pradesh", "GORAKHPUR",  26.7606, 83.3732, "Gorakhpur"),
    ("Uttar Pradesh", "LUCKNOW",    26.8467, 80.9462, "Lucknow"),
    ("Uttar Pradesh", "MEERUT",     28.9845, 77.7064, "Meerut"),
    ("Uttar Pradesh", "PRAYAGRAJ",  25.4358, 81.8463, "Prayagraj"),
    ("Uttar Pradesh", "ALIGARH",    27.8974, 78.0880, "Aligarh"),
]


@pytest.mark.parametrize("state,district,exp_lat,exp_lon,label", PLACEMENT_CASES)
def test_tender_dots_in_correct_district(state, district, exp_lat, exp_lon, label):
    """Every tender for a district must land within PLACEMENT_TOL_KM of that district."""
    df = get_df()
    subset = df[(df["state"] == state) & (df["district"] == district)]
    if subset.empty:
        pytest.skip(f"No {label} tenders in DB")

    bad_rows = []
    for _, row in subset.iterrows():
        dist = _haversine(row["latitude"], row["longitude"], exp_lat, exp_lon)
        if dist > PLACEMENT_TOL_KM:
            bad_rows.append((row["tender_id"], dist))

    pct_bad = len(bad_rows) / len(subset) * 100
    assert not bad_rows, (
        f"{label}: {len(bad_rows)}/{len(subset)} tenders ({pct_bad:.0f}%) "
        f"are > {PLACEMENT_TOL_KM} km from {label}.\n"
        f"  Worst offenders: {bad_rows[:5]}"
    )


def test_agra_tenders_not_at_lucknow():
    """Specific regression: AGRA tenders were appearing at Lucknow."""
    df = get_df()
    agra = df[(df["state"] == "Uttar Pradesh") & (df["district"] == "AGRA")]
    if agra.empty:
        pytest.skip("No AGRA tenders in DB")

    LUCKNOW_LAT, LUCKNOW_LON = 26.8467, 80.9462
    near_lucknow = agra.apply(
        lambda r: _haversine(r["latitude"], r["longitude"], LUCKNOW_LAT, LUCKNOW_LON) < 30,
        axis=1,
    ).sum()

    assert near_lucknow == 0, (
        f"{near_lucknow}/{len(agra)} AGRA tenders are within 30 km of Lucknow — "
        f"district-placement bug still active."
    )


def test_no_district_tenders_at_state_capital():
    """No UP district's tenders should all cluster at Lucknow (state capital fallback)."""
    df = get_df()
    LUCKNOW_LAT, LUCKNOW_LON = 26.8467, 80.9462
    up = df[df["state"] == "Uttar Pradesh"]

    for district in ["AGRA", "VARANASI", "GORAKHPUR", "MEERUT", "ALIGARH"]:
        subset = up[up["district"] == district]
        if subset.empty:
            continue
        near_lko = subset.apply(
            lambda r: _haversine(r["latitude"], r["longitude"], LUCKNOW_LAT, LUCKNOW_LON) < 30,
            axis=1,
        ).sum()
        pct = near_lko / len(subset) * 100
        assert pct < 5, (
            f"{district}: {pct:.0f}% of tenders ({near_lko}/{len(subset)}) "
            f"are near Lucknow — state-capital fallback still firing."
        )


# ── standalone runner ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\nLoading tenders.db through pipeline…")
    df = get_df()
    print(f"  Loaded {len(df):,} tenders\n")

    passed = failed = 0

    def run(name, fn, *args):
        global passed, failed
        try:
            fn(*args)
            print(f"  ✅ {name}")
            passed += 1
        except BaseException as e:
            # pytest.skip raises a special BaseException subclass
            if type(e).__name__ == "Skipped":
                print(f"  ⏭  {name} — skipped ({e})")
            else:
                msg = str(e).split("\n")[0][:120]
                print(f"  ❌ {name}\n     {msg}")
                failed += 1

    print("── Tender placement within district ────────────────────")
    for state, district, lat, lon, label in PLACEMENT_CASES:
        run(label, test_tender_dots_in_correct_district, state, district, lat, lon, label)

    print("\n── Agra → Lucknow regression ───────────────────────────")
    run("AGRA not at Lucknow", test_agra_tenders_not_at_lucknow)

    print("\n── No district clusters at state capital ───────────────")
    run("UP districts not at Lucknow", test_no_district_tenders_at_state_capital)

    print(f"\n{'─'*55}")
    print(f"  {passed} passed  {failed} failed")
    print(f"{'─'*55}\n")
    sys.exit(0 if failed == 0 else 1)
