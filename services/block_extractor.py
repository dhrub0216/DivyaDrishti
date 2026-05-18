"""
services/block_extractor.py

Regex extraction of administrative Block names from tender titles.
Indian administrative hierarchy: State → District → Block (Taluka/Tehsil) → Village.
This module distinguishes admin blocks from structural "blocks" (toilet, paver, CC, etc.).
"""
import re
import sqlite3
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Physical-block exclusion patterns
# ---------------------------------------------------------------------------
_PHYSICAL_RE = re.compile(
    r'\b(?:'
    r'toilet\s+blocks?'
    r'|pav(?:er|ing)\s+blocks?'
    r'|(?:c\.?c\.?|r\.?c\.?c\.?|concrete|granite|stone|cinder|fly.?ash'
    r'|hollow|solid|masonry|rubble)\s+blocks?'
    r'|interlocking\s+(?:tiles?\s+)?blocks?'
    r'|dimensional\s+\w+\s+blocks?'
    r'|block\s+road\b'
    r'|road\s+block'
    r'|block\s+wall\b'
    r'|block\s+laying\b'
    r'|block\s+type\b'
    r'|blockage'
    r'|block\s*/\s*cent(?:er|re)'
    r'|block\s*[-–]\s*0*\d{1,2}(?:\b|$)'
    r'|[a-e]\s*-\s*block\b'
    r'|blocks?\s+no\.?\s*\d'
    r'|all\s+blocks?\b'
    r'|various\s+blocks?\b'
    r')',
    re.IGNORECASE,
)

# Words that are never administrative block names
_NON_PLACE = frozenset({
    # prepositions / conjunctions
    'the', 'and', 'for', 'with', 'under', 'in', 'at', 'to', 'from', 'of',
    'by', 'on', 'into', 'about', 'also', 'both',
    # geographic terms (not block-specific)
    'road', 'wall', 'type', 'level', 'floor', 'area', 'main', 'new', 'old',
    'all', 'total', 'district', 'distt', 'village', 'gram', 'panchayat',
    'nagar', 'tehsil', 'taluk', 'taluka', 'mandal', 'sub',
    # action / process
    'construction', 'repair', 'development', 'scheme', 'project', 'supply',
    'service', 'installation', 'nirman', 'work', 'works',
    # facilities / building types
    'centre', 'center', 'office', 'building', 'hall', 'room', 'hospital',
    'school', 'college', 'hostel', 'dormitory', 'barrack', 'complex',
    'compound', 'campus', 'market', 'shop', 'store', 'warehouse', 'depot',
    'shed', 'tower', 'station', 'church', 'temple', 'mosque', 'shrine',
    # structural
    'roof', 'ceiling', 'door', 'window', 'gate', 'arch', 'pillar',
    # general
    'various', 'other', 'general', 'special', 'phase', 'part', 'no', 'nos',
    'group', 'division', 'section', 'unit', 'camp', 'base', 'site', 'zone',
    'ward', 'block', 'lot', 'number', 'div', 'loc', 'system', 'tender',
    'tenders', 'this', 'that', 'these', 'those', 'each', 'even', 'here',
    # scheme names
    'pmgsy', 'mgnregs', 'mgnrega', 'jjm',
    # short / ambiguous
    'dev', 'nos', 'pyt', 'gp', 'vpo',
})

# Names that mean a physical material, not a place — used when the name
# appears BEFORE "block" (e.g., "toilet block", "stone block")
_PHYSICAL_NOUNS = frozenset({
    'toilet', 'paver', 'paving', 'concrete', 'granite', 'stone', 'masonry',
    'hollow', 'solid', 'cinder', 'rubble', 'breeze', 'fly', 'partition',
    'building', 'hospital', 'guard', 'security', 'mess', 'ors', 'residential',
})

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# Pattern A: "block" (word boundary) + optional separators + name
# Covers: "Block Bastanar", "Block- Darbha", "Block --Bastar", "BLOCK SUNDERPAHARI"
_PAT_A = re.compile(
    r'\bblock\b\s*[-–—]*\s*([A-Za-z][a-zA-Z]{2,})',
    re.IGNORECASE,
)

# Pattern B: "Block" (capital-B, case-sensitive) immediately followed by a capital letter
# Covers: "BlockChhuikhadan" (data-quality concatenation, no space)
_PAT_B = re.compile(r'\bBlock([A-Z][a-zA-Z]{2,})')

# Pattern C: single-word name followed by "block" (not a building-type suffix)
# Covers: "Jhanjharpur Block", "Bissamcuttack Block of Rayagada"
_PAT_C = re.compile(
    r'\b([A-Z][a-z]{2,})\s+block\b'
    r'(?!\s*(?:no\.?|\d|road\b|wall\b|type\b|level\b|work\b|laying\b))',
    re.IGNORECASE,
)

