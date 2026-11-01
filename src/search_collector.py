#!/usr/bin/env python3
"""Paginated DuckDuckGo collector with raw-page preservation and deduplication."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

try:
    from ddgs import DDGS
except ImportError:  # Allows unit tests to run without installing the provider package.
    DDGS = None  # type: ignore[assignment,misc]

LOGGER = logging.getLogger("ddg_collector")
ALLOWED_LIMITS = {10, 30, 50, 100, 200, 500}
PROVIDER_PAGE_SIZE = 10
DEFAULT_REGION = "in-en"
DEFAULT_SAFESEARCH = "moderate"
SEARCH_ENGINE = "DuckDuckGo"
DEFAULT_MAX_PAGES = 60

CSV_FIELDS = [
    "rank", "title", "url", "domain", "snippet", "query",
    "region", "search_engine", "collected_at",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str) -> str:
    """Normalize scheme/host and remove fragments; retain path and query."""
    candidate = (url or "").strip()
    if not candidate:
        return ""
    try:
        parts = urlsplit(candidate)
        if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
            return ""
        return urlunsplit((
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path or "",
            parts.query,
            "",
        ))
    except ValueError:
        return ""


def extract_domain(url: str) -> str:
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def clean_results(
    raw_results: list[dict[str, Any]],
    query: str,
    region: str,
    collected_at: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Normalize and deduplicate a flattened collection of raw result objects."""
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in raw_results:
        if not isinstance(item, dict):
            continue
        raw_url = str(item.get("href") or item.get("url") or "")
        url = normalize_url(raw_url)
        if not url or url in seen:
            continue

        seen.add(url)
        cleaned.append({
            "rank": len(cleaned) + 1,
            "title": str(item.get("title") or "").strip(),
            "url": url,
            "domain": extract_domain(url),
            "snippet": str(item.get("body") or item.get("snippet") or "").strip(),
            "query": query,
            "region": region,
            "search_engine": SEARCH_ENGINE,
            "collected_at": collected_at,
        })
        if len(cleaned) >= limit:
            break
    return cleaned


def _page_fingerprint(items: list[dict[str, Any]]) -> tuple[str, ...]:
    """Stable fingerprint used to detect providers repeating the same page."""
    values = []
    for item in items:
        url = normalize_url(str(item.get("href") or item.get("url") or ""))
        values.append(url or json.dumps(item, sort_keys=True, default=str))
    return tuple(values)


