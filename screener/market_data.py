"""
Market data layer with two-tier fallback:
  1. FinanceDataReader (KRX native, preferred)
  2. yfinance (Yahoo Finance, fallback)
"""
import concurrent.futures
import logging
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

EXCLUDED_SECTORS_YF = {"Financial Services"}
EXCLUDED_INDUSTRIES_YF = {
    "Banks—Regional", "Banks—Diversified",
    "Insurance—Life", "Insurance—Property & Casualty",
    "Insurance—Diversified", "Insurance—Reinsurance",
    "Capital Markets", "Asset Management",
    "Financial Conglomerates", "Conglomerates",
}
# Korean sector strings from FinanceDataReader / KRX
EXCLUDED_SECTORS_KR = {
    "은행", "증권", "보험", "기타금융", "금융지주", "지주회사",
}


# ── FinanceDataReader path ─────────────────────────────────────────────────

def _try_fdr_listing() -> pd.DataFrame | None:
    """
    Use FinanceDataReader to get KOSPI listing with market cap and sector.
    Returns DataFrame indexed by 6-digit ticker, or None on failure.
    Columns: name, market_cap, price, sector
    """
    try:
        import FinanceDataReader as fdr
        logger.info("[FDR] Fetching KOSPI listing...")
        df = fdr.StockListing("KOSPI")
        if df is None or df.empty:
            logger.warning("[FDR] Empty listing returned")
            return None

        logger.info("[FDR] Raw columns: %s", df.columns.tolist())

        # Normalise column names (FDR column names vary by version)
        col_map = {}
        for c in df.columns:
            lc = c.lower()
            if lc in ("code", "symbol", "ticker"):
                col_map[c] = "ticker"
            elif lc in ("name", "company", "corp_name", "종목명"):
                col_map[c] = "name"
            elif "cap" in lc or "mktcap" in lc or "시가총액" in lc:
                col_map[c] = "market_cap"
            elif lc in ("close", "price", "종가", "현재가"):
                col_map[c] = "price"
            elif "sector" in lc or "업종" in lc or "industry" in lc:
                col_map[c] = "sector"
        df = df.rename(columns=col_map)

        # If ticker is a column, make it the index
        if "ticker" in df.columns:
            df = df.set_index("ticker")
        df.index = df.index.astype(str).str.zfill(6)

        # Ensure market_cap exists
        if "market_cap" not in df.columns:
            logger.warning("[FDR] No market_cap column after mapping; available: %s", df.columns.tolist())
            return None

        df["market_cap"] = pd.to_numeric(df["market_cap"], errors="coerce")
        df = df[df["market_cap"].notna() & (df["market_cap"] > 0)]

        # Add pbr/per/psr as NaN (FDR listing doesn't include them; computed later)
        for col in ("pbr", "per", "psr", "shares"):
            if col not in df.columns:
                df[col] = np.nan

        if "price" not in df.columns:
            df["price"] = np.nan
        if "sector" not in df.columns:
            df["sector"] = ""

        df["industry"] = ""
        df["ticker_yf"] = df.index + ".KS"

        logger.info("[FDR] Listing OK: %d KOSPI stocks", len(df))
        return df[["name", "market_cap", "price", "pbr", "per", "psr",
                   "sector", "industry", "shares", "ticker_yf"]]

    except Exception as e:
        logger.warning("[FDR] Failed: %s", e)
        return None


