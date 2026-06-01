import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from screener.config import QUALITY_THRESHOLDS, SELECTION_COUNT
from screener.piotroski import compute_fscore

logger = logging.getLogger(__name__)


def _percentile_rank(series: pd.Series) -> pd.Series:
    """Lower value → lower rank (better). NaN → worst rank (1.0)."""
    values = series.values.astype(float)
    nan_mask = np.isnan(values)
    ranks = np.full(len(values), 1.0)  # default worst
    if (~nan_mask).sum() > 0:
        valid_vals = values[~nan_mask]
        valid_ranks = rankdata(valid_vals, method="average") / len(valid_vals)
        ranks[~nan_mask] = valid_ranks
    return pd.Series(ranks, index=series.index)


def compute_value_scores(
    filtered_universe: pd.DataFrame,
    fundamentals: pd.DataFrame,
    financial_data: dict[str, dict],
    prices: pd.Series,
    market_caps: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute 4-factor value composite scores for all stocks in the filtered universe.

    Returns DataFrame with all metrics + composite_score.
    """
    tickers = filtered_universe.index.tolist()

    records = []
    for ticker in tickers:
        fin = financial_data.get(ticker, {})
        fund_row = fundamentals.loc[ticker] if ticker in fundamentals.index else pd.Series(dtype=float)
        price = prices.get(ticker, np.nan)
        cap_row = market_caps.loc[ticker] if ticker in market_caps.index else pd.Series(dtype=float)
        shares = cap_row.get("shares", np.nan)

        pbr = fund_row.get("pbr", np.nan)
        per = fund_row.get("per", np.nan)

        # PSR = price / (revenue / shares)
        revenue = fin.get("revenue")
        psr = np.nan
        if revenue and not np.isnan(price) and shares and shares > 0:
            revenue_per_share = revenue / shares
            if revenue_per_share > 0:
                psr = price / revenue_per_share

        # PCR = price / (operating_cash_flow / shares)
        op_cf = fin.get("operating_cash_flow")
        pcr = np.nan
        if op_cf and op_cf > 0 and not np.isnan(price) and shares and shares > 0:
            cf_per_share = op_cf / shares
            if cf_per_share > 0:
                pcr = price / cf_per_share

        # Zero or negative PER/PBR → unreliable, treat as NaN
        if per is not None and per <= 0:
            per = np.nan
        if pbr is not None and pbr <= 0:
            pbr = np.nan

        records.append({
            "ticker": ticker,
            "pbr": pbr,
            "per": per,
            "psr": psr,
            "pcr": pcr,
        })

    df = pd.DataFrame(records).set_index("ticker")

    # Compute percentile ranks (lower value = lower rank = better)
    df["pbr_rank_pct"] = _percentile_rank(df["pbr"]) * 100
    df["per_rank_pct"] = _percentile_rank(df["per"]) * 100
    df["psr_rank_pct"] = _percentile_rank(df["psr"]) * 100
    df["pcr_rank_pct"] = _percentile_rank(df["pcr"]) * 100

    df["composite_score"] = df[["pbr_rank_pct", "per_rank_pct", "psr_rank_pct", "pcr_rank_pct"]].mean(axis=1)

    return df


def apply_quality_overlay(
    tickers: list[str],
    financial_data: dict[str, dict],
    market_caps: pd.DataFrame,
) -> tuple[list[str], dict[str, dict]]:
    """
    Apply quality overlay filters. Returns (passing_tickers, quality_metrics_map).
    """
    thresholds = QUALITY_THRESHOLDS
    passing = []
    quality_map: dict[str, dict[str, Any]] = {}

    for ticker in tickers:
        fin = financial_data.get(ticker, {})

        roe = fin.get("roe")
        debt_ratio = fin.get("debt_ratio")
        current_ratio = fin.get("current_ratio")
        op_consecutive = fin.get("operating_profit_consecutive", False)

        # Compute Piotroski F-Score
        cap_row = market_caps.loc[ticker] if ticker in market_caps.index else pd.Series(dtype=float)
        shares = int(cap_row.get("shares", 0)) or None
        fscore = compute_fscore(fin, shares)

        quality_map[ticker] = {
            "roe": roe,
            "debt_ratio": debt_ratio,
            "current_ratio": current_ratio,
            "operating_profit_consecutive": op_consecutive,
            "piotroski_fscore": fscore,
        }

        # Check thresholds
        if roe is None or roe <= thresholds["roe_min"]:
            continue
        if debt_ratio is None or debt_ratio >= thresholds["debt_ratio_max"]:
            continue
        if current_ratio is None or current_ratio < thresholds["current_ratio_min"]:
            continue
        if not op_consecutive:
            continue
        if fscore is not None and fscore < thresholds["piotroski_min"]:
            continue

        passing.append(ticker)

    logger.info("Quality overlay: %d/%d passed", len(passing), len(tickers))
    return passing, quality_map


def select_top_stocks(
    filtered_universe: pd.DataFrame,
    value_scores: pd.DataFrame,
    quality_passing: list[str],
    quality_metrics: dict[str, dict],
    financial_data: dict[str, dict],
    fundamentals: pd.DataFrame,
    prices: pd.Series,
    market_caps: pd.DataFrame,
) -> list[dict]:
    """
    Final selection: quality-passing stocks ranked by composite_score (ascending).
    Returns list of stock dicts, sorted by composite_score.
    """
    quality_set = set(quality_passing)
    ranked = value_scores.loc[
        [t for t in value_scores.index if t in quality_set]
    ].sort_values("composite_score")

    selected = ranked.head(SELECTION_COUNT)
    results = []

    for rank, (ticker, row) in enumerate(selected.iterrows(), start=1):
        uni_row = filtered_universe.loc[ticker] if ticker in filtered_universe.index else pd.Series()
        cap_row = market_caps.loc[ticker] if ticker in market_caps.index else pd.Series(dtype=float)
        fin = financial_data.get(ticker, {})
        qual = quality_metrics.get(ticker, {})

        market_cap_bn = round(float(cap_row.get("market_cap", 0)) / 1e8, 1)  # 억 단위
        price = float(prices.get(ticker, 0))

        op_profit = fin.get("operating_profit")
        op_profit_bn = round(op_profit / 1e8, 1) if op_profit else None

        results.append({
            "rank": rank,
            "ticker": ticker,
            "name": str(uni_row.get("name", "")),
            "sector": str(uni_row.get("sector", "")),
            "market_cap_bn_krw": market_cap_bn,
            "price": int(price),
            "pbr": _round_or_none(row.get("pbr")),
            "per": _round_or_none(row.get("per")),
            "psr": _round_or_none(row.get("psr")),
            "pcr": _round_or_none(row.get("pcr")),
            "composite_score": round(float(row["composite_score"]), 2),
            "pbr_rank_pct": round(float(row["pbr_rank_pct"]), 1),
            "per_rank_pct": round(float(row["per_rank_pct"]), 1),
            "psr_rank_pct": round(float(row["psr_rank_pct"]), 1),
            "pcr_rank_pct": round(float(row["pcr_rank_pct"]), 1),
            "roe_pct": _pct_or_none(qual.get("roe")),
            "debt_ratio_pct": _pct_or_none(qual.get("debt_ratio")),
            "current_ratio_pct": _pct_or_none(qual.get("current_ratio")),
            "operating_profit_bn_krw": op_profit_bn,
            "operating_profit_consecutive": bool(qual.get("operating_profit_consecutive")),
            "piotroski_fscore": qual.get("piotroski_fscore"),
            "is_new": None,      # populated by output.py changelog logic
            "prev_rank": None,
        })

    return results


def _round_or_none(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return round(f, 2) if not np.isnan(f) else None
    except (TypeError, ValueError):
        return None


def _pct_or_none(val) -> float | None:
    if val is None:
        return None
    try:
        return round(float(val) * 100, 1)
    except (TypeError, ValueError):
        return None
