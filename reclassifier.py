"""
reclassifier.py — Eliminate 'Other' / 'Unknown' from sector/state/district.

Reads `title` + `department` text and applies multi-strategy classification:

  1. Sector  → keyword scoring across 12 sectors + department-name regex
  2. State   → STATES_DATA lookup + abbreviation match (UP, MP, J&K, etc.)
  3. District → state-bounded district lookup, or any-state global match
  4. Block   → STATES_DATA[state][district] block list lookup

Modes:
  • reclassify_dataframe(df)  — in-memory, fast; mutates DataFrame
  • reclassify_db(db_path)    — writes back to tenders.db
"""

import re
import sqlite3
import logging
from typing import Optional, Tuple

from pipeline import STATES_DATA

logger = logging.getLogger("reclassifier")


# ── Sector keyword catalogue (heavy on real Indian gov vocabulary) ────────

SECTOR_KEYWORDS = {
    "Infrastructure": [
        # Specific transport / civil-engineering signals only — generic action
        # verbs like 'construction of' are excluded because every sector has them.
        "road", "highway", "expressway", "bypass", "flyover", "bridge", "rob ",
        "underpass", "tunnel", "carriageway", "bituminous", "metalled",
        "pavement", "asphalt", "nh-", "sh-", "nhai", "bro ",
        "transmission line", "substation", "railway track", "metro corridor",
        "airport runway", "port", "terminal", "depot",
    ],
    "Health": [
        "hospital", "phc", "chc", "dispensary", "clinic", "medical college",
        "aiims", "trauma centre", "trauma center", "diagnostic", "pathology",
        "x-ray", "mri", "ct scan", "icu ", " ward", "opd ", "ambulance",
        "vaccine", "immunisation", "nhm ", "ayushman", "health centre",
        "medicine", "pharmaceutical", "surgical equipment",
    ],
    "Education": [
        "school", "college", "university", "vidyalaya", "navodaya",
        "kendriya", " iit ", " nit ", " iim ", "polytechnic", " iti ",
        "samagra shiksha", "sarva shiksha", " diet ",
        "scholarship", "library", " lab ", "classroom",
        "textbook", "uniform", "midday meal",
    ],
    "Agriculture": [
        "agriculture", "farmer", "farm ", "crop", " soil", "fertili",
        "seed ", "irrigation", "tube well", "sprinkler", "drip",
        " icar ", " kvk ", " fci ", "godown", "mandi", " apmc ",
        "horticulture", "fishery", "dairy", "livestock", "veterinary",
        "pm-kisan", "pm-kusum", "fasal", "kisan",
    ],
    "MSME": [
        " msme ", "small industry", "khadi", "village industries", "handicraft",
        "handloom", "weaver", "artisan", "tool room",
        "incubation", "startup", " sidbi ", " nsic ", "common facility",
    ],
    "Energy": [
        "solar", "wind energy", "renewable", " ntpc ", " seci ", "power grid",
        "discom", "biomass", "hydro", "thermal power",
        "electrification", "smart meter", "street light", " led ",
        " kv ", " mw ",
    ],
    "Water & Sanitation": [
        "water supply", "drinking water", "jal jeevan", " jjm ", "water treatment",
        " stp ", " etp ", "sewage", "sanitation", "swachh bharat", " sbm ",
        "toilet", " odf ", "drain", "stormwater", "borewell",
        "pipeline", "tap connection", "namami gange",
    ],
    "Urban Development": [
        "smart city", " amrut ", "pmay-u", "pmay urban", "municipal",
        "urban renewal", " ulb ", "affordable housing", "city bus", " brt ",
        "parking", "footpath",
    ],
    "Rural Development": [
        " pmgsy", "mnrega", "mgnrega", "pmay-g", "pmay gramin",
        " rural", "gram panchayat", " drda ", "rural road",
        "ddu-gky", " nrlm ", " shg ",
    ],
    "Minority Affairs": [
        "minority", " waqf", " msdp ", "madrasa", " haj ",
        " urdu ", "post-matric",
    ],
    "Social Welfare": [
        "social justice", "tribal", " sc/st", " obc ",
        "women & child", "anganwadi", " icds ",
        "old age", "pension", "disability", "divyangjan",
        "creche", "shelter home",
    ],
    "Digital & IT": [
        "bharatnet", " ofc ", "optical fibre", "fiber optic", "broadband",
        " csc ", "common service centre", "data centre", "data center",
        "e-governance", " meity ", " nic ", " cdac ",
        "cyber", " cctv ", "surveillance", "computerization",
    ],
}

