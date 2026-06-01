import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from screener.config import QUALITY_THRESHOLDS, SELECTION_COUNT
from screener.piotroski import compute_fscore

logger = logging.getLogger(__name__)


def _percentile_rank(series: pd.Series) -> pd.Series:
    """Lower value → lower percentile rank (better). NaN → 1.0 (worst)."""
    values = series.values.astype(float)
    nan_mask = np.isnan(values)
    ranks = np.full(len(values), 1.0)
    if (~nan_mask).sum() > 0:
        valid_vals = values[~nan_mask]
        ranks[~nan_mask] = rankdata(valid_vals, method="average") / len(valid_vals)
    return pd.Series(ranks, index=series.index)


def compute_value_scores(
    filtered_universe: pd.DataFrame,
    financial_data: dict[str, dict],
    market_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute 4-factor value composite scores.
    PBR, PER, PSR come from yfinance (market_df).
    PCR is computed from DART operating cash flow + yfinance shares/price.
    """
    tickers = filtered_universe.index.tolist()
    records = []

    for ticker in tickers:
        mrow = market_df.loc[ticker] if ticker in market_df.index else pd.Series(dtype=float)
        fin = financial_data.get(ticker, {})

        pbr = _clean(mrow.get("pbr"))
        per = _clean(mrow.get("per"))
        psr = _clean(mrow.get("psr"))

        # PCR = price / (operating_cash_flow / shares)
        price = float(mrow.get("price") or 0)
        shares = float(mrow.get("shares") or 0)
        op_cf = fin.get("operating_cash_flow")
        pcr = None
        if op_cf and op_cf > 0 and price > 0 and shares > 0:
            cf_ps = op_cf / shares
            if cf_ps > 0:
                pcr = price / cf_ps

        # Zero or negative PER/PBR → unreliable
        if per is not None and per <= 0:
            per = None
        if pbr is not None and pbr <= 0:
            pbr = None

        records.append({"ticker": ticker, "pbr": pbr, "per": per, "psr": psr, "pcr": pcr})

    df = pd.DataFrame(records).set_index("ticker")

    df["pbr_rank_pct"] = _percentile_rank(df["pbr"]) * 100
    df["per_rank_pct"] = _percentile_rank(df["per"]) * 100
    df["psr_rank_pct"] = _percentile_rank(df["psr"]) * 100
    df["pcr_rank_pct"] = _percentile_rank(df["pcr"]) * 100
    df["composite_score"] = df[["pbr_rank_pct", "per_rank_pct",
                                "psr_rank_pct", "pcr_rank_pct"]].mean(axis=1)
    return df


def apply_quality_overlay(
    tickers: list[str],
    financial_data: dict[str, dict],
    market_df: pd.DataFrame,
) -> tuple[list[str], dict[str, dict]]:
    """Returns (passing_tickers, quality_metrics_map)."""
    thresholds = QUALITY_THRESHOLDS
    passing = []
    quality_map: dict[str, dict[str, Any]] = {}

    for ticker in tickers:
        fin = financial_data.get(ticker, {})
        mrow = market_df.loc[ticker] if ticker in market_df.index else pd.Series(dtype=float)
        shares_raw = mrow.get("shares")
        try:
            shares = int(float(shares_raw)) if shares_raw is not None and shares_raw == shares_raw else None
            if shares == 0:
                shares = None
        except (ValueError, TypeError):
            shares = None

        roe = fin.get("roe")
        debt_ratio = fin.get("debt_ratio")
        current_ratio = fin.get("current_ratio")
        op_consecutive = fin.get("operating_profit_consecutive", False)
        fscore = compute_fscore(fin, shares)

        quality_map[ticker] = {
            "roe": roe,
            "debt_ratio": debt_ratio,
            "current_ratio": current_ratio,
            "operating_profit_consecutive": op_consecutive,
            "piotroski_fscore": fscore,
        }

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
    market_df: pd.DataFrame,
) -> list[dict]:
    """Final selection: quality-passing stocks ranked by composite_score."""
    quality_set = set(quality_passing)
    ranked = value_scores.loc[
        [t for t in value_scores.index if t in quality_set]
    ].sort_values("composite_score")

    selected = ranked.head(SELECTION_COUNT)
    results = []

    for rank, (ticker, row) in enumerate(selected.iterrows(), start=1):
        uni_row = filtered_universe.loc[ticker] if ticker in filtered_universe.index else pd.Series()
        mrow = market_df.loc[ticker] if ticker in market_df.index else pd.Series(dtype=float)
        fin = financial_data.get(ticker, {})
        qual = quality_metrics.get(ticker, {})

        market_cap_bn = round(float(mrow.get("market_cap") or 0) / 1e8, 1)
        price = int(float(mrow.get("price") or 0))
        op_profit = fin.get("operating_profit")
        op_profit_bn = round(op_profit / 1e8, 1) if op_profit else None

        results.append({
            "rank": rank,
            "ticker": ticker,
            "name": str(mrow.get("name") or uni_row.get("name") or ""),
            "sector": str(mrow.get("sector") or uni_row.get("sector") or ""),
            "market_cap_bn_krw": market_cap_bn,
            "price": price,
            "pbr": _round2(row.get("pbr")),
            "per": _round2(row.get("per")),
            "psr": _round2(row.get("psr")),
            "pcr": _round2(row.get("pcr")),
            "composite_score": round(float(row["composite_score"]), 2),
            "pbr_rank_pct": round(float(row["pbr_rank_pct"]), 1),
            "per_rank_pct": round(float(row["per_rank_pct"]), 1),
            "psr_rank_pct": round(float(row["psr_rank_pct"]), 1),
            "pcr_rank_pct": round(float(row["pcr_rank_pct"]), 1),
            "roe_pct": _pct(qual.get("roe")),
            "debt_ratio_pct": _pct(qual.get("debt_ratio")),
            "current_ratio_pct": _pct(qual.get("current_ratio")),
            "operating_profit_bn_krw": op_profit_bn,
            "operating_profit_consecutive": bool(qual.get("operating_profit_consecutive")),
            "piotroski_fscore": qual.get("piotroski_fscore"),
            "is_new": None,
            "prev_rank": None,
        })

    return results


def _clean(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _round2(val) -> float | None:
    f = _clean(val)
    return round(f, 2) if f is not None else None


def _pct(val) -> float | None:
    f = _clean(val)
    return round(f * 100, 1) if f is not None else None
