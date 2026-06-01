import logging
from datetime import date, timedelta

import pandas as pd
from pykrx import stock as pykrx_stock

logger = logging.getLogger(__name__)


def get_last_trading_date(max_lookback: int = 7) -> str:
    today = date.today()
    for i in range(max_lookback):
        candidate = today - timedelta(days=i)
        d = candidate.strftime("%Y%m%d")
        try:
            df = pykrx_stock.get_market_ohlcv_by_date(d, d, "005930")
            if not df.empty:
                return d
        except Exception:
            continue
    raise RuntimeError("Could not find a recent trading date")


def get_market_caps(date_str: str) -> pd.DataFrame:
    """Return DataFrame with ticker, market_cap, shares for KOSPI."""
    df = pykrx_stock.get_market_cap_by_ticker(date_str, market="KOSPI")
    df = df.rename(columns={"시가총액": "market_cap", "상장주식수": "shares"})
    df.index.name = "ticker"
    return df[["market_cap", "shares"]].copy()


def get_fundamentals(date_str: str) -> pd.DataFrame:
    """Return PBR, PER, BPS, EPS, DIV for all KOSPI tickers."""
    df = pykrx_stock.get_market_fundamental_by_ticker(date_str, market="KOSPI")
    df.index.name = "ticker"
    df = df.rename(columns={
        "BPS": "bps",
        "PER": "per",
        "PBR": "pbr",
        "EPS": "eps",
        "DIV": "div_yield",
        "DPS": "dps",
    })
    return df


def get_closing_prices(date_str: str) -> pd.Series:
    """Return Series of closing prices indexed by ticker for KOSPI."""
    df = pykrx_stock.get_market_ohlcv_by_ticker(date_str, market="KOSPI")
    if "종가" in df.columns:
        return df["종가"].rename("price")
    return pd.Series(dtype=float, name="price")


def get_suspended_tickers(date_str: str) -> set[str]:
    """Return set of tickers currently under trading suspension."""
    try:
        df = pykrx_stock.get_market_trading_suspension_by_ticker(date_str, market="KOSPI")
        if df is not None and not df.empty:
            return set(df.index.tolist())
    except Exception as e:
        logger.warning("Could not fetch suspended tickers: %s", e)
    return set()


def get_sector_classifications(date_str: str) -> pd.DataFrame:
    """Return DataFrame with ticker and sector (업종) for KOSPI."""
    try:
        df = pykrx_stock.get_market_sector_classifications(date_str, market="KOSPI")
        df.index.name = "ticker"
        if "업종명" in df.columns:
            return df[["업종명"]].rename(columns={"업종명": "sector"})
        # Try alternate column names
        for col in df.columns:
            if "업종" in col or "sector" in col.lower():
                return df[[col]].rename(columns={col: "sector"})
    except Exception as e:
        logger.warning("Could not fetch sector data: %s", e)
    return pd.DataFrame(columns=["sector"])


def get_ticker_names(date_str: str) -> pd.Series:
    """Return Series mapping ticker → company name."""
    try:
        tickers = pykrx_stock.get_market_ticker_list(date_str, market="KOSPI")
        names = {t: pykrx_stock.get_market_ticker_name(t) for t in tickers}
        return pd.Series(names, name="name")
    except Exception as e:
        logger.warning("Could not fetch ticker names: %s", e)
        return pd.Series(dtype=str, name="name")
