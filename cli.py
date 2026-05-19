"""
cli.py — Command-line interface for the DivyaDrishti tender scraper.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO USE (quick reference)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run the full pipeline (CPPP + GeM + all states + data.gov.in):
  python cli.py --sources cppp gem states

Scrape only specific sources:
  python cli.py --sources biharv2 cgstate up_misc

Scrape JS-rendered PSU portals (ONGC, NHAI, Coal India):
  python cli.py --sources ongc nhai coal_india

Scrape state GePNIC portals (NIC-based e-procurement):
  python cli.py --gepnic-states Bihar "Uttar Pradesh" Rajasthan
  python cli.py --gepnic-states all           # all 30+ states

Reclassify tenders already in the DB (offline, fast):
  python cli.py --reclassify

Geocode tenders with missing coordinates (uses Nominatim, slow):
  python cli.py --enrich-entities --enrich-limit 500

Visit detail pages of each tender to extract better data:
  python cli.py --deep-scrape --deep-limit 100

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AVAILABLE SOURCE KEYS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  cppp         Central NIC GePNIC portal (central government)
  states       All 28 state NIC GePNIC portals
  gem          Government e-Marketplace Bidplus
  datagov      data.gov.in Open Government Data (needs --api-key)
  pmgsy        PMGSY rural road tenders (CAPTCHA-handled Playwright)
  cgstate      Chhattisgarh CHEPS portal (Java Struts RFQ system)
  biharv2      Bihar EPS v2 (JS hash-tab AJAX pagination)
  up_misc      UP: Jal Nigam + UPEIDA + State Bridge Corp
  up_sectors   UP: Health, MSME, Social Welfare, Digital & IT portals
  up_power     UP: PVVNL + MVVNL power distribution
  psu_html     Central PSU HTML portals: MSEDCL, Chennai Port, BHEL
  ongc         ONGC Current NITs (Liferay portlet, Playwright)
  nhai         NHAI tenders (Angular SPA REST API, no browser)
  coal_india   Coal India all tenders (DataTables, Playwright)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
All scraped records are saved to tenders.db (SQLite, project root).
The dashboard (streamlit run app.py) reads from the same database.
A scraping_health_log entry is written for each source, recording whether
it succeeded, how many records it returned, and any error encountered.
"""

import argparse
import logging
import sqlite3

