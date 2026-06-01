import io
import logging
import os
import time
import xml.etree.ElementTree as ET
import zipfile

import requests

from screener.config import DART_BASE_URL

logger = logging.getLogger(__name__)

_corp_code_map: dict[str, str] = {}


class DartApiError(Exception):
    pass


def _get_api_key() -> str:
    key = os.environ.get("DART_API_KEY", "")
    if not key:
        raise DartApiError("DART_API_KEY environment variable is not set")
    return key


def _request(url: str, params: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** attempt * 2
                logger.warning("DART rate limited, waiting %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") not in ("000", None):
                raise DartApiError(f"DART API error: {data.get('status')} {data.get('message')}")
            return data
        except (requests.RequestException, DartApiError) as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            logger.warning("Request failed (%s), retrying in %ds", e, wait)
            time.sleep(wait)
    raise DartApiError("Max retries exceeded")


def load_corp_code_map() -> dict[str, str]:
    global _corp_code_map
    if _corp_code_map:
        return _corp_code_map

    api_key = _get_api_key()
    logger.info("Downloading DART corpCode.xml...")
    try:
        resp = requests.get(
            f"{DART_BASE_URL}/corpCode.xml",
            params={"crtfc_key": api_key},
            timeout=60,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise DartApiError(f"Failed to download corpCode.xml: {e}") from e

    # DART returns JSON (with error status) if API key is invalid
    content_type = resp.headers.get("Content-Type", "")
    if "json" in content_type or resp.content[:1] == b"{":
        try:
            body = resp.json()
            raise DartApiError(
                f"DART API key rejected: status={body.get('status')} "
                f"message={body.get('message')} "
                f"(Check that DART_API_KEY secret is correct)"
            )
        except (ValueError, KeyError):
            raise DartApiError(f"Unexpected DART response (not zip): {resp.content[:100]}")

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_bytes = zf.read("CORPCODE.xml")
    except zipfile.BadZipFile as e:
        raise DartApiError(
            f"corpCode.xml response is not a valid zip file. "
            f"Content starts with: {resp.content[:80]!r}"
        ) from e

    root = ET.fromstring(xml_bytes)
    result: dict[str, str] = {}
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code = (item.findtext("corp_code") or "").strip()
        if stock_code:
            result[stock_code] = corp_code

    _corp_code_map = result
    logger.info("Loaded %d corp codes", len(result))
    return result


def get_corp_code(stock_code: str) -> str | None:
    code_map = load_corp_code_map()
    return code_map.get(stock_code)


def get_company_info(corp_code: str) -> dict:
    api_key = _get_api_key()
    data = _request(
        f"{DART_BASE_URL}/company.json",
        {"crtfc_key": api_key, "corp_code": corp_code},
    )
    return data


def get_single_acnt(
    corp_code: str,
    year: int,
    report_type: str = "11011",
    fs_div: str = "CFS",
) -> list[dict]:
    """Fetch financial statement accounts from DART.

    report_type: 11011=annual, 11012=Q1, 11013=H1, 11014=Q3
    fs_div: CFS=consolidated, OFS=standalone
    """
    api_key = _get_api_key()
    time.sleep(0.7)
    try:
        data = _request(
            f"{DART_BASE_URL}/fnlttSinglAcnt.json",
            {
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": report_type,
                "fs_div": fs_div,
            },
        )
        return data.get("list", [])
    except DartApiError as e:
        if fs_div == "CFS":
            logger.debug("CFS not available for %s, trying OFS: %s", corp_code, e)
            return get_single_acnt(corp_code, year, report_type, fs_div="OFS")
        logger.warning("DART fetch failed for %s year=%d: %s", corp_code, year, e)
        return []
