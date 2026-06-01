import logging

import pandas as pd

logger = logging.getLogger(__name__)


def apply_exclusion_filters(
    universe: pd.DataFrame,
    financial_data: dict,
    suspended_tickers: set[str],
) -> tuple[pd.DataFrame, dict]:
    """
    Apply exclusion filters to the universe.
    Returns (filtered_df, exclusion_log).
    """
    exclusion_log: dict[str, list[str]] = {
        "suspended": [],
        "sector_excluded": [],
        "non_december_fiscal": [],
        "capital_impaired": [],
        "net_loss": [],
        "data_unavailable": [],
    }

    remaining = universe.copy()

    # 1. Suspended / administrative
    suspended_in_universe = [t for t in remaining.index if t in suspended_tickers]
    exclusion_log["suspended"] = suspended_in_universe
    remaining = remaining.drop(index=suspended_in_universe, errors="ignore")
    logger.info("After suspended filter: %d (excluded %d)", len(remaining), len(suspended_in_universe))

    # 2. No financial data available
    no_data = [t for t in remaining.index if t not in financial_data]
    exclusion_log["data_unavailable"] = no_data
    remaining = remaining.drop(index=no_data, errors="ignore")
    logger.info("After data availability filter: %d (excluded %d)", len(remaining), len(no_data))

    # 3. Capital impairment (자본잠식)
    capital_impaired = [
        t for t in remaining.index
        if (financial_data[t].get("total_equity") or 1) <= 0
    ]
    exclusion_log["capital_impaired"] = capital_impaired
    remaining = remaining.drop(index=capital_impaired, errors="ignore")
    logger.info("After capital impairment filter: %d (excluded %d)", len(remaining), len(capital_impaired))

    # 4. Net loss (최근 당기순이익 적자)
    net_loss = [
        t for t in remaining.index
        if (financial_data[t].get("net_income") or 1) <= 0
    ]
    exclusion_log["net_loss"] = net_loss
    remaining = remaining.drop(index=net_loss, errors="ignore")
    logger.info("After net loss filter: %d (excluded %d)", len(remaining), len(net_loss))

    logger.info("Final universe after all filters: %d stocks", len(remaining))
    return remaining, exclusion_log
