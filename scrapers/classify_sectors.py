"""
scrapers/classify_sectors.py — Reclassify 'Other', 'Works', 'General' tenders into specific sectors.

Strategy
────────
1. Department-name rules (highest confidence — e.g. DGVCL → Energy)
2. Title keyword rules (confidence varies by specificity)
3. New sectors introduced: "Environment & Forestry", "Transport & Logistics",
   "Food & Civil Supplies"
4. Tenders that can't be classified are left as 'Other'
"""

import re
import sqlite3
import logging

logger = logging.getLogger(__name__)

# ── Department-name rules (applied before title keywords) ─────────────────────
# Maps a regex on department → sector
DEPT_RULES = [
    # Energy — electricity boards, power corps, generation companies
    (r'(DGVCL|PGVCL|GETCO|GSECL|MSEDCL|TNEB|HVPNL|DHBVN|UHBVN|PSPCL|CESC'
     r'|WBSEDCL|BESCOM|MESCOM|HESCOM|KSEB|APEPDCL|TSSPDCL|DISCOM'
     r'|power\s+corp|electricity\s+board|electric\s+supply'
     r'|Haryana.*Board|HPSEBL|JDVVNL|AVVNL|JVVNL|MVVNL|PVVNL'
     r'|JSEB|JBVNL|UPCL\b|MPPTCL|RRVUN|NTPC|PGCIL|NHPC'
     r'|Vidyut\s+Vitran|Vidyut\s+Utpadan|Vidyut\s+Prasaran'
     r'|Engineers\s+India\s+Lim|MoPNG|petroleum|oil\s+and\s+gas)',
     'Energy'),
    # Water & Sanitation
    (r'\b(PHED?|PHE\b|GWSSB|CMWSSB|BWSSB|KUWS?|jal\s+nigam|jal\s+board'
     r'|water\s+supply|water\s+works|water\s+board|sanitation'
     r'|NWR|irrigation|minor\s+irrigation|CE-BM|LMB\s+Basin)\b',
     'Water & Sanitation'),
    # Education
    (r'\b(samagra\s+shiksha|GCSE|shiksha|education\s+dept|vidyalay'
     r'|school\s+education|higher\s+education|university|college\b'
     r'|ITI\b|polytechnic|DIET\b|SIERT)\b',
     'Education'),
    # Health
    (r'\b(HFW|civil\s+hospital|district\s+hospital|medical\s+college'
     r'|health\s+(and\s+)?family\s+welfare|NHM|AYUSH|dispensary)\b',
     'Health'),
    # Agriculture & allied
    (r'(agriculture|horticulture|fisheri|animal\s+husbandry'
     r'|veterinar|sericulture|dairy|sugarcane|cane\s+dev|FCI\b'
     r'|department\s+of\s+sugar|cooperative.*marketing|dairy\s+fed'
     r'|RCDF\b|NDDB\b|milk\s+fed)',
     'Agriculture'),
    # Rural Development
    (r'(rural\s+dev|panchayati\s+raj|\bZP\b|zila\s+parishad|zilla\s+parishad'
     r'|gram\s+panchayat|block\s+dev|DRDA\b|RDD-CEO)',
     'Rural Development'),
    # Urban Development — broad match on Urban, Local Bodies, Municipal
    (r'(AMC\b|SMC\b|RMC\b|VMC\b|NMC\b|BMC\b|\bDLB\b|DDA\b'
     r'|municipal\s+corp|nagar\s+palika|nagar\s+panchayat|nagar\s+nigam'
     r'|UDA\b|UDH\b|metro\b|smart\s+city|DUDA\b'
     r'|development\s+authority|housing\s+board'
     r'|directorate.*urban|directorate.*local\s+bod|local\s+bod'
     r'|department.*local.*gov|local\s+self\s+gov'
     r'|urban\s+admin|chandigarh\s+admin)',
     'Urban Development'),
    # Social Welfare
    (r'\b(prison|jail|correctional|tribal\s+welfare|TW\s+dept'
     r'|SC.?ST|minority|backward\s+class|social\s+justice|welfare\s+dept)\b',
     'Social Welfare'),
    # Environment & Forestry
    (r'(forest\s+dep|forestry|environment\s+dep|ecology|wildlife'
     r'|pollution\s+control|PCB\b)',
     'Environment & Forestry'),
    # Infrastructure — roads, buildings, RED (Rural Engineering Dept)
    (r'(R\s*&\s*B\b|PWD\b|NHAI\b|roads?\s+and\s+buildings?|public\s+works'
     r'|highway|CGRRDA|Chief.*Engineer.*RED\b)',
     'Infrastructure'),
    # Transport & Logistics
    (r'\b(transport\s+dept|RSWC|warehouse|warehousing\s+corp|logistics'
     r'|STC\b|civil\s+supplies?\s+dept|food\s+corporation)\b',
     'Transport & Logistics'),
    # Food & Civil Supplies
    (r'\b(food\s+and\s+civil\s+supplies?|civil\s+supplies?\s+dept'
     r'|DFO\b|PDS\b|FCI\b|ration|grain|mandi)\b',
     'Food & Civil Supplies'),
    # Digital & IT
    (r'\b(IT\s+dept|NIC\b|information\s+tech|e-?governance|STPI)\b',
     'Digital & IT'),
]

