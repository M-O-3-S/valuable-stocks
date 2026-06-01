#!/usr/bin/env python3
"""
Diagnostic script for CI — tests each data source independently.
Run before the main screener to pinpoint failures quickly.
"""
import os
import sys
import zipfile
import io
import json

def check(label, ok, detail=""):
    status = "OK" if ok else "FAIL"
    print(f"  [{status}] {label}" + (f": {detail}" if detail else ""))
    return ok


def test_dart_api_key():
    import requests
    key = os.environ.get("DART_API_KEY", "")
    if not key:
        check("DART_API_KEY env var", False, "not set")
        return False

    check("DART_API_KEY env var", True, f"length={len(key)}")

    print("  Downloading DART corpCode.xml...")
    try:
        resp = requests.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={"crtfc_key": key},
            timeout=30,
        )
        check("DART HTTP status", resp.status_code == 200, f"status={resp.status_code}")
        if resp.status_code != 200:
            return False

        content_type = resp.headers.get("Content-Type", "")
        # DART returns application/zip on success, application/json on auth error
        if "json" in content_type or resp.content[:1] == b"{":
            try:
                body = resp.json()
                check("DART API key valid", False,
                      f"API error: status={body.get('status')} message={body.get('message')}")
            except Exception:
                check("DART API key valid", False, "unexpected response (not zip, not json)")
            return False

        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                names = zf.namelist()
            check("DART corpCode.xml download", True, f"zip contains: {names}")
            return True
        except zipfile.BadZipFile:
            check("DART corpCode.xml download", False,
                  f"response is not a zip file (content starts with: {resp.content[:50]})")
            return False

    except requests.Timeout:
        check("DART API connectivity", False, "timeout after 30s")
        return False
    except requests.RequestException as e:
        check("DART API connectivity", False, str(e))
        return False


def test_fdr():
    try:
        import FinanceDataReader as fdr
        check("FinanceDataReader import", True)
    except ImportError as e:
        check("FinanceDataReader import", False, str(e))
        return False

    try:
        df = fdr.StockListing("KOSPI")
        ok = df is not None and not df.empty
        check("FDR KOSPI listing", ok,
              f"rows={len(df)} cols={df.columns.tolist()}" if ok else "empty")
        return ok
    except Exception as e:
        check("FDR KOSPI listing", False, str(e))
        return False


def test_yfinance():
    try:
        import yfinance as yf
        check("yfinance import", True)
    except ImportError as e:
        check("yfinance import", False, str(e))
        return False

    try:
        # Test batch download (primary method)
        df = yf.download("005380.KS", period="5d", auto_adjust=True,
                         progress=False, threads=False)
        ok = not df.empty
        price = float(df["Close"].dropna().iloc[-1]) if ok else None
        check("yfinance batch download (Samsung)", ok, f"price={price}")
        if ok:
            return True
    except Exception as e:
        check("yfinance batch download", False, str(e))

    try:
        import yfinance as yf
        fi = yf.Ticker("005380.KS").fast_info
        mc = getattr(fi, "market_cap", None)
        check("yfinance fast_info (Samsung)", bool(mc), f"market_cap={mc}")
        return bool(mc)
    except Exception as e:
        check("yfinance fast_info", False, str(e))
        return False


def main():
    print("=" * 50)
    print("Screener Diagnostics")
    print("=" * 50)

    results = {}

    print("\n[1] DART API")
    results["dart"] = test_dart_api_key()

    print("\n[2] FinanceDataReader (KRX native — primary source)")
    results["fdr"] = test_fdr()

    print("\n[3] yfinance (Yahoo Finance — fallback source)")
    results["yfinance"] = test_yfinance()

    print("\n" + "=" * 50)
    if not results["dart"]:
        print("CRITICAL: DART API is not working. Check DART_API_KEY secret.")
        sys.exit(1)
    if not results["fdr"] and not results["yfinance"]:
        print("CRITICAL: Neither FinanceDataReader nor yfinance can fetch market data.")
        sys.exit(1)
    if results["fdr"]:
        print("Market data source: FinanceDataReader (KRX native) ✓")
    else:
        print("Market data source: yfinance (fallback) — FDR unavailable")
    print("Diagnostics passed. Proceeding with screener.")
    sys.exit(0)


if __name__ == "__main__":
    main()
