#!/usr/bin/env python3
"""
Korean Value Investment Stock Screener
Usage: python run_screener.py [--year YYYY] [--dry-run]
"""

import argparse
import logging
import sys

from screener.config import get_target_fiscal_year
from screener import dart_client, market_data as md, financial_data as fd
from screener.universe import build_universe
from screener.filters import apply_exclusion_filters
from screener.scoring import compute_value_scores, apply_quality_overlay, select_top_stocks
from screener.output import build_output, write_output

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("screener.main")


def main() -> int:
    parser = argparse.ArgumentParser(description="Korean value stock screener")
    parser.add_argument("--year", type=int, default=None, help="Fiscal year for financial data")
    parser.add_argument("--dry-run", action="store_true", help="Skip writing output file")
    args = parser.parse_args()

    fiscal_year = args.year if args.year else get_target_fiscal_year()
    logger.info("Fiscal year: %d | dry-run: %s", fiscal_year, args.dry_run)

    # Validate DART API key early
    try:
        dart_client.load_corp_code_map()
    except dart_client.DartApiError as e:
        logger.error("DART setup failed: %s", e)
        return 1

    # Step 1: Find last trading date
    logger.info("Finding last trading date...")
    try:
        date_str = md.get_last_trading_date()
    except RuntimeError as e:
        logger.error("Could not find trading date: %s", e)
        return 1
    logger.info("Using trading date: %s", date_str)

    # Step 2: Get suspended tickers
    suspended = md.get_suspended_tickers(date_str)
    logger.info("Suspended tickers: %d", len(suspended))

    # Step 3: Get all KOSPI tickers for fiscal month lookup (top N * 2 candidates)
    logger.info("Loading market data...")
    caps = md.get_market_caps(date_str)
    top_candidates = caps.sort_values("market_cap", ascending=False).head(600).index.tolist()

    # Step 4: Fetch fiscal months from DART (needed before universe build)
    logger.info("Fetching fiscal months for top %d candidates...", len(top_candidates))
    fiscal_months = fd.get_fiscal_months(top_candidates)

    # Step 5: Build universe
    universe = build_universe(date_str, fiscal_months)
    universe_size = len(universe)

    if universe_size < 50:
        logger.warning("Universe is very small (%d stocks). Data may be incomplete.", universe_size)

    # Step 6: Fetch financial data from DART
    universe_tickers = universe.index.tolist()
    logger.info("Fetching DART financial data for %d stocks...", len(universe_tickers))
    financial_data = fd.fetch_financials(universe_tickers, fiscal_year)

    # Step 7: Apply exclusion filters
    filtered_universe, exclusion_log = apply_exclusion_filters(
        universe, financial_data, suspended
    )
    survived_filters = len(filtered_universe)

    # Step 8: Get market fundamentals + prices
    logger.info("Fetching market fundamentals...")
    fundamentals = md.get_fundamentals(date_str)
    prices = md.get_closing_prices(date_str)

    # Step 9: Compute value scores
    value_scores = compute_value_scores(
        filtered_universe, fundamentals, financial_data, prices, caps
    )

    # Step 10: Apply quality overlay
    quality_passing, quality_metrics = apply_quality_overlay(
        filtered_universe.index.tolist(), financial_data, caps
    )
    quality_passed = len(quality_passing)

    # Step 11: Select top stocks
    stocks = select_top_stocks(
        filtered_universe, value_scores, quality_passing, quality_metrics,
        financial_data, fundamentals, prices, caps
    )
    logger.info("Selected %d stocks", len(stocks))

    if len(stocks) < 10:
        warnings = [f"Only {len(stocks)} stocks selected (expected 15-20). Data may be incomplete."]
    else:
        warnings = []

    # Step 12: Build and write output
    meta_extra = {
        "data_as_of": date_str[:4] + "-" + date_str[4:6] + "-" + date_str[6:],
        "fiscal_year": fiscal_year,
        "universe_size": universe_size,
        "survived_filters": survived_filters,
        "quality_passed": quality_passed,
        "warnings": warnings,
    }
    output = build_output(stocks, exclusion_log, meta_extra)
    write_output(output, dry_run=args.dry_run)

    logger.info("Done. Selected %d stocks.", len(stocks))
    for s in stocks:
        logger.info(
            "  #%2d %-20s PBR=%-5s PER=%-6s Score=%-6.1f ROE=%s%%",
            s["rank"], s["name"], s.get("pbr", "N/A"),
            s.get("per", "N/A"), s["composite_score"],
            s.get("roe_pct", "N/A"),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