# Department-name regex → sector hint
_DEPT_PATTERNS = [
    (r"\b(health|medical|hospital|nhm|aiims|ayush|pmjay)", "Health"),
    (r"\b(education|school|university|ugc|cbse|navodaya|samagra)", "Education"),
    (r"\b(agricult|farmer|nabard|icar|fci|horticult|kisan)", "Agriculture"),
    (r"\b(msme|small industr|khadi|nsic|sidbi|handicraft|handloom)", "MSME"),
    (r"\b(energy|power|electric|ntpc|seci|discom|new & renewable|mnre)", "Energy"),
    (r"\b(jal jeevan|swachh bharat|namami gange|phed|water resources|jal nigam|sanitation)", "Water & Sanitation"),
    (r"\b(smart city|amrut|pmay.urban|municipal corp|metro rail|urban dev)", "Urban Development"),
    (r"\b(pmgsy|mnrega|pmay.gramin|rural dev|panchayat|drda)", "Rural Development"),
    (r"\b(minority|waqf|msdp|haj committee)", "Minority Affairs"),
    (r"\b(social justice|tribal|women.child|icds|sc/st development)", "Social Welfare"),
    (r"\b(meity|bharatnet|csc|nic infra|cdac|electronics.{0,5}it)", "Digital & IT"),
    (r"\b(highway|nhai|cpwd|airport|railway|metro|bro|public works|pwd|state pwd)", "Infrastructure"),
]


# ── State abbreviations / shorthand ──────────────────────────────────────

_STATE_ABBREV = {
    "u.p.": "Uttar Pradesh",  " up ": "Uttar Pradesh",
    "m.p.": "Madhya Pradesh", " mp ": "Madhya Pradesh",
    "a.p.": "Andhra Pradesh", " ap ": "Andhra Pradesh",
    "j&k": "Jammu & Kashmir", " jk ": "Jammu & Kashmir",
    " tn ": "Tamil Nadu",     " wb ": "West Bengal",
    " hp ": "Himachal Pradesh"," uk ": "Uttarakhand",
    "tamilnadu": "Tamil Nadu", "westbengal": "West Bengal",
    "telengana": "Telangana",  "kerela": "Kerala",
}

# Generic / placeholder state values that should be replaced
_PLACEHOLDER_STATES = {"Unknown", "Central (GeM)", "", None, "nan", "Government of India"}


# ── Classifiers ───────────────────────────────────────────────────────────

def classify_sector_v2(title: str, department: str) -> str:
    """Returns best-fit sector. Never 'Other' / 'Unknown' — falls back to 'General'."""
    text = ((title or "") + " " + (department or "")).lower()

    # 1. Score by keyword hits in title+dept
    scores = {}
    for sector, keywords in SECTOR_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score:
            scores[sector] = score
    if scores:
        return max(scores.items(), key=lambda x: x[1])[0]

    # 2. Department regex fallback
    dept_l = (department or "").lower()
    for pattern, sector in _DEPT_PATTERNS:
        if re.search(pattern, dept_l):
            return sector

    return "General"


def extract_state(title: str, department: str) -> Optional[str]:
    text = ((title or "") + " " + (department or "")).lower()
    # 1. Direct state name match
    for state in STATES_DATA:
        if state.lower() in text:
            return state
    # 2. State abbreviation
    for abbr, st in _STATE_ABBREV.items():
        if abbr in text:
            return st
    # 3. Reverse-infer state from any district name mentioned in text
    for st, dists in STATES_DATA.items():
        for d in dists:
            if d.lower() in text:
                return st
    return None


def extract_district(title: str, department: str, state: Optional[str]) -> Optional[str]:
    text = ((title or "") + " " + (department or "")).lower()
    if state and state in STATES_DATA:
        for d in STATES_DATA[state]:
            if d.lower() in text:
                return d
        return None
    # State unknown — scan all districts globally
    for st, dists in STATES_DATA.items():
        for d in dists:
            if d.lower() in text:
                return d
    return None


def extract_block(title: str, department: str,
                  state: Optional[str], district: Optional[str]) -> Optional[str]:
    if not state or not district:
        return None
    if state not in STATES_DATA or district not in STATES_DATA[state]:
        return None
    text = ((title or "") + " " + (department or "")).lower()
    for b in STATES_DATA[state][district]:
        if b.lower() in text:
            return b
    return None


# ── Bulk dataframe update ─────────────────────────────────────────────────

