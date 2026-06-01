import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from screener.config import OUTPUT_PATH

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def _load_previous(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def build_output(
    stocks: list[dict],
    exclusion_log: dict[str, list[str]],
    meta_extra: dict[str, Any],
) -> dict:
    """Build the full output JSON structure."""
    prev = _load_previous(OUTPUT_PATH)

    # Changelog
    prev_tickers = {s["ticker"] for s in (prev or {}).get("stocks", [])}
    prev_rank_map = {s["ticker"]: s["rank"] for s in (prev or {}).get("stocks", [])}
    curr_tickers = {s["ticker"] for s in stocks}

    entered = sorted(curr_tickers - prev_tickers)
    exited = sorted(prev_tickers - curr_tickers)

    # Annotate is_new and prev_rank
    for s in stocks:
        s["is_new"] = s["ticker"] in entered
        s["prev_rank"] = prev_rank_map.get(s["ticker"])

    now_kst = datetime.now(KST)
    output = {
        "meta": {
            "generated_at": now_kst.isoformat(),
            "data_as_of": meta_extra.get("data_as_of", ""),
            "fiscal_year": meta_extra.get("fiscal_year"),
            "universe_size": meta_extra.get("universe_size", 0),
            "survived_filters": meta_extra.get("survived_filters", 0),
            "quality_passed": meta_extra.get("quality_passed", 0),
            "selected_count": len(stocks),
            "screener_version": "1.0.0",
            "next_rebalance": _next_rebalance(meta_extra.get("fiscal_year")),
            "warnings": meta_extra.get("warnings", []),
        },
        "stocks": stocks,
        "excluded": exclusion_log,
        "changelog": {
            "entered": entered,
            "exited": exited,
        },
    }
    return output


def write_output(output: dict, dry_run: bool = False) -> None:
    path = Path(OUTPUT_PATH)
    json_str = json.dumps(output, ensure_ascii=False, indent=2)

    if dry_run:
        logger.info("[dry-run] Would write %d bytes to %s", len(json_str), path)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json_str)
    logger.info("Wrote %d bytes to %s", len(json_str), path)


def _next_rebalance(fiscal_year: int | None) -> str:
    if fiscal_year is None:
        return ""
    return f"{fiscal_year + 2}-04"
