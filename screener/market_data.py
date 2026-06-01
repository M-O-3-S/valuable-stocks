import concurrent.futures
import logging
import time
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# yfinance sector/industry strings that correspond to excluded Korean sectors
EXCLUDED_SECTORS_YF = {"Financial Services"}
EXCLUDED_INDUSTRIES_YF = {
    "Banks—Regional", "Banks—Diversified",
    "Insurance—Life", "Insurance—Property & Casualty",
    "Insurance—Diversified", "Insurance—Reinsurance",
    "Capital Markets", "Asset Management",
    "Financial Conglomerates", "Conglomerates",
}


def get_last_trading_date(max_lookback: int = 7) -> str:
    """Return the most recent KRX trading day as YYYYMMDD string."""
    for i in range(max_lookback):
        d = date.today() - timedelta(days=i)
        try:
            df = yf.download("005930.KS", period="1d", auto_adjust=True,
                             progress=False, threads=False)
            if not df.empty:
                return df.index[-1].strftime("%Y%m%d")
        except Exception:
            continue
    raise RuntimeError("Could not find a recent trading date via yfinance")


def _batch_get_prices(tickers: list[str], period: str = "5d") -> dict[str, float]:
    """Batch download latest close prices. Returns {ticker: price}."""
    prices: dict[str, float] = {}
    chunk_size = 200

    for idx in range(0, len(tickers), chunk_size):
        chunk = tickers[idx: idx + chunk_size]
        try:
            df = yf.download(chunk, period=period, auto_adjust=True,
                             progress=False, threads=False)
            if df.empty:
                time.sleep(1)
                continue

            close = df.get("Close", pd.DataFrame())
            if isinstance(close, pd.Series):
                val = close.dropna()
                if not val.empty:
                    prices[chunk[0]] = float(val.iloc[-1])
            elif isinstance(close, pd.DataFrame):
                for t in chunk:
                    if t in close.columns:
                        series = close[t].dropna()
                        if not series.empty:
                            prices[t] = float(series.iloc[-1])
        except Exception as e:
            logger.warning("Price batch chunk %d failed: %s", idx // chunk_size, e)

        time.sleep(1)

    return prices


def _fetch_fast_info(ticker: str) -> tuple[str, dict]:
    try:
        fi = yf.Ticker(ticker).fast_info
        return ticker, {
            "market_cap": getattr(fi, "market_cap", None),
            "last_price": getattr(fi, "last_price", None),
        }
    except Exception:
        return ticker, {}


def _fetch_full_info(ticker: str) -> tuple[str, dict]:
    try:
        info = yf.Ticker(ticker).info
        return ticker, {
            "market_cap": info.get("marketCap"),
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "pbr": info.get("priceToBook"),
            "per": info.get("trailingPE"),
            "psr": info.get("priceToSalesTrailing12Months"),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "name": info.get("longName") or info.get("shortName", ""),
            "shares": info.get("sharesOutstanding"),
        }
    except Exception:
        return ticker, {}


def _parallel_fetch(tickers: list[str], fetch_fn, max_workers: int = 5) -> dict[str, dict]:
    results: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for ticker, data in executor.map(fetch_fn, tickers):
            if data:
                results[ticker] = data
    return results


def build_market_dataframe(dart_stock_codes: list[str], universe_size: int = 300) -> pd.DataFrame:
    """
    Build a DataFrame of KOSPI stocks with market data from yfinance.

    Steps:
      1. Batch-download prices for all DART codes with .KS suffix
         → identifies which are KOSPI-listed
      2. Get market caps via fast_info for price-positive tickers
      3. Take top universe_size by market cap
      4. Get full yfinance info (PBR, PER, PSR, sector, name) for those top stocks

    Returns DataFrame indexed by 6-digit ticker with columns:
      name, market_cap, price, pbr, per, psr, sector, industry, shares, ticker_yf
    """
    all_yf = [f"{c}.KS" for c in dart_stock_codes if c.strip()]
    logger.info("Step 1: Batch price check for %d KOSPI candidates...", len(all_yf))

    prices = _batch_get_prices(all_yf)
    active_yf = [t for t, p in prices.items() if p and p > 0]
    logger.info("  → %d active tickers with prices", len(active_yf))

    logger.info("Step 2: Getting market caps via fast_info for %d tickers...", len(active_yf))
    fast_data = _parallel_fetch(active_yf, _fetch_fast_info, max_workers=8)

    # Sort by market cap, take top candidates
    mc_list = [
        (t, (fast_data[t].get("market_cap") or 0))
        for t in active_yf if t in fast_data
    ]
    mc_list.sort(key=lambda x: x[1], reverse=True)
    top_yf = [t for t, mc in mc_list if mc > 0][: universe_size * 2]
    logger.info("  → Top %d by market cap selected for full info", len(top_yf))

    logger.info("Step 3: Getting full info (PBR/PER/PSR/sector) for top tickers...")
    full_data = _parallel_fetch(top_yf, _fetch_full_info, max_workers=5)

    records = []
    for yf_ticker in top_yf:
        info = full_data.get(yf_ticker, {})
        mc = info.get("market_cap") or fast_data.get(yf_ticker, {}).get("market_cap") or 0
        price = info.get("price") or fast_data.get(yf_ticker, {}).get("last_price") or 0
        if mc <= 0 or price <= 0:
            continue
        code = yf_ticker.replace(".KS", "")
        records.append({
            "ticker": code,
            "ticker_yf": yf_ticker,
            "name": info.get("name") or code,
            "market_cap": mc,
            "price": price,
            "pbr": info.get("pbr"),
            "per": info.get("per"),
            "psr": info.get("psr"),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "shares": info.get("shares"),
        })

    df = pd.DataFrame(records).set_index("ticker")
    df = df.sort_values("market_cap", ascending=False)
    logger.info("Market dataframe: %d stocks", len(df))
    return df


def get_suspended_tickers(date_str: str) -> set[str]:
    return set()