# ── Title keyword rules ────────────────────────────────────────────────────────
# Each entry: (pattern, sector, priority)  — higher priority wins on tie
TITLE_RULES = [
    # Energy
    (r'\b(electricity|electric|solar\s+panel|wind\s+(energy|power)|substation'
     r'|transformer|feeder|HT\s+line|LT\s+line|11\s*kv|33\s*kv|132\s*kv'
     r'|metering|street\s+light|electrif|HVDS|wiring|switchgear'
     r'|power\s+(supply|plant|house)|energy\s+meter|DG\s+set'
     r'|generator|turbine|inverter)\b',
     'Energy', 10),
    # Water & Sanitation
    (r'\b(water\s+supply|drinking\s+water|pipeline|tube.?well|bore.?well'
     r'|hand\s*pump|overhead\s+tank|sump|sewer|sewage|STP\b|WTP\b'
     r'|sanitation|toilet|latrine|ODF|irrigation|canal|distributary'
     r'|check\s+dam|percolation|nala|drain|flood\s+protection|bund'
     r'|water\s+treatment|RO\s+plant|jal\s+jeevan)\b',
     'Water & Sanitation', 10),
    # Health
    (r'\b(hospital|health\s+cent(er|re)|PHC\b|CHC\b|dispensary'
     r'|medicine|drug|pharmaceutical|vaccine|ambulance|ICU\b|OT\b'
     r'|medical\s+(equipment|store)|nursing|malnutrition|SNCU'
     r'|blood\s+bank|X.?ray|dialysis|surgical|clinical|diagnostic)\b',
     'Health', 10),
    # Education
    (r'\b(school|college|university|classroom|hostel|library'
     r'|samagra\s+shiksha|vidyalay|shiksha|gurukul|ITI\b'
     r'|polytechnic|scholarship|mid.?day\s+meal|MDM\b|student'
     r'|examination|skill\s+(dev|training)|vocational\s+training)\b',
     'Education', 10),
    # Agriculture & allied
    (r'\b(agricult|farmer|kisan|farm\s+(pond|road)|crop|seeds?'
     r'|fertilizer|pesticide|horticultur|plantation\s+scheme'
     r'|fisheri|aquaculture|animal\s+husbandry|dairy|veterinar'
     r'|sheep|goat|cattle|poultry|sericulture|cane|sugarcane'
     r'|paddy|wheat|rice\s+mill|agro)\b',
     'Agriculture', 9),
    # Environment & Forestry
    (r'\b(forest|plantation|afforestation|nursery\s+(raising|work)'
     r'|soil\s+conservation|wildlife|ecology|biodiversity|green\s+belt'
     r'|tree\s+plantation|mangrove|wetland|pollution)\b',
     'Environment & Forestry', 9),
    # Digital & IT
    (r'\b(software|application\s+(development|software)|IT\s+(infra|system)'
     r'|computer|server|networking|internet|website|portal|ERP\b|GIS\b'
     r'|CCTV|surveillance|data\s+cent(er|re)|cloud|digitiz|e-?governance'
     r'|biometric|RFID|IoT)\b',
     'Digital & IT', 9),
    # Social Welfare
    (r'\b(prison|jail|correctional\s+service|ration|PDS\b|food\s+grain'
     r'|tribal\s+(hostel|school|welfare)|SC.?ST\s+hostel|old\s+age\s+home'
     r'|shelter\s+(home|shed)|anganwadi|ICDS\b|creche|orphan'
     r'|widow|disability|rehabilitation)\b',
     'Social Welfare', 8),
    # Food & Civil Supplies
    (r'\b(grain\s+(procurement|storage)|wheat\s+procurement|paddy\s+procurement'
     r'|FCI\s+godown|ration\s+shop|PDS\s+depot|civil\s+supply|food\s+storage'
     r'|warehousing|cold\s+storage|handling\s+and\s+transportation'
     r'|bora\s+raik)\b',
     'Food & Civil Supplies', 8),
    # Transport & Logistics
    (r'\b(vehicle\s+hir|bus\s+hir|taxi\s+hir|jeep\s+hir|truck\s+hir'
     r'|transport\s+(service|contract)|logistics|depot|bus\s+stand'
     r'|goods\s+vehicle|freight|cargo|ambulance\s+service'
     r'|EV\s+charging)\b',
     'Transport & Logistics', 8),
    # Rural Development
    (r'\b(gram\s+panchayat|panchayat\s+(bhavan|road|building)'
     r'|rural\s+(road|building|connectivity)|PMGSY\b|MNREGA\b'
     r'|pradhan\s+mantri\s+gram|mukhya\s+mantri\s+gram|anganwadi\s+cent'
     r'|rural\s+development|block\s+level)\b',
     'Rural Development', 7),
    # Urban Development
    (r'\b(smart\s+city|ULB\b|municipal\s+(road|drain|market|building)'
     r'|ward\s+(no|level|work)|nagar\s+(palika|nigam|panchayat)'
     r'|town\s+planning|beautification|pedestrian|footpath\s+tile'
     r'|street\s+(furniture|light\s+LED)|park\s+(development|maintenance)'
     r'|solid\s+waste|SWM\b|dust\s+bin)\b',
     'Urban Development', 7),
    # Infrastructure (broad catch-all for construction)
    (r'\b(construction|renovation|repair\s+and|civil\s+work|RCC\b'
     r'|bituminous|road\s+work|bridge|culvert|building\s+work'
     r'|boundary\s+wall|retaining\s+wall|approach\s+road'
     r'|link\s+road|state\s+highway|national\s+highway|flyover'
     r'|underpass|sampark\s+marg|godown\s+construction|govt\s+building)\b',
     'Infrastructure', 5),
    # MSME / Industrial
    (r'\b(MSME\b|CSIDC\b|small\s+(enterprise|industry)|industrial\s+(park|estate)'
     r'|manufacturing\s+unit|cluster\s+dev)\b',
     'MSME', 9),
    # Scheme-name shortcuts common in CHEPS/CG tenders
    (r'\b(PM\s*JANMAN|MMGGPY|PMAY|PMGSY\b|sampark\s+marg|sadak\s+yojana'
     r'|CGRRDA|gram\s+sadak)\b',
     'Infrastructure', 7),
    (r'\b(dava\s+apatti|aushadhi|medicine\s+supply|drug\s+supply)\b',
     'Health', 9),
    (r'\b(bijli|vidyut|power\s+line|electric\s+pole|HT\s+pole|DT\s+point)\b',
     'Energy', 9),
    (r'\b(nal\s+jal|jal\s+jeevan|pani\s+tank|paani|borewell|tubwell)\b',
     'Water & Sanitation', 9),
    (r'\b(anganwadi\s+cent|poshan|poshahar|ICDS\s+centre)\b',
     'Social Welfare', 9),
]