def reclassify_dataframe(df) -> dict:
    """
    In-memory pass: replace 'Other' / 'Unknown' / 'Central (GeM)' with
    text-derived values. Mutates df in place. Returns count summary.
    """
    import pandas as pd

    if df is None or df.empty:
        return {"sector": 0, "state": 0, "district": 0, "block": 0}

    counts = {"sector": 0, "state": 0, "district": 0, "block": 0}

    for col in ("sector", "state", "district", "block"):
        if col in df.columns and isinstance(df[col].dtype, pd.CategoricalDtype):
            df[col] = df[col].astype(object)

    for idx in df.index:
        title = str(df.at[idx, "title"]) if "title" in df.columns and pd.notna(df.at[idx, "title"]) else ""
        dept  = str(df.at[idx, "department"]) if "department" in df.columns and pd.notna(df.at[idx, "department"]) else ""

        # Sector
        if "sector" in df.columns:
            cur = str(df.at[idx, "sector"]) if pd.notna(df.at[idx, "sector"]) else ""
            if cur in ("Other", "General", "Unknown", "nan", ""):
                new_sector = classify_sector_v2(title, dept)
                if new_sector != cur:
                    df.at[idx, "sector"] = new_sector
                    counts["sector"] += 1

        # State
        if "state" in df.columns:
            cur_state = str(df.at[idx, "state"]) if pd.notna(df.at[idx, "state"]) else ""
            if cur_state in _PLACEHOLDER_STATES:
                new_state = extract_state(title, dept)
                if new_state:
                    df.at[idx, "state"] = new_state
                    counts["state"] += 1
                    # Cascading: re-derive district + block
                    new_d = extract_district(title, dept, new_state)
                    if new_d:
                        df.at[idx, "district"] = new_d
                        counts["district"] += 1
                        nb = extract_block(title, dept, new_state, new_d)
                        if nb:
                            df.at[idx, "block"] = nb
                            counts["block"] += 1
                    continue

        # District (state already known)
        if "district" in df.columns:
            cur_d = str(df.at[idx, "district"]) if pd.notna(df.at[idx, "district"]) else ""
            if cur_d in ("Unknown", "nan", ""):
                cs = str(df.at[idx, "state"]) if pd.notna(df.at[idx, "state"]) else None
                new_d = extract_district(title, dept, cs if cs in STATES_DATA else None)
                if new_d:
                    df.at[idx, "district"] = new_d
                    counts["district"] += 1
                    nb = extract_block(title, dept, cs, new_d)
                    if nb:
                        df.at[idx, "block"] = nb
                        counts["block"] += 1

    if any(counts.values()):
        logger.info("Reclassified — %s", counts)
    return counts


# ── Persistent SQLite update ──────────────────────────────────────────────

def reclassify_db(db_path: str) -> dict:
    """Apply reclassification and write back to tenders.db."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT tender_id, title, department, sector, state, district, block FROM tenders"
    ).fetchall()

    updates = []
    counts = {"sector": 0, "state": 0, "district": 0, "block": 0}

    for r in rows:
        title = r["title"] or ""
        dept  = r["department"] or ""
        sector = r["sector"] or ""
        state = r["state"] or ""
        district = r["district"] or ""
        block = r["block"] or ""

        new_sector, new_state, new_district, new_block = sector, state, district, block

        if sector in ("Other", "General", "Unknown", "", None):
            new_sector = classify_sector_v2(title, dept)
        if state in _PLACEHOLDER_STATES:
            ns = extract_state(title, dept)
            if ns:
                new_state = ns
                nd = extract_district(title, dept, ns)
                if nd:
                    new_district = nd
                    nb = extract_block(title, dept, ns, nd)
                    if nb:
                        new_block = nb
        if new_district in ("Unknown", "", None):
            nd = extract_district(title, dept, new_state if new_state in STATES_DATA else None)
            if nd:
                new_district = nd
                nb = extract_block(title, dept, new_state, nd)
                if nb:
                    new_block = nb

        changed = (new_sector != sector or new_state != state
                   or new_district != district or new_block != block)
        if changed:
            if new_sector != sector:     counts["sector"] += 1
            if new_state != state:       counts["state"] += 1
            if new_district != district: counts["district"] += 1
            if new_block != block:       counts["block"] += 1
            updates.append((new_sector, new_state, new_district, new_block, r["tender_id"]))

    if updates:
        conn.executemany(
            "UPDATE tenders SET sector=?, state=?, district=?, block=? WHERE tender_id=?",
            updates,
        )
        conn.commit()

    conn.close()
    counts["total_rows_updated"] = len(updates)
    logger.info("DB reclassified — %s", counts)
    return counts


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description="Reclassify sector/state/district from title text")
    parser.add_argument("--db", default=str(Path(__file__).parent / "tenders.db"))
    args = parser.parse_args()
    res = reclassify_db(args.db)
    print(f"\n✅ DB reclassified — {res}\n")
