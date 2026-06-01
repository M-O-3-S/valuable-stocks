#!/usr/bin/env python3
"""
Korean Value Investment Stock Screener
Usage: python run_screener.py [--year YYYY] [--dry-run] [--test-mode [N]]
"""

import argparse
import logging
import sys

from screener.config import get_target_fiscal_year
from screener import dart_client
from screener import market_data as md
from screener import financial_data as fd
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
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--test-mode", nargs="?", const=20, type=int, metavar="N",
        help="Limit universe to top N stocks for fast pipeline testing (default: 20)",
    )
    args = parser.parse_args()

    fiscal_year = args.year if args.year else get_target_fiscal_year()
    test_limit: int | None = args.test_mode
    logger.info(
        "Fiscal year: %d | dry-run: %s | test-mode: %s",
        fiscal_year, args.dry_run, f"top-{test_limit}" if test_limit else "off",
    )

    # Step 1: Load DART corp code map (validates API key + downloads corpCode.xml)
    logger.info("Loading DART corp code map...")
    try:
        corp_map = dart_client.load_corp_code_map()
    except dart_client.DartApiError as e:
        logger.error("DART setup failed: %s", e)
        return 1

    dart_stock_codes = [code for code in corp_map.keys() if code.strip()]
    logger.info("DART stock codes loaded: %d", len(dart_stock_codes))

    # Step 2: Find last trading date
    logger.info("Finding last trading date...")
    try:
        date_str = md.get_last_trading_date()
    except RuntimeError as e:
        logger.error("Could not find trading date: %s", e)
        return 1
    logger.info("Using trading date: %s", date_str)

    # Step 3: Build market dataframe from yfinance
    logger.info("Building market data from yfinance (may take 10-15 min)...")
    market_df = md.build_market_dataframe(dart_stock_codes)
    if market_df.empty:
        logger.error("No market data retrieved. Aborting.")
        return 1

    # Step 4: Fetch fiscal months from DART for top candidates
    candidate_limit = test_limit * 3 if test_limit else 600
    top_candidates = market_df.head(candidate_limit).index.tolist()
    logger.info("Fetching fiscal months for %d candidates...", len(top_candidates))
    fiscal_months = fd.get_fiscal_months(top_candidates)

    # Step 5: Build universe (fiscal + sector filter)
    universe = build_universe(market_df, fiscal_months)
    if test_limit:
        universe = universe.head(test_limit)
        logger.info("test-mode: universe capped at %d stocks", test_limit)
    universe_size = len(universe)
    if universe_size < 50 and not test_limit:
        logger.warning("Universe very small (%d). Data may be incomplete.", universe_size)

    # Step 6: Fetch DART financial data
    universe_tickers = universe.index.tolist()
    logger.info("Fetching DART financial data for %d stocks...", len(universe_tickers))
    financial_data = fd.fetch_financials(universe_tickers, fiscal_year)

    # Step 7: Apply exclusion filters
    suspended = md.get_suspended_tickers(date_str)
    filtered_universe, exclusion_log = apply_exclusion_filters(
        universe, financial_data, suspended
    )
    survived_filters = len(filtered_universe)

    # Step 8: Compute value scores
    value_scores = compute_value_scores(filtered_universe, financial_data, market_df)

    # Step 9: Quality overlay
    quality_passing, quality_metrics = apply_quality_overlay(
        filtered_universe.index.tolist(), financial_data, market_df
    )
    quality_passed = len(quality_passing)

    # Step 10: Select top stocks
    stocks = select_top_stocks(
        filtered_universe, value_scores, quality_passing,
        quality_metrics, financial_data, market_df
    )
    logger.info("Selected %d stocks", len(stocks))

    warnings = []
    if len(stocks) < 10:
        warnings.append(
            f"Only {len(stocks)} stocks selected (expected 15-20). "
            "Data may be incomplete."
        )

    # Step 11: Build and write output
    meta_extra = {
        "data_as_of": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}",
        "fiscal_year": fiscal_year,
        "universe_size": universe_size,
        "survived_filters": survived_filters,
        "quality_passed": quality_passed,
        "warnings": warnings,
    }
    output = build_output(stocks, exclusion_log, meta_extra)
    write_output(output, dry_run=args.dry_run)

    logger.info("Done. Selected %d stocks:", len(stocks))
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