def _fdr_enrich_fundamentals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Attempt to enrich PBR/PER/PSR using FDR for the top-N tickers.
    If FDR doesn't provide fundamentals, returns df unchanged.
    """
    # FDR StockListing for KRX may include BPS/PER/PBR in newer versions
    try:
        import FinanceDataReader as fdr
        # Some FDR versions return PER/PBR directly
        raw = fdr.StockListing("KRX")
        if raw is None or raw.empty:
            return df

        # Normalise
        col_map = {}
        for c in raw.columns:
            lc = c.lower()
            if lc in ("code", "symbol"):
                col_map[c] = "ticker"
            elif "per" == lc:
                col_map[c] = "per"
            elif "pbr" == lc:
                col_map[c] = "pbr"
            elif "psr" == lc:
                col_map[c] = "psr"
        raw = raw.rename(columns=col_map)
        if "ticker" in raw.columns:
            raw = raw.set_index("ticker")
        raw.index = raw.index.astype(str).str.zfill(6)

        for col in ("per", "pbr", "psr"):
            if col in raw.columns:
                raw[col] = pd.to_numeric(raw[col], errors="coerce")
                df[col] = df[col].fillna(raw[col].reindex(df.index))

        logger.info("[FDR] Fundamentals enriched")
    except Exception as e:
        logger.debug("[FDR] Fundamentals enrichment skipped: %s", e)
    return df


# ── yfinance path ──────────────────────────────────────────────────────────

def _try_yfinance_listing(dart_stock_codes: list[str]) -> pd.DataFrame | None:
    """
    Use yfinance to build market listing for KOSPI stocks.
    Returns DataFrame indexed by 6-digit ticker, or None on failure.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("[YF] yfinance not installed")
        return None

    all_yf = [f"{c}.KS" for c in dart_stock_codes if c.strip()]
    logger.info("[YF] Batch price download for %d tickers...", len(all_yf))

    prices: dict[str, float] = {}
    chunk_size = 200
    for idx in range(0, len(all_yf), chunk_size):
        chunk = all_yf[idx: idx + chunk_size]
        try:
            dl = yf.download(chunk, period="5d", auto_adjust=True,
                             progress=False, threads=False)
            if dl.empty:
                time.sleep(1)
                continue
            close = dl.get("Close", pd.DataFrame())
            if isinstance(close, pd.Series):
                v = close.dropna()
                if not v.empty:
                    prices[chunk[0]] = float(v.iloc[-1])
            elif isinstance(close, pd.DataFrame):
                for t in chunk:
                    if t in close.columns:
                        s = close[t].dropna()
                        if not s.empty:
                            prices[t] = float(s.iloc[-1])
        except Exception as e:
            logger.warning("[YF] Chunk %d failed: %s", idx // chunk_size, e)
        time.sleep(1)

    active = [t for t, p in prices.items() if p and p > 0]
    logger.info("[YF] %d active tickers with prices", len(active))
    if not active:
        return None

    # Fast market-cap lookup
    def _fast_mc(ticker):
        try:
            fi = yf.Ticker(ticker).fast_info
            return ticker, getattr(fi, "market_cap", None)
        except Exception:
            return ticker, None

    logger.info("[YF] Getting market caps via fast_info...")
    mc_map: dict[str, float] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for t, mc in ex.map(_fast_mc, active):
            if mc and mc > 0:
                mc_map[t] = mc

    if not mc_map:
        return None

    sorted_tickers = sorted(mc_map, key=lambda t: mc_map[t], reverse=True)[:600]

    # Full .info for top candidates
    FIELDS = ["marketCap", "currentPrice", "priceToBook", "trailingPE",
              "priceToSalesTrailing12Months", "sector", "industry",
              "longName", "shortName", "sharesOutstanding"]

    def _full_info(ticker):
        try:
            info = yf.Ticker(ticker).info
            return ticker, {f: info.get(f) for f in FIELDS}
        except Exception:
            return ticker, {}

    logger.info("[YF] Getting full info for %d tickers...", len(sorted_tickers))
    info_map: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        for t, d in ex.map(_full_info, sorted_tickers):
            if d:
                info_map[t] = d

    records = []
    for yf_ticker in sorted_tickers:
        info = info_map.get(yf_ticker, {})
        mc = info.get("marketCap") or mc_map.get(yf_ticker, 0)
        price = info.get("currentPrice") or prices.get(yf_ticker, 0)
        if not mc or not price:
            continue
        code = yf_ticker.replace(".KS", "")
        records.append({
            "ticker": code,
            "ticker_yf": yf_ticker,
            "name": info.get("longName") or info.get("shortName") or code,
            "market_cap": mc,
            "price": price,
            "pbr": info.get("priceToBook"),
            "per": info.get("trailingPE"),
            "psr": info.get("priceToSalesTrailing12Months"),
            "sector": info.get("sector") or "",
            "industry": info.get("industry") or "",
            "shares": info.get("sharesOutstanding"),
        })

    if not records:
        return None

    df = pd.DataFrame(records).set_index("ticker")
    df = df.sort_values("market_cap", ascending=False)
    logger.info("[YF] Listing OK: %d stocks", len(df))
    return df


# ── public API ─────────────────────────────────────────────────────────────

def build_market_dataframe(dart_stock_codes: list[str]) -> pd.DataFrame:
    """
    Build market DataFrame, trying FDR first then yfinance.
    Returns DataFrame indexed by 6-digit ticker.
    """
    # 1st: FinanceDataReader (KRX native)
    df = _try_fdr_listing()
    if df is not None and len(df) >= 100:
        df = _fdr_enrich_fundamentals(df)
        return df

    logger.warning("FDR failed or returned too few rows — falling back to yfinance")

    # 2nd: yfinance
    df = _try_yfinance_listing(dart_stock_codes)
    if df is not None and len(df) >= 50:
        return df

    logger.error("Both FDR and yfinance failed to return market data")
    return pd.DataFrame()


def get_last_trading_date(max_lookback: int = 7) -> str:
    """Return the most recent trading day as YYYYMMDD, trying FDR then yfinance."""
    # Try FDR
    try:
        import FinanceDataReader as fdr
        for i in range(max_lookback):
            d = (date.today() - timedelta(days=i)).strftime("%Y%m%d")
            try:
                df = fdr.DataReader("005930", d, d)
                if not df.empty:
                    logger.info("[FDR] Last trading date: %s", d)
                    return d
            except Exception:
                continue
    except ImportError:
        pass

    # Fallback: yfinance
    try:
        import yfinance as yf
        df = yf.download("005930.KS", period="5d", auto_adjust=True,
                         progress=False, threads=False)
        if not df.empty:
            d = df.index[-1].strftime("%Y%m%d")
            logger.info("[YF] Last trading date: %s", d)
            return d
    except Exception as e:
        logger.warning("[YF] get_last_trading_date failed: %s", e)

    raise RuntimeError("Could not determine last trading date from FDR or yfinance")


def get_suspended_tickers(date_str: str) -> set[str]:
    return set()
