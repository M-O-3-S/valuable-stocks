import logging

import pandas as pd

from screener import market_data as md
from screener.config import FISCAL_MONTH, UNIVERSE_SIZE

logger = logging.getLogger(__name__)


def build_universe(date_str: str, fiscal_months: dict[str, int | None]) -> pd.DataFrame:
    """
    Build the investable universe: KOSPI top-N by market cap,
    filtered to December fiscal year-end.

    Returns DataFrame indexed by ticker with columns:
      name, market_cap, shares, sector, fiscal_month
    """
    caps = md.get_market_caps(date_str)
    names = md.get_ticker_names(date_str)
    sectors = md.get_sector_classifications(date_str)

    df = caps.copy()
    df = df.join(names, how="left")
    df = df.join(sectors, how="left")

    df = df.sort_values("market_cap", ascending=False)
    top_n = df.head(UNIVERSE_SIZE * 2)  # fetch extra to allow for fiscal filter

    fm_series = pd.Series(fiscal_months, name="fiscal_month")
    top_n = top_n.join(fm_series, how="left")

    # Keep only December fiscal year-end; unknown fiscal month → exclude (conservative)
    universe = top_n[top_n["fiscal_month"] == FISCAL_MONTH].head(UNIVERSE_SIZE).copy()

    logger.info(
        "Universe: %d tickers (from top-%d KOSPI, fiscal month=%d filter)",
        len(universe), UNIVERSE_SIZE * 2, FISCAL_MONTH,
    )
    return universe
