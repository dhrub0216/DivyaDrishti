"""data.gov.in OGD REST API and PMGSY scrapers."""

import re
import time
import sqlite3
import logging

import requests

from config.portals import DATAGOV_BASE, DATAGOV_DATASETS, DATAGOV_RESOURCES, PMGSY_URL
from services.classifier import make_record
from repository.db import log_health

logger = logging.getLogger(__name__)

# Column name synonyms across different OGD datasets
_OGD_TITLE_COLS   = ["tender_title", "work_name", "subject", "description", "name_of_work", "title"]
_OGD_DEPT_COLS    = ["department", "organisation", "ministry", "org_name", "dept_name"]
_OGD_AMOUNT_COLS  = ["tender_value", "estimated_value", "value", "amount", "cost", "budget"]
_OGD_STATE_COLS   = ["state", "state_name", "location"]
_OGD_ID_COLS      = ["tender_id", "nit_number", "ref_no", "bid_number", "id"]
_OGD_STATUS_COLS  = ["status", "bid_status", "tender_status"]


def _pick(row: dict, candidates: list) -> str:
    for k in candidates:
        if k in row and row[k]:
            return str(row[k]).strip()
    return ""


def scrape_datagov(api_key: str, limit: int = 100, max_records: int = 10_000) -> list:
    """Pull procurement datasets from data.gov.in OGD API."""
    records = []

    logger.info("[OGD] Searching data.gov.in catalog for tender datasets...")
    search_terms = ["tender", "procurement", "NIT", "public procurement"]

    found_resources = []
    for term in search_terms:
        try:
            resp = requests.get(
                f"{DATAGOV_BASE}/catalog/resources",
                params={"q": term, "api-key": api_key, "format": "json", "count": 20},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("records", []):
                rid = item.get("id") or item.get("resource_id")
                if rid and rid not in found_resources:
                    found_resources.append(rid)
                    logger.info("[OGD] Found dataset: %s — %s", rid, item.get("title", "")[:60])
        except Exception as e:
            logger.warning("[OGD] Catalog search error for '%s': %s", term, e)

    found_resources = list(set(found_resources + list(DATAGOV_DATASETS.values())))
    logger.info("[OGD] Total datasets to pull: %d", len(found_resources))

    for resource_id in found_resources:
        offset = 0
        dataset_count = 0

        while dataset_count < max_records:
            try:
                resp = requests.get(
                    f"{DATAGOV_BASE}/resource/{resource_id}",
                    params={
                        "api-key": api_key,
                        "format":  "json",
                        "limit":   limit,
                        "offset":  offset,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                payload = resp.json()

                rows = payload.get("records", payload.get("fields", []))
                if not rows:
                    break

                for row in rows:
                    title  = _pick(row, _OGD_TITLE_COLS)
                    dept   = _pick(row, _OGD_DEPT_COLS)
                    amount = _pick(row, _OGD_AMOUNT_COLS)
                    state  = _pick(row, _OGD_STATE_COLS) or "Unknown"
                    tid    = _pick(row, _OGD_ID_COLS) or f"OGD-{resource_id[:8]}-{offset+dataset_count}"
                    status = _pick(row, _OGD_STATUS_COLS) or "Active"

                    if not title:
                        continue

                    records.append(make_record(
                        tender_id  = tid[:120],
                        title      = title[:300],
                        department = dept[:200],
                        amount_str = amount,
                        state      = state,
                        source     = f"data.gov.in/{resource_id[:8]}",
                        status     = status,
                    ))
                    dataset_count += 1

                total_available = payload.get("total", payload.get("count", 0))
                logger.info("[OGD] %s offset=%d — fetched %d / %d", resource_id[:12], offset, dataset_count, total_available)

                if offset + limit >= int(total_available):
                    break
                offset += limit
                time.sleep(0.5)

            except requests.exceptions.HTTPError as e:
                if e.response.status_code in (401, 403):
                    logger.error("[OGD] Invalid API key or access denied for %s", resource_id[:12])
                else:
                    logger.warning("[OGD] HTTP %s for %s", e.response.status_code, resource_id[:12])
                break
            except Exception as e:
                logger.warning("[OGD] Error for %s: %s", resource_id[:12], e)
                break

    logger.info("[OGD] Total records fetched: %d", len(records))
    return records


def scrape_pmgsy(max_pages: int, headless: bool, conn: sqlite3.Connection = None) -> list:
    """Scrape PMGSY tender portal for rural road construction tenders."""
    from scrapers.nic import scrape_nic_portal
    return scrape_nic_portal(
        state_label="PMGSY (Central)",
        base_url=PMGSY_URL,
        max_pages=max_pages,
        headless=headless,
        conn=conn,
    )
