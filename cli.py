"""Unified CLI entry point for India Government Tender Scraper."""

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

    parser = argparse.ArgumentParser(description="India Government Tender Scraper v3")
    parser.add_argument(
        "--sources", nargs="+",
        default=["cppp", "gem", "states", "datagov"],
        choices=["cppp", "gem", "states", "datagov", "pmgsy", "cgstate", "biharv2",
                 "up_misc", "up_power", "up_sectors"],
        help=(
            "Which sources to scrape. "
            "pmgsy=PMGSY rural road portal (block-level); "
            "cgstate=Chhattisgarh CHEPS portal (Java Struts RFQ system); "
            "biharv2=Bihar EPS v2 portal (JS hash-tabs, AJAX pagination)"
        ),
    )
    parser.add_argument("--pages",    type=int, default=20,  help="Max pages per portal")
    parser.add_argument("--headless", type=str, default="true", choices=["true", "false"],
                        help="Run browser headless (true) or visible (false)")
    parser.add_argument("--api-key",  type=str, default="",
                        help="data.gov.in API key (required for --sources datagov)")
    parser.add_argument("--states",   nargs="+", default=None,
                        help="Limit state portals (e.g. --states Bihar 'Uttar Pradesh')")
    parser.add_argument("--enrich-entities", action="store_true",
                        help="Skip scraping; only run Nominatim entity geocoding "
                             "on existing tenders.db rows.")
    parser.add_argument("--enrich-limit", type=int, default=500,
                        help="Max rows to enrich per run (Nominatim is rate-limited).")
    parser.add_argument("--deep-scrape", action="store_true",
                        help="Visit each tender's detail page to read full contract text, "
                             "then re-classify sector/state/district from richer content.")
    parser.add_argument("--deep-limit", type=int, default=100,
                        help="Max detail pages to scrape per run.")
    parser.add_argument("--up-deep", action="store_true",
                        help="Enrich UP Jal Nigam tenders with allocated_amount from NIT PDFs.")
    parser.add_argument("--up-deep-limit", type=int, default=300,
                        help="Max UPJN tenders to enrich per run (default 300).")
    parser.add_argument("--enrich-power", action="store_true",
                        help="OCR PVVNL/MVVNL tender documents to extract EMD → est. cost.")
    parser.add_argument("--scrape-up-sectors", action="store_true",
                        help="Scrape UP Health/MSME/SocialWelfare/IT portals "
                             "(etender.up.nic.in + upmsc.in) and save to DB.")
    parser.add_argument("--enrich-up-sectors", action="store_true",
                        help="Enrich etender.up.nic.in and UPMSC tenders with Tender Value amounts.")
    parser.add_argument("--gepnic-states", nargs="+", metavar="STATE",
                        help="Scrape GePNIC NIC portals for given states. Use 'all' for all states.")
    parser.add_argument("--scrape-karnataka", action="store_true",
                        help="Scrape Karnataka eProcurement portal (non-GePNIC, no CAPTCHA).")
    parser.add_argument("--scrape-ap", action="store_true",
                        help="Scrape Andhra Pradesh eProcurement portal.")
    parser.add_argument("--scrape-telangana", action="store_true",
                        help="Scrape Telangana eProcurement portal.")
    parser.add_argument("--scrape-gujarat", action="store_true",
                        help="Scrape Gujarat nProcure portal (~4k tenders, Playwright XHR).")
    parser.add_argument("--reclassify", action="store_true",
                        help="Run in-memory text reclassifier and persist to DB (no network — fast).")
    args = parser.parse_args()

    headless = args.headless.lower() == "true"

    # Standalone entity enrichment mode
    if args.enrich_entities:
        n = run_entity_enrichment(limit=args.enrich_limit)
        print(f"\nEntity enrichment complete — {n} rows updated\n")
        raise SystemExit(0)

    # Standalone reclassifier mode (offline — fast)
    if args.reclassify:
        from services.classifier import reclassify_db
        res = reclassify_db(str(DB_PATH))
        print(f"\nReclassification complete — {res}\n")
        raise SystemExit(0)

    # Standalone deep-scrape mode (visit detail pages)
    if args.deep_scrape:
        from scrapers.deep import deep_scrape_details
        stats = deep_scrape_details(limit=args.deep_limit, headless=headless)
        print(f"\nDeep scrape complete — {stats}\n")
        raise SystemExit(0)

    # Standalone UP Power (PVVNL/MVVNL) amount enrichment via OCR
    if args.enrich_power:
        from scrapers.states.up import enrich_up_power_amounts
        _conn = sqlite3.connect(DB_PATH)
        n = enrich_up_power_amounts(_conn)
        _conn.close()
        print(f"\nUP Power enrichment complete — {n} tenders updated\n")
        raise SystemExit(0)

    # Standalone enrichment for etender UP sectors + UPMSC
    if args.enrich_up_sectors:
        from scrapers.states.up import enrich_etender_up_amounts, enrich_upmsc_amounts
        _conn = sqlite3.connect(DB_PATH)
        n1 = enrich_etender_up_amounts(_conn)
        n2 = enrich_upmsc_amounts(_conn)
        _conn.close()
        print(f"\nUP sector enrichment complete — {n1} etender + {n2} UPMSC tenders updated\n")
        raise SystemExit(0)

    # Standalone GePNIC multi-state scrape
    if args.gepnic_states:
        from scrapers.nic import scrape_gepnic_state
        _conn = sqlite3.connect(DB_PATH)
        states_to_run = list(GEPNIC_STATES.keys()) if args.gepnic_states == ["all"] else args.gepnic_states
        grand_total = 0
        for state in states_to_run:
            if state not in GEPNIC_STATES:
                print(f"  Unknown state: {state}  (valid: {list(GEPNIC_STATES.keys())})")
                continue
            print(f"\n{'─'*50}")
            print(f"  Scraping {state}...")
            recs = scrape_gepnic_state(state, conn=_conn)
            n = len(recs)  # already upserted inside function when conn provided
            grand_total += n
            print(f"  {state}: {n} new records")
        geocode_missing_db(_conn)
        _conn.close()
        print(f"\nGePNIC scrape complete — {grand_total} new records across {len(states_to_run)} states\n")
        raise SystemExit(0)

    # Karnataka scrape
    if args.scrape_karnataka:
        from scrapers.states.karnataka import scrape_karnataka
        _conn = sqlite3.connect(DB_PATH)
        recs = scrape_karnataka(conn=_conn)
        _conn.close()
        print(f"\nKarnataka scrape complete — {len(recs)} records\n")
        raise SystemExit(0)

    # AP scrape
    if args.scrape_ap:
        from scrapers.states.ap_telangana import scrape_ap_telangana
        _conn = sqlite3.connect(DB_PATH)
        recs = scrape_ap_telangana("Andhra Pradesh", conn=_conn)
        _conn.close()
        print(f"\nAndhra Pradesh scrape complete — {len(recs)} records\n")
        raise SystemExit(0)

    # Telangana scrape
    if args.scrape_telangana:
        from scrapers.states.ap_telangana import scrape_ap_telangana
        _conn = sqlite3.connect(DB_PATH)
        recs = scrape_ap_telangana("Telangana", conn=_conn)
        _conn.close()
        print(f"\nTelangana scrape complete — {len(recs)} records\n")
        raise SystemExit(0)

    # Gujarat scrape
    if args.scrape_gujarat:
        from scrapers.states.gujarat import scrape_gujarat
        _conn = sqlite3.connect(DB_PATH)
        recs = scrape_gujarat(conn=_conn)
        _conn.close()
        print(f"\nGujarat scrape complete — {len(recs)} records\n")
        raise SystemExit(0)

    # Standalone UP sector scrape (Health, MSME, Social Welfare, Digital & IT)
    if args.scrape_up_sectors:
        from scrapers.states.up import scrape_etender_up_orgs, scrape_upmsc
        _conn = sqlite3.connect(DB_PATH)
        recs = scrape_etender_up_orgs(conn=_conn)
        total = 0
        for src in set(r["source"] for r in recs):
            n = upsert(_conn, [r for r in recs if r["source"] == src])
            total += n
            print(f"  {src}: {n} records")
        recs2 = scrape_upmsc(conn=_conn)
        n2 = upsert(_conn, recs2)
        total += n2
        print(f"  UPMSC/UP: {n2} records")
        geocode_missing_db(_conn)
        _conn.close()
        print(f"\nUP sector scrape complete — {total} tenders saved\n")
        raise SystemExit(0)

    # Standalone UP Jal Nigam PDF enrichment
    if args.up_deep:
        from scrapers.deep import deep_scrape_up_tenders
        stats = deep_scrape_up_tenders(limit=args.up_deep_limit)
        print(f"\nUP deep scrape complete — {stats}\n")
        raise SystemExit(0)

    print(f"\n{'─'*60}")
    print(f"  India Tender Scraper v3.0")
    print(f"  Sources : {args.sources}")
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

    print(f"\n{'─'*60}")
    print(f"  Scraping complete — {total:,} total tenders in DB")
    print(f"{'─'*60}")
    for source, count in summary.items():
        print(f"  {source:<30} {count:>6,} records")
    print()


if __name__ == "__main__":
    main()
