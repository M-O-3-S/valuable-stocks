import logging
from typing import Any

from screener.config import DART_ACCOUNT_ALIASES
from screener import dart_client

logger = logging.getLogger(__name__)


def _find_account(rows: list[dict], canonical_name: str) -> int | None:
    """Search DART account rows for any alias match. Returns raw amount as int."""
    aliases = DART_ACCOUNT_ALIASES.get(canonical_name, [])
    for alias in aliases:
        match = next(
            (r for r in rows if r.get("account_nm", "").strip() == alias),
            None,
        )
        if match:
            raw = match.get("thstrm_amount", "").replace(",", "").strip()
            if raw and raw not in ("-", ""):
                try:
                    return int(raw)
                except ValueError:
                    pass
    return None


def _parse_financials(rows: list[dict]) -> dict[str, Any]:
    """Extract all needed financial figures from a DART account row list."""
    result: dict[str, Any] = {}
    for key in DART_ACCOUNT_ALIASES:
        result[key] = _find_account(rows, key)
    return result


def fetch_financials(tickers: list[str], year: int) -> dict[str, dict]:
    """
    Fetch annual financial data from DART for each ticker.
    Returns dict: ticker → financial metrics dict.
    Missing/failed tickers are absent from the result.
    """
    corp_map = dart_client.load_corp_code_map()
    results: dict[str, dict] = {}

    for i, ticker in enumerate(tickers):
        corp_code = corp_map.get(ticker)
        if not corp_code:
            logger.debug("No corp_code for ticker %s", ticker)
            continue

        logger.info("[%d/%d] Fetching DART data for %s", i + 1, len(tickers), ticker)

        # Current year
        rows_current = dart_client.get_single_acnt(corp_code, year, "11011")
        if not rows_current:
            logger.warning("No annual data for %s year=%d", ticker, year)
            continue

        fin_current = _parse_financials(rows_current)

        # Prior year (needed for consecutive operating profit + Piotroski)
        rows_prior = dart_client.get_single_acnt(corp_code, year - 1, "11011")
        fin_prior = _parse_financials(rows_prior) if rows_prior else {}

        # Derived ratios
        equity = fin_current.get("total_equity")
        assets = fin_current.get("total_assets")
        liabilities = fin_current.get("total_liabilities")
        current_assets = fin_current.get("current_assets")
        current_liabilities = fin_current.get("current_liabilities")
        net_income = fin_current.get("net_income")
        op_profit_current = fin_current.get("operating_profit")
        op_profit_prior = fin_prior.get("operating_profit")

        roe = (net_income / equity) if equity and equity > 0 and net_income is not None else None
        debt_ratio = (liabilities / equity) if equity and equity > 0 and liabilities is not None else None
        current_ratio = (
            (current_assets / current_liabilities)
            if current_liabilities and current_liabilities > 0 and current_assets is not None
            else None
        )
        op_profit_consecutive = (
            op_profit_current is not None
            and op_profit_current > 0
            and op_profit_prior is not None
            and op_profit_prior > 0
        )

        results[ticker] = {
            "roe": roe,
            "debt_ratio": debt_ratio,
            "current_ratio": current_ratio,
            "total_equity": equity,
            "total_assets": assets,
            "total_liabilities": liabilities,
            "current_assets": current_assets,
            "current_liabilities": current_liabilities,
            "net_income": net_income,
            "revenue": fin_current.get("revenue"),
            "operating_profit": op_profit_current,
            "operating_profit_prior": op_profit_prior,
            "operating_cash_flow": fin_current.get("operating_cash_flow"),
            "gross_profit": fin_current.get("gross_profit"),
            "gross_profit_prior": fin_prior.get("gross_profit"),
            "total_assets_prior": fin_prior.get("total_assets"),
            "net_income_prior": fin_prior.get("net_income"),
            "long_term_debt": fin_current.get("long_term_debt"),
            "long_term_debt_prior": fin_prior.get("long_term_debt"),
            "current_assets_prior": fin_prior.get("current_assets"),
            "current_liabilities_prior": fin_prior.get("current_liabilities"),
            "operating_profit_consecutive": op_profit_consecutive,
        }

    return results


def get_fiscal_months(tickers: list[str]) -> dict[str, int | None]:
    """Return dict: ticker → fiscal month (int 1-12) or None if unknown."""
    corp_map = dart_client.load_corp_code_map()
    result: dict[str, int | None] = {}

    for ticker in tickers:
        corp_code = corp_map.get(ticker)
        if not corp_code:
            result[ticker] = None
            continue
        try:
            info = dart_client.get_company_info(corp_code)
            acc_mt_raw = info.get("acc_mt", "")
            acc_mt = int(acc_mt_raw) if acc_mt_raw.strip().isdigit() else None
            result[ticker] = acc_mt
        except Exception as e:
            logger.debug("Could not get fiscal month for %s: %s", ticker, e)
            result[ticker] = None

    return result
