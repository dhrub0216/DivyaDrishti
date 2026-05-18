"""
scraper_v3.py — backward-compatibility shim.

All logic has been moved to the layered package structure:
  config/     — portal URLs, sector definitions, geography constants
  models/     — TenderRecord dataclass, SCHEMA, field helpers
  repository/ — TenderRepository, get_db, upsert, log_health
  services/   — classifier, geocoder, enricher, aggregator
  scrapers/   — nic, gem, api_sources, deep, orchestrator
  scrapers/states/ — bihar, chhattisgarh, up, karnataka, ap_telangana, gujarat

This file re-exports every name that app.py or pipeline.py relied on from
the old monolithic scraper_v3.py so that any remaining callers continue to work.
"""

# Config
from config.portals import (
    NIC_PORTALS, GEM_URL, DATAGOV_BASE, PMGSY_URL,
    CGSTATE_CHEPS_URL, BIHAR_EPSV2_BASE,
    UPJN_BASE, UPJN_LIST, UPEIDA_BASE, UPEIDA_LIST, UPSBC_LIST,
    PVVNL_LIST, MVVNL_BASE, ETENDER_UP, UPMSC_LIST,
    GEPNIC_STATES, DATAGOV_RESOURCES, DATAGOV_DATASETS,
)

# Models
from models.tender import SCHEMA, TenderRecord, TENDER_FIELDS, _stable_hash, is_linear_title, linear_endpoints

# Repository
from repository.db import get_db, upsert, log_health, DB_PATH, BASE_DIR

# Services
from services.classifier import (
    classify_sector, parse_amount, extract_state_from_org, extract_date,
    make_record, _DATE_RE,
    classify_sector_v2, extract_state, extract_district, extract_block,
    reclassify_dataframe, reclassify_db,
    SECTOR_KEYWORDS,
)

# Scrapers
from scrapers.nic import scrape_nic_portal, scrape_gepnic_state
from scrapers.gem import scrape_gem
from scrapers.api_sources import scrape_datagov, scrape_pmgsy
from scrapers.deep import deep_scrape_bihar_epsv2, deep_scrape_up_tenders, deep_scrape_details
from scrapers.orchestrator import geocode_missing_db, run_entity_enrichment, run_pipeline

# State scrapers
from scrapers.states.bihar import scrape_bihar_epsv2
from scrapers.states.chhattisgarh import scrape_cgstate_cheps
from scrapers.states.up import (
    _upjn_hidden_fields, scrape_upjalNigam, scrape_upeida_archive,
    scrape_upsbc, scrape_etender_up_orgs, scrape_upmsc,
    scrape_pvvnl, scrape_mvvnl,
    enrich_up_power_amounts, enrich_etender_up_amounts, enrich_upmsc_amounts,
)
from scrapers.states.karnataka import scrape_karnataka
from scrapers.states.ap_telangana import scrape_ap_telangana
from scrapers.states.gujarat import scrape_gujarat

__all__ = [
    # config
    "NIC_PORTALS", "GEM_URL", "DATAGOV_BASE", "PMGSY_URL",
    "CGSTATE_CHEPS_URL", "BIHAR_EPSV2_BASE",
    "UPJN_BASE", "UPJN_LIST", "UPEIDA_BASE", "UPEIDA_LIST", "UPSBC_LIST",
    "PVVNL_LIST", "MVVNL_BASE", "ETENDER_UP", "UPMSC_LIST",
    "GEPNIC_STATES", "DATAGOV_RESOURCES", "DATAGOV_DATASETS",
    # models
    "SCHEMA", "TenderRecord", "TENDER_FIELDS", "_stable_hash", "is_linear_title", "linear_endpoints",
    # repository
    "get_db", "upsert", "log_health", "DB_PATH", "BASE_DIR",
    # services
    "classify_sector", "parse_amount", "extract_state_from_org", "extract_date",
    "make_record", "_DATE_RE",
    "classify_sector_v2", "extract_state", "extract_district", "extract_block",
    "reclassify_dataframe", "reclassify_db", "SECTOR_KEYWORDS",
    # scrapers
    "scrape_nic_portal", "scrape_gepnic_state",
    "scrape_gem", "scrape_datagov", "scrape_pmgsy",
    "deep_scrape_bihar_epsv2", "deep_scrape_up_tenders", "deep_scrape_details",
    "geocode_missing_db", "run_entity_enrichment", "run_pipeline",
    "scrape_bihar_epsv2", "scrape_cgstate_cheps",
    "_upjn_hidden_fields", "scrape_upjalNigam", "scrape_upeida_archive",
    "scrape_upsbc", "scrape_etender_up_orgs", "scrape_upmsc",
    "scrape_pvvnl", "scrape_mvvnl",
    "enrich_up_power_amounts", "enrich_etender_up_amounts", "enrich_upmsc_amounts",
    "scrape_karnataka", "scrape_ap_telangana", "scrape_gujarat",
]