def fetch_paginated_results(
    query: str,
    limit: int,
    region: str = DEFAULT_REGION,
    page_size: int = PROVIDER_PAGE_SIZE,
    max_pages: int | None = None,
    retries: int = 3,
    retry_base_seconds: float = 2.0,
    page_delay_seconds: float = 1.0,
) -> dict[str, Any]:
    """Collect pages until target, exhaustion, repeated pages, or a safety cap.

    DDGS/DuckDuckGo is queried in conservative batches of 10. A short page is
    not treated as exhaustion: pagination continues until an empty/repeated page,
    duplicate-only streak, requested unique-result target, or safety cap.

    A later-page failure returns a partial collection with a recorded error;
    a first-page failure raises because no useful result set was obtained.
    """
    if limit not in ALLOWED_LIMITS:
        raise ValueError(f"limit must be one of {sorted(ALLOWED_LIMITS)}")
    if page_size != PROVIDER_PAGE_SIZE:
        raise ValueError(f"DuckDuckGo provider page_size is fixed at {PROVIDER_PAGE_SIZE}")
    if not query.strip():
        raise ValueError("query must not be empty")
    if retries < 1:
        raise ValueError("retries must be at least 1")
    if DDGS is None:
        raise RuntimeError("Missing dependency: install requirements.txt (ddgs).")

    # DDGS/DuckDuckGo commonly returns at most 10 items per page even when a
    # larger max_results value is requested. Keep requests aligned with that cap.
    # Allow extra pages to compensate for duplicates and short pages.
    calculated_cap = math.ceil(limit / PROVIDER_PAGE_SIZE) * 3 + 2
    page_cap = min(max_pages or calculated_cap, DEFAULT_MAX_PAGES)

    client = DDGS(timeout=20)
    pages: list[dict[str, Any]] = []
    flattened_raw: list[dict[str, Any]] = []
    unique_urls: set[str] = set()
    previous_fingerprints: set[tuple[str, ...]] = set()
    duplicate_only_streak = 0
    stop_reason = "page_cap_reached"
    page_errors: list[dict[str, Any]] = []

    for page_number in range(1, page_cap + 1):
        page_items: list[dict[str, Any]] | None = None
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                LOGGER.info(
                    "Fetching page %d/%d | batch_size=%d | attempt=%d/%d",
                    page_number, page_cap, page_size, attempt, retries
                )
                response = client.text(
                    query,
                    region=region,
                    safesearch=DEFAULT_SAFESEARCH,
                    max_results=page_size,
                    page=page_number,
                    backend="duckduckgo",
                )
                page_items = list(response or [])
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                LOGGER.warning(
                    "Page %d attempt %d failed: %s",
                    page_number, attempt, exc, exc_info=True
                )
                if attempt < retries:
                    wait = retry_base_seconds * (2 ** (attempt - 1))
                    LOGGER.info("Retrying page %d in %.1f seconds.", page_number, wait)
                    time.sleep(wait)

        if page_items is None:
            error_text = repr(last_error)
            page_errors.append({"page": page_number, "error": error_text})
            LOGGER.error("Page %d exhausted retries.", page_number)
            if page_number == 1:
                raise RuntimeError(
                    f"DuckDuckGo first page failed after {retries} attempts: {error_text}"
                ) from last_error
            stop_reason = "later_page_failed_partial_results"
            break

        fingerprint = _page_fingerprint(page_items)
        page_new = 0

        for item in page_items:
            if isinstance(item, dict):
                flattened_raw.append(item)
                url = normalize_url(str(item.get("href") or item.get("url") or ""))
                if url and url not in unique_urls:
                    unique_urls.add(url)
                    page_new += 1

        pages.append({
            "page": page_number,
            "requested_batch_size": page_size,
            "returned_count": len(page_items),
            "new_unique_url_count": page_new,
            "results": page_items,
        })

        LOGGER.info(
            "Page %d complete | raw=%d | new_unique_urls=%d | total_raw=%d | total_unique=%d",
            page_number, len(page_items), page_new,
            len(flattened_raw), len(unique_urls)
        )

        if len(unique_urls) >= limit:
            stop_reason = "requested_unique_result_limit_reached"
            break
        if not page_items:
            stop_reason = "provider_returned_empty_page"
            break
        if fingerprint and fingerprint in previous_fingerprints:
            stop_reason = "provider_repeated_page"
            LOGGER.warning("Page %d repeated an earlier page; stopping pagination.", page_number)
            break
        if fingerprint:
            previous_fingerprints.add(fingerprint)

        if page_new == 0:
            duplicate_only_streak += 1
        else:
            duplicate_only_streak = 0

        if duplicate_only_streak >= 2:
            stop_reason = "two_consecutive_pages_without_new_urls"
            LOGGER.warning("Two consecutive pages added no new URLs; stopping.")
            break

        if len(page_items) < page_size:
            LOGGER.info(
                "Page %d returned a short page (%d < %d); continuing to the next page "
                "because short responses do not reliably indicate exhaustion.",
                page_number, len(page_items), page_size
            )

        if page_number < page_cap and page_delay_seconds > 0:
            time.sleep(page_delay_seconds)

    return {
        "search_engine": SEARCH_ENGINE,
        "query": query,
        "region": region,
        "requested_unique_result_limit": limit,
        "page_size": PROVIDER_PAGE_SIZE,
        "pagination_policy": "continue_after_short_page_until_empty_or_other_stop_condition",
        "pages_attempted": len(pages) + len(page_errors),
        "pages_succeeded": len(pages),
        "raw_result_count": len(flattened_raw),
        "raw_unique_url_count": len(unique_urls),
        "stop_reason": stop_reason,
        "page_errors": page_errors,
        "pages": pages,
        "raw_results": flattened_raw,
    }


