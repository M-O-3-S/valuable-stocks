import logging

import pandas as pd

from screener.config import FISCAL_MONTH, UNIVERSE_SIZE
from screener.market_data import EXCLUDED_SECTORS_YF, EXCLUDED_INDUSTRIES_YF

logger = logging.getLogger(__name__)


def build_universe(
    market_df: pd.DataFrame,
    fiscal_months: dict[str, int | None],
) -> pd.DataFrame:
    """
    Apply fiscal month filter and sector pre-filter to the market DataFrame.
    Returns top UNIVERSE_SIZE stocks (by market cap) that pass the filters.
    """
    fm_series = pd.Series(fiscal_months, name="fiscal_month")
    df = market_df.join(fm_series, how="left")

    # Sector pre-filter: remove financial / holding companies
    def _exclude(row) -> bool:
        return (
            row.get("sector", "") in EXCLUDED_SECTORS_YF
            or row.get("industry", "") in EXCLUDED_INDUSTRIES_YF
        )

    before = len(df)
    df = df[~df.apply(_exclude, axis=1)]
    logger.info("Sector pre-filter: %d → %d (removed %d financial/holding)",
                before, len(df), before - len(df))

    # Fiscal month filter: keep December (or unknown — treated conservatively as include)
    before = len(df)
    df_dec = df[df["fiscal_month"].isin([FISCAL_MONTH, None])]
    # If too few December stocks, relax the filter
    if len(df_dec) < UNIVERSE_SIZE // 2:
        logger.warning("Too few December-fiscal stocks (%d); skipping fiscal filter", len(df_dec))
    else:
        df = df[df["fiscal_month"] == FISCAL_MONTH]
    logger.info("Fiscal month filter: %d → %d", before, len(df))

    universe = df.head(UNIVERSE_SIZE).copy()
    logger.info("Universe: %d stocks (target %d)", len(universe), UNIVERSE_SIZE)
    return universe
