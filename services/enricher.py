"""Entity geocoding enrichment — refactored from entity_geocoder.py."""

import re
import time
import math
import sqlite3
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

from config.geography import STATES_DATA, DISTRICT_COORDINATES, STATE_CENTERS
from models.tender import is_linear_title, linear_endpoints
from services.geocoder import _load_cache, _save_cache

logger = logging.getLogger(__name__)

NOMINATIM_DELAY = 1.05
DISTRICT_RADIUS_KM = 50


def extract_district_from_title(title: str) -> Optional[Tuple[str, str]]:
    """Find (state, district) mentioned in the title via STATES_DATA lookup."""
    if not title:
        return None
    t = title.lower()
    for state, districts in STATES_DATA.items():
        for dist in districts:
            if dist.lower() in t:
                return state, dist
    return None


def extract_block_from_title(title: str, state: str, district: str) -> Optional[str]:
    """Find a block name from STATES_DATA[state][district] mentioned in the title."""
    if state not in STATES_DATA or district not in STATES_DATA[state]:
        return None
    t = title.lower()
    for block in STATES_DATA[state][district]:
        if block.lower() in t:
            return block
    return None


_LINEAR_AB_RE = re.compile(
    r"(?:from\s+)?([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})"
    r"\s+(?:to|–|—|-)\s+"
    r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})"
)

_FACILITY_KEYWORDS = [
    "hospital", "phc", "chc", "dispensary", "clinic",
    "school", "college", "university", "vidyalaya", "institute",
    "centre", "center", "office", "building", "complex",
    "plant", "treatment", "warehouse", "depot", "yard",
    "market", "stadium", "library", "ghat", "park", "station",
]

_JUNK_ENTITIES = {
    "construction", "repair", "renovation", "upgrade", "installation",
    "supply", "procurement", "maintenance", "rehabilitation",
}


def extract_entity(title: str) -> Tuple[str, Optional[str]]:
    """
    Return (primary_entity, optional_secondary).
    If secondary is non-None → linear A→B feature (both endpoints geocodable).
    """
    if not title or not title.strip():
        return ("", None)

    m = _LINEAR_AB_RE.search(title)
    if m:
        a, b = m.group(1).strip(), m.group(2).strip()
        if a.lower() not in _JUNK_ENTITIES and b.lower() not in _JUNK_ENTITIES:
            return a, b

    for kw in _FACILITY_KEYWORDS:
        rm = re.search(
            rf"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){{0,3}}\s+{kw}s?)\b",
            title, re.I,
        )
        if rm:
            return rm.group(1).strip(), None

    title_l = title.lower()
    for prefix in ("construction of", "repair of", "upgrade of", "renovation of",
                   "installation of", "supply of", "procurement of",
                   "rehabilitation of", "widening of", "four-laning of"):
        if prefix in title_l:
            after = title_l.split(prefix, 1)[1].strip()
            words = after.split()[:4]
            entity = " ".join(words).rstrip(",.: -—")
            if entity and entity not in _JUNK_ENTITIES:
                return entity, None

    cleaned = re.sub(r"[—–\-:]+", " ", title).strip()
    words = [w for w in cleaned.split() if w.lower() not in _JUNK_ENTITIES]
    return (" ".join(words[:4]).strip(), None)


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def within_district_bounds(lat, lon, state, district, max_km: float = DISTRICT_RADIUS_KM) -> bool:
    if state in DISTRICT_COORDINATES and district in DISTRICT_COORDINATES[state]:
        c = DISTRICT_COORDINATES[state][district]
        return _haversine_km(lat, lon, c["lat"], c["lon"]) <= max_km
    if state in STATE_CENTERS:
        c = STATE_CENTERS[state]
        return _haversine_km(lat, lon, c["lat"], c["lon"]) <= 300
    return True