def write_json(data: Any, path: Path) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(
    output_dir: Path,
    query: str,
    limit: int,
    region: str,
    raw_count: int,
    cleaned_count: int,
    pages_succeeded: int,
    stop_reason: str,
    status: str,
    error: str = "",
) -> None:
    lines = [
        "DUCKDUCKGO SEARCH COLLECTION REPORT",
        "=" * 38,
        f"Status                  : {status}",
        f"Search query            : {query}",
        f"Search engine           : {SEARCH_ENGINE}",
        f"Region                  : {region}",
        f"Requested unique limit  : {limit}",
        f"Raw provider records    : {raw_count}",
        f"Unique cleaned records  : {cleaned_count}",
        f"Duplicate/invalid count : {max(raw_count - cleaned_count, 0)}",
        f"Successful pages        : {pages_succeeded}",
        f"Pagination stop reason : {stop_reason}",
        f"Collected at (UTC)      : {utc_now()}",
        "",
        "Run files:",
        "- raw_results.json       (page-by-page provider response + flattened raw records)",
        "- cleaned_results.json  (normalized unique records)",
        "- cleaned_results.csv   (cleaned spreadsheet export)",
        "- run.log               (runner command and dependency logs)",
        "- collector.log         (application logs)",
        "- metadata.json         (GitHub execution provenance)",
        "- summary.txt           (run-level counts and status)",
    ]
    if error:
        lines.extend(["", f"Error: {error}"])
    (output_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Paginated DuckDuckGo search collector."
    )
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", required=True, type=int, choices=sorted(ALLOWED_LIMITS))
    parser.add_argument(
        "--region", default=DEFAULT_REGION,
        choices=["in-en", "us-en", "uk-en", "wt-wt"],
    )
    parser.add_argument(
        "--max-pages", type=int, default=None,
        help="Optional hard cap on pages; otherwise calculated from target and page size.",
    )
    parser.add_argument(
        "--page-delay", type=float, default=1.0,
        help="Delay between successful page requests in seconds.",
    )
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    query = args.query.strip()
    args.output.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(args.output / "collector.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    ))
    if not LOGGER.handlers:
        LOGGER.addHandler(file_handler)
        LOGGER.addHandler(logging.StreamHandler(sys.stdout))
    LOGGER.setLevel(logging.INFO)

    collected_at = utc_now()
    raw_bundle: dict[str, Any] = {
        "search_engine": SEARCH_ENGINE,
        "query": query,
        "requested_unique_result_limit": args.limit,
        "pages": [],
        "raw_results": [],
    }
    cleaned: list[dict[str, Any]] = []
    status = "FAILED"
    error_text = ""

    try:
        LOGGER.info(
            "Starting paginated search | query=%r | target=%d | page_size=%d",
            query, args.limit, PROVIDER_PAGE_SIZE
        )
        raw_bundle = fetch_paginated_results(
            query=query,
            limit=args.limit,
            region=args.region,
            page_size=PROVIDER_PAGE_SIZE,
            max_pages=args.max_pages,
            page_delay_seconds=args.page_delay,
        )
        # Persist the complete raw page bundle before cleaning.
        write_json(raw_bundle, args.output / "raw_results.json")
        LOGGER.info(
            "Raw page bundle saved | pages=%d | raw_records=%d",
            raw_bundle["pages_succeeded"], raw_bundle["raw_result_count"]
        )

        cleaned = clean_results(
            raw_bundle["raw_results"], query, args.region, collected_at, args.limit
        )
        write_json(cleaned, args.output / "cleaned_results.json")
        write_csv(cleaned, args.output / "cleaned_results.csv")

        status = (
            "SUCCESS" if len(cleaned) >= args.limit
            else "PARTIAL" if cleaned
            else "NO_RESULTS"
        )
        write_summary(
            args.output, query, args.limit, args.region,
            raw_bundle["raw_result_count"], len(cleaned),
            raw_bundle["pages_succeeded"], raw_bundle["stop_reason"], status,
        )
        LOGGER.info(
            "Collection finished | requested=%d | raw=%d | unique=%d | status=%s | stop=%s",
            args.limit, raw_bundle["raw_result_count"], len(cleaned),
            status, raw_bundle["stop_reason"]
        )
        # Partial results are valid output; do not mark the run as failed merely
        # because the provider did not expose the full requested count.
        return 0

    except Exception as exc:
        error_text = str(exc)
        LOGGER.exception("Collection failed.")
        write_json(raw_bundle, args.output / "raw_results.json")
        write_json(cleaned, args.output / "cleaned_results.json")
        write_csv(cleaned, args.output / "cleaned_results.csv")
        write_summary(
            args.output, query, args.limit, args.region,
            len(raw_bundle.get("raw_results", [])), len(cleaned),
            len(raw_bundle.get("pages", [])),
            "collection_error", "FAILED", error_text,
        )
        return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    sys.exit(main())
