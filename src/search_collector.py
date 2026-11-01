#!/usr/bin/env python3
"""Collect and export DuckDuckGo text-search results.

This tool collects search-result metadata only. It does not crawl or download
the pages referenced by result URLs.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ddgs import DDGS

LOGGER = logging.getLogger("ddg_collector")
ALLOWED_LIMITS = {10, 30, 50, 100, 200, 500}
DEFAULT_REGION = "in-en"
DEFAULT_SAFESEARCH = "moderate"
SEARCH_ENGINE = "DuckDuckGo"

CSV_FIELDS = [
    "rank",
    "title",
    "url",
    "domain",
    "snippet",
    "query",
    "region",
    "search_engine",
    "collected_at",
]


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str) -> str:
    """Remove fragments and trailing whitespace without changing query strings."""
    candidate = (url or "").strip()
    if not candidate:
        return ""

    parts = urlsplit(candidate)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""

    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, "")
    )


def extract_domain(url: str) -> str:
    """Return the hostname for a URL, or an empty string if it is invalid."""
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def normalize_result(
    item: dict[str, Any],
    rank: int,
    query: str,
    region: str,
    collected_at: str,
) -> dict[str, Any] | None:
    """Convert a DDGS result dictionary into the stable output schema."""
    url = normalize_url(str(item.get("href") or item.get("url") or ""))
    if not url:
        return None

    return {
        "rank": rank,
        "title": str(item.get("title") or "").strip(),
        "url": url,
        "domain": extract_domain(url),
        "snippet": str(item.get("body") or item.get("snippet") or "").strip(),
        "query": query,
        "region": region,
        "search_engine": SEARCH_ENGINE,
        "collected_at": collected_at,
    }


def collect_results(
    query: str,
    limit: int,
    region: str = DEFAULT_REGION,
    retries: int = 3,
    retry_delay: float = 2.0,
) -> list[dict[str, Any]]:
    """Fetch up to ``limit`` unique HTTP(S) results from DuckDuckGo.

    A single DDGS request is made with ``max_results=limit``. The result count
    may be lower than requested because the provider can return fewer results,
    throttle requests, or change its response behaviour.
    """
    if limit not in ALLOWED_LIMITS:
        raise ValueError(f"limit must be one of {sorted(ALLOWED_LIMITS)}")
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    if retries < 1:
        raise ValueError("retries must be at least 1")

    last_error: Exception | None = None
    raw_results = None

    for attempt in range(1, retries + 1):
        try:
            LOGGER.info(
                "DuckDuckGo request: query=%r limit=%d region=%s attempt=%d/%d",
                query, limit, region, attempt, retries
            )
            client = DDGS()
            raw_results = client.text(
                query,
                region=region,
                safesearch=DEFAULT_SAFESEARCH,
                max_results=limit,
                backend="duckduckgo",
            )
            break
        except Exception as exc:  # Provider/library exceptions can vary by version.
            last_error = exc
            LOGGER.warning("Search attempt %d failed: %s", attempt, exc)
            if attempt < retries:
                time.sleep(retry_delay * attempt)

    if raw_results is None:
        raise RuntimeError(f"DuckDuckGo search failed after {retries} attempts") from last_error

    collected_at = utc_now()
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for item in raw_results:
        if not isinstance(item, dict):
            continue
        normalized = normalize_result(
            item, len(results) + 1, query, region, collected_at
        )
        if normalized is None or normalized["url"] in seen_urls:
            continue
        seen_urls.add(normalized["url"])
        results.append(normalized)
        if len(results) >= limit:
            break

    return results


def write_json(results: list[dict[str, Any]], output_dir: Path) -> Path:
    path = output_dir / "search_results.json"
    path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def write_csv(results: list[dict[str, Any]], output_dir: Path) -> Path:
    path = output_dir / "search_results.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    return path


def write_summary(
    output_dir: Path,
    query: str,
    limit: int,
    region: str,
    results: list[dict[str, Any]],
    status: str = "SUCCESS",
    error: str = "",
) -> Path:
    path = output_dir / "summary.txt"
    lines = [
        "DUCKDUCKGO SEARCH COLLECTION REPORT",
        "=" * 38,
        f"Status             : {status}",
        f"Search query       : {query}",
        f"Search engine      : {SEARCH_ENGINE}",
        f"Region             : {region}",
        f"Requested maximum  : {limit}",
        f"Unique results     : {len(results)}",
        f"Collected at (UTC) : {utc_now()}",
        "",
        "Output files:",
        "- search_results.json",
        "- search_results.csv",
        "- summary.txt",
        "",
        "Notes:",
        "- Results are search-result metadata, not downloaded webpage content.",
        "- The provider may return fewer results than requested.",
    ]
    if error:
        lines.extend(["", f"Error: {error}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect DuckDuckGo text-search results into JSON and CSV."
    )
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument(
        "--limit",
        required=True,
        type=int,
        choices=sorted(ALLOWED_LIMITS),
        help="Maximum number of unique results",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        choices=["in-en", "us-en", "uk-en", "wt-wt"],
        help="DuckDuckGo region (default: in-en)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs"),
        help="Output directory (default: outputs)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    query = args.query.strip()
    args.output.mkdir(parents=True, exist_ok=True)

    if not query:
        LOGGER.error("Search query cannot be empty.")
        write_json([], args.output)
        write_csv([], args.output)
        write_summary(args.output, query, args.limit, args.region, [], "FAILED",
                      "Search query cannot be empty.")
        return 2

    try:
        results = collect_results(query, args.limit, args.region)
        write_json(results, args.output)
        write_csv(results, args.output)
        write_summary(args.output, query, args.limit, args.region, results)
        LOGGER.info("Completed: requested=%d collected=%d", args.limit, len(results))
        return 0
    except Exception as exc:
        LOGGER.exception("Collection failed")
        # Keep machine-readable empty outputs and a failure report for artifacts.
        write_json([], args.output)
        write_csv([], args.output)
        write_summary(
            args.output, query, args.limit, args.region, [], "FAILED", str(exc)
        )
        return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    sys.exit(main())