from config.portals import GEPNIC_STATES
from repository.db import get_db, upsert, DB_PATH
from scrapers.orchestrator import geocode_missing_db, run_entity_enrichment, run_pipeline


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="DivyaDrishti — India Government Tender Scraper v3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ── Source selection ──────────────────────────────────────────────────────
    parser.add_argument(
        "--sources", nargs="+",
        default=["cppp", "gem", "states", "datagov"],
        choices=["cppp", "gem", "states", "datagov", "pmgsy", "cgstate", "biharv2",
                 "up_misc", "up_power", "up_sectors", "psu_html", "ongc", "nhai", "coal_india"],
        help="Which portal sources to scrape (space-separated list).",
    )

    # ── Scraper controls ──────────────────────────────────────────────────────
    parser.add_argument("--pages",    type=int, default=20,
                        help="Maximum pages to scrape per portal (default: 20)")
    parser.add_argument("--headless", type=str, default="true", choices=["true", "false"],
                        help="Run browser headless=true (background) or false (visible window)")
    parser.add_argument("--api-key",  type=str, default="",
                        help="data.gov.in API key — required for --sources datagov")
    parser.add_argument("--states",   nargs="+", default=None,
                        help="Limit state portals to specific states (e.g. Bihar 'Uttar Pradesh')")

    # ── Standalone operation modes ────────────────────────────────────────────
    parser.add_argument("--enrich-entities", action="store_true",
                        help="Only geocode existing DB rows using Nominatim (no scraping).")
    parser.add_argument("--enrich-limit", type=int, default=500,
                        help="Max rows to geocode per run (Nominatim rate-limits at 1 req/sec)")

    parser.add_argument("--deep-scrape", action="store_true",
                        help="Visit each tender's detail page for richer contract text, "
                             "then re-classify sector/state/district.")
    parser.add_argument("--deep-limit", type=int, default=100,
                        help="Max detail pages to visit per deep-scrape run.")

    parser.add_argument("--up-deep", action="store_true",
                        help="Enrich UP Jal Nigam tenders: read NIT PDFs for allocated amounts.")
    parser.add_argument("--up-deep-limit", type=int, default=300,
                        help="Max UP Jal Nigam tenders to enrich (default 300).")

    parser.add_argument("--enrich-power", action="store_true",
                        help="OCR PVVNL/MVVNL tender PDFs to extract EMD → estimated cost.")

    parser.add_argument("--scrape-up-sectors", action="store_true",
                        help="Scrape UP-specific sectoral portals: Health, MSME, "
                             "Social Welfare, Digital & IT (etender.up.nic.in + upmsc.in).")
    parser.add_argument("--enrich-up-sectors", action="store_true",
                        help="Enrich etender.up.nic.in and UPMSC tenders with Tender Value amounts.")

    parser.add_argument("--gepnic-states", nargs="+", metavar="STATE",
                        help="Scrape GePNIC portals for given states. Use 'all' for every state.")

    parser.add_argument("--scrape-karnataka", action="store_true",
                        help="Scrape Karnataka eProcurement portal (non-GePNIC, no CAPTCHA).")
    parser.add_argument("--scrape-ap", action="store_true",
                        help="Scrape Andhra Pradesh eProcurement portal.")
    parser.add_argument("--scrape-telangana", action="store_true",
                        help="Scrape Telangana eProcurement portal.")
    parser.add_argument("--scrape-gujarat", action="store_true",
                        help="Scrape Gujarat nProcure portal (~4k tenders, Playwright XHR).")

    parser.add_argument("--reclassify", action="store_true",
                        help="Re-classify all tenders in the DB using the latest keyword rules "
                             "(offline — no network needed, very fast).")

    args    = parser.parse_args()
    headless = args.headless.lower() == "true"

    # ── Standalone modes — run one specific operation and exit ─────────────────

    # Geocode missing coordinates using Nominatim OSM (slow — 1 req/sec)
    if args.enrich_entities:
        n = run_entity_enrichment(limit=args.enrich_limit)
        print(f"\nEntity enrichment complete — {n} rows updated\n")
        raise SystemExit(0)

    # Re-run sector classification with latest keyword rules (fast, offline)
    if args.reclassify:
        from services.classifier import reclassify_db
        res = reclassify_db(str(DB_PATH))
        print(f"\nReclassification complete — {res}\n")
        raise SystemExit(0)

    # Visit each tender's detail page to read full contract specifications
    if args.deep_scrape:
        from scrapers.deep import deep_scrape_details
        stats = deep_scrape_details(limit=args.deep_limit, headless=headless)
        print(f"\nDeep scrape complete — {stats}\n")
        raise SystemExit(0)

    # OCR power utility tender PDFs to extract estimated costs
    if args.enrich_power:
        from scrapers.states.up import enrich_up_power_amounts
        _conn = sqlite3.connect(DB_PATH)
        n = enrich_up_power_amounts(_conn)
        _conn.close()
        print(f"\nUP Power enrichment complete — {n} tenders updated\n")
        raise SystemExit(0)

    # Extract tender values from etender.up.nic.in detail pages
    if args.enrich_up_sectors:
        from scrapers.states.up import enrich_etender_up_amounts, enrich_upmsc_amounts
        _conn = sqlite3.connect(DB_PATH)
        n1 = enrich_etender_up_amounts(_conn)
        n2 = enrich_upmsc_amounts(_conn)
        _conn.close()
        print(f"\nUP sector enrichment complete — {n1} etender + {n2} UPMSC tenders updated\n")
        raise SystemExit(0)

    # Scrape specific states' GePNIC NIC portals (all use the same scraper)
    if args.gepnic_states:
        from scrapers.nic import scrape_gepnic_state
        _conn = sqlite3.connect(DB_PATH)
        states_to_run = (list(GEPNIC_STATES.keys())
                         if args.gepnic_states == ["all"] else args.gepnic_states)
        grand_total = 0
        for state in states_to_run:
            if state not in GEPNIC_STATES:
                print(f"  Unknown state: {state}  (valid: {list(GEPNIC_STATES.keys())})")
                continue
            print(f"\n{'─'*50}")
            print(f"  Scraping {state}...")
            recs = scrape_gepnic_state(state, conn=_conn)
            grand_total += len(recs)
            print(f"  {state}: {len(recs)} records")
        geocode_missing_db(_conn)
        _conn.close()
        print(f"\nGePNIC scrape complete — {grand_total} records across {len(states_to_run)} states\n")
        raise SystemExit(0)

    # State-specific standalone scrapers
    if args.scrape_karnataka:
        from scrapers.states.karnataka import scrape_karnataka
        _conn = sqlite3.connect(DB_PATH)
        recs = scrape_karnataka(conn=_conn)
        _conn.close()
        print(f"\nKarnataka scrape complete — {len(recs)} records\n")
        raise SystemExit(0)

    if args.scrape_ap:
        from scrapers.states.ap_telangana import scrape_ap_telangana
        _conn = sqlite3.connect(DB_PATH)
        recs = scrape_ap_telangana("Andhra Pradesh", conn=_conn)
        _conn.close()
        print(f"\nAndhra Pradesh scrape complete — {len(recs)} records\n")
        raise SystemExit(0)

    if args.scrape_telangana:
        from scrapers.states.ap_telangana import scrape_ap_telangana
        _conn = sqlite3.connect(DB_PATH)
        recs = scrape_ap_telangana("Telangana", conn=_conn)
        _conn.close()
        print(f"\nTelangana scrape complete — {len(recs)} records\n")
        raise SystemExit(0)

    if args.scrape_gujarat:
        from scrapers.states.gujarat import scrape_gujarat
        _conn = sqlite3.connect(DB_PATH)
        recs = scrape_gujarat(conn=_conn)
        _conn.close()
        print(f"\nGujarat scrape complete — {len(recs)} records\n")
        raise SystemExit(0)

    # UP Health/MSME/SocialWelfare/IT sector portals
    if args.scrape_up_sectors:
        from scrapers.states.up import scrape_etender_up_orgs, scrape_upmsc
        _conn = sqlite3.connect(DB_PATH)
        recs  = scrape_etender_up_orgs(conn=_conn)
        total = 0
        for src in set(r["source"] for r in recs):
            n = upsert(_conn, [r for r in recs if r["source"] == src])
            total += n
            print(f"  {src}: {n} records")
        recs2 = scrape_upmsc(conn=_conn)
        n2    = upsert(_conn, recs2)
        total += n2
        print(f"  UPMSC/UP: {n2} records")
        geocode_missing_db(_conn)
        _conn.close()
        print(f"\nUP sector scrape complete — {total} tenders saved\n")
        raise SystemExit(0)

    # Enrich UP Jal Nigam tenders with amounts from NIT PDF documents
    if args.up_deep:
        from scrapers.deep import deep_scrape_up_tenders
        stats = deep_scrape_up_tenders(limit=args.up_deep_limit)
        print(f"\nUP deep scrape complete — {stats}\n")
        raise SystemExit(0)

    # ── Main pipeline — scrape all requested sources ───────────────────────────
    print(f"\n{'─'*60}")
    print(f"  DivyaDrishti — India Tender Scraper v3.0")
    print(f"  Sources  : {args.sources}")
    print(f"  Max pages: {args.pages} per portal")
    print(f"  Headless : {headless}")
    print(f"  DB       : {DB_PATH}")
    print(f"{'─'*60}\n")

    summary, total = run_pipeline(
        sources       = args.sources,
        max_pages     = args.pages,
        headless      = headless,
        api_key       = args.api_key,
        states_filter = args.states,
    )

    # Print a summary table of records saved per source
    print(f"\n{'─'*60}")
    print(f"  Scraping complete — {total:,} total tenders now in DB")
    print(f"{'─'*60}")
    for source, count in summary.items():
        print(f"  {source:<30} {count:>6,} records")
    print()


if __name__ == "__main__":
    main()
