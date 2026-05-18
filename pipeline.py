"""
pipeline.py — backward-compatibility shim.

All logic has been moved to the layered package structure:
  config/geography.py   — LINEAR_KEYWORDS, STATES_DATA, STATE_CENTERS,
                          DISTRICT_COORDINATES, BLOCK_COORDINATES,
                          TITLE_TEMPLATES, SECTOR_WEIGHTS
  config/sectors.py     — SECTOR_DEPARTMENTS, SECTOR_COLORS
  models/tender.py      — _stable_hash, is_linear_title, linear_endpoints
  services/aggregator.py — all pipeline/aggregation functions
  services/classifier.py — reclassify_dataframe

This file re-exports every public name that app.py (or any other caller) used
to import directly from pipeline.py, so that existing callers continue to work
without modification.
"""

# ── Geography / geometry constants ──────────────────────────────────────────
from config.geography import (
    LINEAR_KEYWORDS,
    STATES_DATA,
    STATE_CENTERS,
    DISTRICT_COORDINATES,
    BLOCK_COORDINATES,
    TITLE_TEMPLATES,
    SECTOR_WEIGHTS,
)

# ── Sector constants ─────────────────────────────────────────────────────────
from config.sectors import SECTOR_DEPARTMENTS, SECTOR_COLORS

# ── Model helpers ────────────────────────────────────────────────────────────
from models.tender import _stable_hash, is_linear_title, linear_endpoints

# ── Aggregation / pipeline functions ─────────────────────────────────────────
from services.aggregator import (
    _district_coords,
    resolve_coords,
    apply_memory_optimization,
    generate_enterprise_seed_data,
    load_health_log,
    load_enterprise_tender_stream,
    get_full_hierarchy,
    server_side_aggregate,
    get_view_config,
)

# ── Reclassifier (re-exported for backward compat) ───────────────────────────
from services.classifier import reclassify_dataframe, reclassify_db

__all__ = [
    # geography
    "LINEAR_KEYWORDS",
    "STATES_DATA",
    "STATE_CENTERS",
    "DISTRICT_COORDINATES",
    "BLOCK_COORDINATES",
    "TITLE_TEMPLATES",
    "SECTOR_WEIGHTS",
    # sectors
    "SECTOR_DEPARTMENTS",
    "SECTOR_COLORS",
    # models
    "_stable_hash",
    "is_linear_title",
    "linear_endpoints",
    # aggregation
    "_district_coords",
    "resolve_coords",
    "apply_memory_optimization",
    "generate_enterprise_seed_data",
    "load_health_log",
    "load_enterprise_tender_stream",
    "get_full_hierarchy",
    "server_side_aggregate",
    "get_view_config",
    # reclassifier
    "reclassify_dataframe",
    "reclassify_db",
]