# Pattern D: sub-district units used in other states (equivalent to Block)
# Covers: "Tehsil Nichlaul" (UP), "Taluk Mangalore" (KA), "Mandal Shadnagar" (TS/AP)
_PAT_D = re.compile(
    r'\b(?:tehsil|taluk|taluka|mandal)\b\s*[-–—]*\s*([A-Za-z][a-zA-Z]{2,})',
    re.IGNORECASE,
)
# Reverse: "Salempur Tehsil", "Mangalore Taluk"
_PAT_D2 = re.compile(
    r'\b([A-Z][a-z]{2,})\s+(?:tehsil|taluk|taluka|mandal)\b',
    re.IGNORECASE,
)


def _validate(name: str, before_ctx: str) -> Optional[str]:
    """Return title-cased block name if it looks like an admin unit, else None."""
    name = name.strip()
    if not name or len(name) < 3:
        return None
    if name[0].isdigit() or name[-1].isdigit():
        return None
    nl = name.lower()
    if nl in _NON_PLACE:
        return None
    # Reject only if preceded by a physical-material word (not generic prepositions)
    last_word = before_ctx.rstrip().rsplit(None, 1)
    if last_word and last_word[-1].lower().strip('.,;:') in _PHYSICAL_NOUNS:
        return None
    return name.title()


def extract_block_from_title(title: str) -> str:
    """
    Return sub-district administrative unit name found in tender title, or '' if none.
    Handles: Block (all states), Tehsil (UP/HP/Raj), Taluk/Taluka (KA/MH), Mandal (TS/AP).
    Priority: A (block→name) > B (concatenated) > C (name→block) > D (tehsil/taluk).
    """
    if not title:
        return ''

    t = title.strip()
    tl = t.lower()
    has_block = 'block' in tl
    has_sub = any(w in tl for w in ('tehsil', 'taluk', 'taluka', 'mandal'))

    if not has_block and not has_sub:
        return ''

    if has_block:
        # Pattern A
        for m in _PAT_A.finditer(t):
            candidate = m.group(1)
            before = t[:m.start()]
            result = _validate(candidate, before)
            if not result:
                continue
            ctx = t[max(0, m.start() - 10):m.end() + 15].lower()
            if _PHYSICAL_RE.search(ctx):
                continue
            return result

        # Pattern B (concatenated — lower priority, rarer)
        for m in _PAT_B.finditer(t):
            candidate = m.group(1)
            result = _validate(candidate, t[:m.start()])
            if result:
                return result

        # Pattern C
        for m in _PAT_C.finditer(t):
            candidate = m.group(1)
            nl = candidate.lower()
            if nl in _PHYSICAL_NOUNS or nl in _NON_PLACE:
                continue
            result = _validate(candidate, t[:m.start()])
            if not result:
                continue
            ctx = t[max(0, m.start() - 15):m.end()].lower()
            if _PHYSICAL_RE.search(ctx):
                continue
            return result

    if has_sub:
        # Pattern D: "Tehsil Nichlaul", "Taluk Mangalore", "Mandal Shadnagar"
        for m in _PAT_D.finditer(t):
            result = _validate(m.group(1), t[:m.start()])
            if result:
                return result
        # Pattern D2: "Salempur Tehsil", "Mangalore Taluk"
        for m in _PAT_D2.finditer(t):
            candidate = m.group(1)
            if candidate.lower() in _NON_PLACE:
                continue
            result = _validate(candidate, t[:m.start()])
            if result:
                return result

    return ''


def update_blocks_in_db(db_path=None, dry_run: bool = False) -> dict:
    """
    Walk every tender in the DB and fill the 'block' column from title text.
    Only updates rows where block is currently Unknown/NULL/''.
    Returns a stats dict.
    """
    from repository.db import DB_PATH
    path = Path(db_path) if db_path else DB_PATH

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT tender_id, title FROM tenders")
    rows = cur.fetchall()

    updated = 0
    extracted = 0
    examples: list[tuple[str, str]] = []

    for row in rows:
        tid = row['tender_id']
        raw_title = row['title'] or ''
        block = extract_block_from_title(raw_title)
        if not block:
            continue
        extracted += 1
        if len(examples) < 30:
            examples.append((raw_title[:90], block))
        if not dry_run:
            cur.execute(
                "UPDATE tenders SET block = ? "
                "WHERE tender_id = ? AND (block = 'Unknown' OR block IS NULL OR block = '')",
                (block, tid),
            )
            updated += cur.rowcount

    if not dry_run:
        conn.commit()
    conn.close()

    return {
        'total': len(rows),
        'extracted': extracted,
        'updated': updated,
        'dry_run': dry_run,
        'examples': examples,
    }