def geocode_entity_bounded(
    entity: str, state: str, district: str,
    geo: Nominatim, cache: Dict,
) -> Optional[Tuple[float, float]]:
    """Nominatim geocode with district context + bounded validation."""
    if not entity or len(entity.strip()) < 3:
        return None

    parts = [entity]
    if district and district != "Unknown":
        parts.append(district)
    if state and state != "Unknown":
        parts.append(state)
    parts.append("India")
    query = ", ".join(parts)

    if query in cache:
        c = cache[query]
        if c.get("lat") is None:
            return None
        if within_district_bounds(c["lat"], c["lon"], state, district):
            return c["lat"], c["lon"]
        return None

    time.sleep(NOMINATIM_DELAY)
    try:
        r = geo.geocode(query, timeout=10)
        if not r:
            cache[query] = {"lat": None, "lon": None}
            return None
        lat, lon = r.latitude, r.longitude
        cache[query] = {"lat": lat, "lon": lon}
        if within_district_bounds(lat, lon, state, district):
            return lat, lon
        logger.info("Geocode '%s' → (%.4f,%.4f) outside %s bounds; rejected",
                    entity, lat, lon, district)
        return None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.warning("Geocode failed for '%s': %s", entity, e)
        return None


def enrich_record(record: Dict, geo: Nominatim, cache: Dict) -> Dict:
    """Enrich one record in-place with geocoded coordinates."""
    title = (record.get("title") or "").strip()
    state = record.get("state") or "Unknown"
    district = record.get("district") or "Unknown"

    if district == "Unknown":
        ext = extract_district_from_title(title)
        if ext:
            state, district = ext
            record["state"] = state
            record["district"] = district

    block = record.get("block") or "Unknown"
    if block == "Unknown" and state != "Unknown" and district != "Unknown":
        b = extract_block_from_title(title, state, district)
        if b:
            record["block"] = b

    primary, secondary = extract_entity(title)

    coords = geocode_entity_bounded(primary, state, district, geo, cache)
    if coords:
        record["latitude"], record["longitude"] = coords

    if secondary:
        c2 = geocode_entity_bounded(secondary, state, district, geo, cache)
        if c2:
            record["latitude2"], record["longitude2"] = c2
    elif is_linear_title(title) and coords:
        lat2, lon2 = linear_endpoints(coords[0], coords[1], record.get("tender_id", title))
        record["latitude2"], record["longitude2"] = lat2, lon2

    return record


def enrich_db_geocode(db_path: str, limit: int = 500) -> int:
    """
    Re-geocode the first `limit` rows in tenders.db that need enrichment.
    Returns: count of rows updated.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """SELECT tender_id, title, state, district, block, latitude, longitude
           FROM tenders
           WHERE (district IS NULL OR district = 'Unknown' OR latitude IS NULL)
              OR (latitude2 IS NULL AND title LIKE '%road%')
              OR (latitude2 IS NULL AND title LIKE '%bridge%')
           LIMIT ?""",
        (limit,),
    ).fetchall()

    if not rows:
        logger.info("[ENRICH] No rows need geocoding.")
        conn.close()
        return 0

    logger.info("[ENRICH] Processing %d rows (this takes ~%d minutes due to 1 req/sec rate limit)",
                len(rows), int(len(rows) * NOMINATIM_DELAY / 60) + 1)

    cache = _load_cache()
    geo = Nominatim(user_agent="india_tender_entity_geocoder_v4")

    updated = 0
    for i, row in enumerate(rows, 1):
        rec = dict(row)
        enrich_record(rec, geo, cache)

        conn.execute(
            """UPDATE tenders
               SET state=?, district=?, block=?,
                   latitude=?, longitude=?,
                   latitude2=?, longitude2=?
               WHERE tender_id=?""",
            (
                rec.get("state"), rec.get("district"), rec.get("block"),
                rec.get("latitude"), rec.get("longitude"),
                rec.get("latitude2"), rec.get("longitude2"),
                rec["tender_id"],
            ),
        )
        updated += 1

        if i % 25 == 0:
            conn.commit()
            _save_cache(cache)
            logger.info("[ENRICH] %d / %d done", i, len(rows))

    conn.commit()
    _save_cache(cache)
    conn.close()
    logger.info("[ENRICH] Complete — %d rows enriched", updated)
    return updated