# Pre-compile
_DEPT_COMPILED = [(re.compile(p, re.IGNORECASE), s) for p, s in DEPT_RULES]
_TITLE_COMPILED = [(re.compile(p, re.IGNORECASE), s, pri) for p, s, pri in TITLE_RULES]


def _classify_one(title: str, department: str):
    """Return new sector or None if not confident."""
    title = title or ''
    dept = department or ''

    # 1. Department rules (highest confidence)
    for pat, sector in _DEPT_COMPILED:
        if pat.search(dept):
            return sector

    # 2. Title rules — collect all matches, take highest priority
    matches: list[tuple[int, str]] = []
    for pat, sector, pri in _TITLE_COMPILED:
        if pat.search(title):
            matches.append((pri, sector))

    if matches:
        matches.sort(reverse=True)
        return matches[0][1]

    return None


def classify_unclassified(conn: sqlite3.Connection) -> dict:
    """
    Reclassify tenders in 'Other', 'Works', 'General' sectors.
    Returns stats dict.
    """
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT tender_id, title, department, sector FROM tenders "
        "WHERE sector IN ('Other', 'Works', 'General')"
    ).fetchall()

    logger.info("[CLASSIFY] %d tenders to reclassify", len(rows))

    from collections import Counter
    moved: Counter = Counter()
    stayed = 0
    updates: list[tuple[str, str]] = []

    for tid, title, dept, old_sector in rows:
        new_sector = _classify_one(title, dept)
        if new_sector and new_sector != old_sector:
            updates.append((new_sector, tid))
            moved[f"{old_sector} → {new_sector}"] += 1
        else:
            stayed += 1

    # Batch update
    cur.executemany("UPDATE tenders SET sector=? WHERE tender_id=?", updates)
    conn.commit()

    logger.info("[CLASSIFY] Updated %d tenders, %d remain unclassified", len(updates), stayed)
    return {"updated": len(updates), "stayed": stayed, "breakdown": dict(moved)}
