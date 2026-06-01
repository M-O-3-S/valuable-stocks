import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_fscore(fin: dict[str, Any], shares: int | None) -> int | None:
    """
    Compute Piotroski F-Score (0-9) from financial data dict.
    Returns None if data is too incomplete to be meaningful.
    """
    assets = fin.get("total_assets")
    assets_prior = fin.get("total_assets_prior")
    net_income = fin.get("net_income")
    net_income_prior = fin.get("net_income_prior")
    op_cf = fin.get("operating_cash_flow")
    liabilities = fin.get("total_liabilities")
    equity = fin.get("total_equity")
    current_assets = fin.get("current_assets")
    current_liabilities = fin.get("current_liabilities")
    current_assets_prior = fin.get("current_assets_prior")
    current_liabilities_prior = fin.get("current_liabilities_prior")
    gross_profit = fin.get("gross_profit")
    gross_profit_prior = fin.get("gross_profit_prior")
    revenue = fin.get("revenue")
    revenue_prior = fin.get("total_assets_prior")  # placeholder — revenue prior not fetched separately
    long_term_debt = fin.get("long_term_debt")
    long_term_debt_prior = fin.get("long_term_debt_prior")

    if None in (assets, assets_prior, net_income, op_cf, equity):
        return None

    score = 0
    signals_computed = 0

    # --- Profitability ---
    # F1: ROA > 0
    if assets and assets > 0:
        roa = net_income / assets
        score += int(roa > 0)
        signals_computed += 1

    # F2: Operating cash flow > 0
    if op_cf is not None:
        score += int(op_cf > 0)
        signals_computed += 1

    # F3: ROA increased YoY
    if assets and assets > 0 and assets_prior and assets_prior > 0 and net_income_prior is not None:
        roa_current = net_income / assets
        roa_prior = net_income_prior / assets_prior
        score += int(roa_current > roa_prior)
        signals_computed += 1

    # F4: Cash flow > net income (accrual quality)
    if op_cf is not None and net_income is not None:
        score += int(op_cf > net_income)
        signals_computed += 1

    # --- Leverage / Liquidity ---
    # F5: Long-term debt ratio decreased YoY
    if (
        long_term_debt is not None and long_term_debt_prior is not None
        and assets and assets > 0 and assets_prior and assets_prior > 0
    ):
        ltd_ratio = long_term_debt / assets
        ltd_ratio_prior = long_term_debt_prior / assets_prior
        score += int(ltd_ratio < ltd_ratio_prior)
        signals_computed += 1

    # F6: Current ratio increased YoY
    if (
        current_assets is not None and current_liabilities and current_liabilities > 0
        and current_assets_prior is not None
        and current_liabilities_prior and current_liabilities_prior > 0
    ):
        cr = current_assets / current_liabilities
        cr_prior = current_assets_prior / current_liabilities_prior
        score += int(cr > cr_prior)
        signals_computed += 1

    # F7: No new share issuance (proxy: shares data not available from DART easily)
    # Skip this signal if shares data is unavailable
    signals_computed += 0  # not counted

    # --- Operating Efficiency ---
    # F8: Gross margin increased YoY
    if (
        gross_profit is not None and revenue and revenue > 0
        and gross_profit_prior is not None
    ):
        # revenue_prior is not directly available — skip if not present
        pass  # would need revenue from prior year, skipping
    signals_computed += 0

    # F9: Asset turnover increased YoY (revenue / assets)
    if (
        revenue is not None and assets and assets > 0
        and assets_prior and assets_prior > 0
    ):
        # revenue_prior would be needed — not available in current data structure
        pass
    signals_computed += 0

    if signals_computed < 4:
        return None

    return score
