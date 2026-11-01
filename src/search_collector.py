#!/usr/bin/env python3
"""DuckDuckGo collection engine with paginated and diversified strategies.

The collector deliberately uses DuckDuckGo only. Hybrid mode gathers first-page
results from related queries before attempting pagination, reducing dependence
on a single fragile page-2 request. Provider blocks are recorded distinctly from
empty result pages; no results are fabricated or silently sourced elsewhere.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover - tests inject a fake client
    DDGS = None  # type: ignore[assignment,misc]

LOGGER = logging.getLogger("ddg_collector")
ALLOWED_LIMITS = {10, 30, 50, 100, 200, 500}
PROVIDER_PAGE_SIZE = 10
DEFAULT_REGION = "in-en"
DEFAULT_SAFESEARCH = "moderate"
SEARCH_ENGINE = "DuckDuckGo"
DEFAULT_MAX_PAGES = 60
DEFAULT_MAX_QUERIES = 8
CSV_FIELDS = [
    "rank", "title", "url", "domain", "snippet", "query", "source_query",
    "region", "search_engine", "collected_at",
]


class ProviderRequestError(RuntimeError):
    """A failed DDGS request with any observable HTTP status attached."""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _error_category(status_code: int | None) -> str:
    if status_code == 202:
        return "http_202_challenge_or_throttle"
    if status_code == 403:
        return "http_403_forbidden_or_blocked"
    if status_code == 429:
        return "http_429_rate_limited"
    if status_code is not None:
        return f"http_{status_code}_provider_error"
    return "provider_request_error"


class _ResponseStatusCapture(logging.Handler):
    """Capture DDGS' response-status log records for challenge classification."""
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.status_codes: list[int] = []

    def emit(self, record: logging.LogRecord) -> None:
        match = re.search(r"\bresponse:.*?\b(\d{3})\s*$", record.getMessage(), re.I)
        if match:
            self.status_codes.append(int(match.group(1)))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str) -> str:
    candidate = (url or "").strip()
    if not candidate:
        return ""
    try:
        parts = urlsplit(candidate)
        if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
            return ""
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "", parts.query, ""))
    except ValueError:
        return ""


def extract_domain(url: str) -> str:
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def _page_fingerprint(items: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        normalize_url(str(item.get("href") or item.get("url") or ""))
        or json.dumps(item, sort_keys=True, default=str)
        for item in items
    )


def build_query_variants(query: str, additional_queries: Iterable[str] | None = None,
                         max_queries: int = DEFAULT_MAX_QUERIES) -> list[str]:
    """Build deterministic, transparent query variants; preserve user additions.

    Variants are domain-sensitive to avoid appending irrelevant suffixes to
    academic, software, and product searches. The original query is always first.
    """
    base = " ".join(query.strip().split())
    if not base:
        raise ValueError("query must not be empty")
    if max_queries < 1:
        raise ValueError("max_queries must be at least 1")

    tokens = set(re.findall(r"[a-z0-9]+", base.lower()))
    if tokens & {"iphone", "ipad", "laptop", "smartphone", "camera", "phone", "tablet", "macbook"}:
        suffixes = ["reviews", "specifications", "price", "models"]
    elif tokens & {"research", "paper", "papers", "algorithm", "machine", "learning", "deep", "neural", "study"}:
        suffixes = ["research papers", "survey", "methodology", "applications"]
    elif tokens & {"python", "github", "api", "framework", "library", "package", "software", "code"}:
        suffixes = ["documentation", "tutorial", "examples", "GitHub"]
    else:
        suffixes = ["overview", "guide", "examples", "latest information"]

    candidates = [base]
    candidates.extend(additional_queries or [])
    candidates.extend(f"{base} {suffix}" for suffix in suffixes)
    variants: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = " ".join(str(candidate).strip().split())
        key = normalized.casefold()
        if normalized and key not in seen:
            variants.append(normalized)
            seen.add(key)
        if len(variants) >= max_queries:
            break
    return variants


def clean_results(raw_results: list[dict[str, Any]], query: str, region: str,
                  collected_at: str, limit: int) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = normalize_url(str(item.get("href") or item.get("url") or ""))
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
            "source_query": str(item.get("_source_query") or query),
            "region": region,
            "search_engine": SEARCH_ENGINE,
            "collected_at": collected_at,
        })
        if len(cleaned) >= limit:
            break
    return cleaned


def _request_page(client: Any, query: str, page: int, region: str) -> list[dict[str, Any]]:
    capture = _ResponseStatusCapture()
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    if previous_level > logging.INFO:
        root_logger.setLevel(logging.INFO)
    root_logger.addHandler(capture)
    try:
        response = client.text(
            query,
            region=region,
            safesearch=DEFAULT_SAFESEARCH,
            max_results=PROVIDER_PAGE_SIZE,
            page=page,
            backend="duckduckgo",
        )
        return list(response or [])
    except Exception as exc:
        status = capture.status_codes[-1] if capture.status_codes else None
        raise ProviderRequestError(str(exc), status) from exc
    finally:
        root_logger.removeHandler(capture)
        root_logger.setLevel(previous_level)


def _fetch_with_retry(client: Any, query: str, page: int, region: str,
                      retry_delays: tuple[float, ...], blocked_cooldown: float) -> list[dict[str, Any]]:
    attempts = len(retry_delays) + 1
    last_error: ProviderRequestError | None = None
    for attempt in range(attempts):
        try:
            LOGGER.info("Requesting query=%r page=%d attempt=%d/%d", query, page, attempt + 1, attempts)
            return _request_page(client, query, page, region)
        except ProviderRequestError as exc:
            last_error = exc
            category = _error_category(exc.status_code)
            LOGGER.warning("Provider request failed | category=%s | query=%r | page=%d | error=%s",
                           category, query, page, exc)
            # HTTP 202 is a challenge/interstitial signal in the observed run,
            # not proof of an empty search. One longer cooldown retry is safer
            # than hammering the endpoint with several short retries.
            if exc.status_code in {202, 403}:
                if attempt == 0 and attempts > 1 and blocked_cooldown > 0:
                    LOGGER.warning("HTTP %s observed; cooling down %.1f seconds before one retry.", exc.status_code, blocked_cooldown)
                    time.sleep(blocked_cooldown)
                    continue
                break
            if attempt < len(retry_delays):
                delay = retry_delays[attempt]
                LOGGER.info("Retrying after %.1f seconds.", delay)
                time.sleep(delay)
    assert last_error is not None
    raise last_error


def _record_page(query: str, page_number: int, items: list[dict[str, Any]],
                 pages: list[dict[str, Any]], raw_results: list[dict[str, Any]],
                 unique_urls: set[str]) -> int:
    new_count = 0
    enriched: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # Keep the original provider object intact in pages[].results; the
        # flattened list carries source metadata for the cleaned export.
        enriched_item = dict(item)
        enriched_item["_source_query"] = query
        enriched_item["_source_page"] = page_number
        enriched.append(enriched_item)
        url = normalize_url(str(item.get("href") or item.get("url") or ""))
        if url and url not in unique_urls:
            unique_urls.add(url)
            new_count += 1
    pages.append({
        "query": query,
        "page": page_number,
        "requested_batch_size": PROVIDER_PAGE_SIZE,
        "returned_count": len(items),
        "new_unique_url_count": new_count,
        "results": items,
    })
    raw_results.extend(enriched)
    LOGGER.info("Page saved | query=%r | page=%d | returned=%d | new_unique=%d | total_unique=%d",
                query, page_number, len(items), new_count, len(unique_urls))
    return new_count


def _bundle(query: str, region: str, limit: int, strategy: str,
            pages: list[dict[str, Any]], raw_results: list[dict[str, Any]],
            unique_urls: set[str], page_errors: list[dict[str, Any]],
            queries: list[str], stop_reason: str) -> dict[str, Any]:
    return {
        "search_engine": SEARCH_ENGINE,
        "strategy": strategy,
        "query": query,
        "region": region,
        "requested_unique_result_limit": limit,
        "provider_page_size": PROVIDER_PAGE_SIZE,
        "queries_planned": queries,
        "queries_attempted": len({p["query"] for p in pages} | {e.get("query", "") for e in page_errors}),
        "pages_attempted": len(pages) + len(page_errors),
        "pages_succeeded": len(pages),
        "raw_result_count": len(raw_results),
        "raw_unique_url_count": len(unique_urls),
        "stop_reason": stop_reason,
        "page_errors": page_errors,
        "pages": pages,
        "raw_results": raw_results,
    }


def fetch_paginated_results(query: str, limit: int, region: str = DEFAULT_REGION,
                            page_size: int = PROVIDER_PAGE_SIZE, max_pages: int | None = None,
                            retries: int = 2, retry_delays: tuple[float, ...] = (4.0, 12.0),
                            page_delay_seconds: float = 3.0,
                            blocked_cooldown_seconds: float = 20.0) -> dict[str, Any]:
    """Legacy single-query pagination, retained as a selectable strategy."""
    if limit not in ALLOWED_LIMITS:
        raise ValueError(f"limit must be one of {sorted(ALLOWED_LIMITS)}")
    if page_size != PROVIDER_PAGE_SIZE:
        raise ValueError(f"DuckDuckGo provider page_size is fixed at {PROVIDER_PAGE_SIZE}")
    if not query.strip():
        raise ValueError("query must not be empty")
    if DDGS is None:
        raise RuntimeError("Missing dependency: install requirements.txt (ddgs).")
    page_cap = min(max_pages or (math.ceil(limit / PROVIDER_PAGE_SIZE) * 3 + 2), DEFAULT_MAX_PAGES)
    client = DDGS(timeout=20)
    pages: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []
    unique: set[str] = set()
    errors: list[dict[str, Any]] = []
    stop = "page_cap_reached"
    previous: set[tuple[str, ...]] = set()
    duplicate_streak = 0
    for page in range(1, page_cap + 1):
        try:
            items = _fetch_with_retry(client, query, page, region, retry_delays, blocked_cooldown_seconds)
        except ProviderRequestError as exc:
            errors.append({"query": query, "page": page, "status_code": exc.status_code,
                           "category": _error_category(exc.status_code),
                           "error": str(exc)})
            stop = "provider_challenge_or_request_failure" if exc.status_code == 202 else "pagination_request_failed"
            LOGGER.warning("Pagination halted on failed page %d; retaining partial results.", page)
            break
        fingerprint = _page_fingerprint(items)
        added = _record_page(query, page, items, pages, raw, unique)
        if len(unique) >= limit:
            stop = "requested_unique_result_limit_reached"
            break
        if not items:
            stop = "provider_returned_empty_page"
            break
        if fingerprint and fingerprint in previous:
            stop = "provider_repeated_page"
            break
        if fingerprint:
            previous.add(fingerprint)
        duplicate_streak = duplicate_streak + 1 if added == 0 else 0
        if duplicate_streak >= 2:
            stop = "two_consecutive_pages_without_new_urls"
            break
        if len(items) < PROVIDER_PAGE_SIZE:
            LOGGER.info("Short page (%d/%d); continuing rather than assuming exhaustion.", len(items), PROVIDER_PAGE_SIZE)
        if page < page_cap and page_delay_seconds > 0:
            time.sleep(page_delay_seconds)
    return _bundle(query, region, limit, "paginated", pages, raw, unique, errors, [query], stop)


def fetch_hybrid_results(query: str, limit: int, region: str = DEFAULT_REGION,
                         additional_queries: Iterable[str] | None = None,
                         max_queries: int = DEFAULT_MAX_QUERIES,
                         max_fallback_pages: int = 8,
                         query_delay_seconds: float = 3.0,
                         retry_delays: tuple[float, ...] = (4.0, 12.0),
                         blocked_cooldown_seconds: float = 20.0) -> dict[str, Any]:
    """Diversify across related queries, then paginate the primary query.

    Each variant is independently queried at page 1. If more results are needed,
    the original query's subsequent pages are attempted as a fallback. A block
    on one query does not discard results already gathered from other queries.
    """
    if limit not in ALLOWED_LIMITS:
        raise ValueError(f"limit must be one of {sorted(ALLOWED_LIMITS)}")
    if DDGS is None:
        raise RuntimeError("Missing dependency: install requirements.txt (ddgs).")
    variants = build_query_variants(query, additional_queries, max_queries)
    client = DDGS(timeout=20)
    pages: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []
    unique: set[str] = set()
    errors: list[dict[str, Any]] = []
    stop = "query_variants_exhausted"

    for index, variant in enumerate(variants):
        try:
            items = _fetch_with_retry(client, variant, 1, region, retry_delays, blocked_cooldown_seconds)
            _record_page(variant, 1, items, pages, raw, unique)
        except ProviderRequestError as exc:
            category = _error_category(exc.status_code)
            errors.append({"query": variant, "page": 1, "status_code": exc.status_code,
                           "category": category, "error": str(exc)})
            LOGGER.warning("Variant failed but collection continues | query=%r | category=%s", variant, category)
        if len(unique) >= limit:
            stop = "requested_unique_result_limit_reached_during_query_diversification"
            break
        if index < len(variants) - 1 and query_delay_seconds > 0:
            time.sleep(query_delay_seconds)

    # If diversification has not reached the target, preserve the old pagination
    # route as a fallback. A page failure is recorded and never erases earlier hits.
    if len(unique) < limit and max_fallback_pages > 0:
        LOGGER.info("Diversification yielded %d unique URLs; trying primary-query pagination fallback.", len(unique))
        previous = {_page_fingerprint(p["results"]) for p in pages if p["query"] == query}
        for page in range(2, min(max_fallback_pages, DEFAULT_MAX_PAGES) + 1):
            try:
                items = _fetch_with_retry(client, query, page, region, retry_delays, blocked_cooldown_seconds)
            except ProviderRequestError as exc:
                category = _error_category(exc.status_code)
                errors.append({"query": query, "page": page, "status_code": exc.status_code,
                               "category": category, "error": str(exc)})
                stop = "pagination_fallback_blocked_or_failed"
                break
            fingerprint = _page_fingerprint(items)
            added = _record_page(query, page, items, pages, raw, unique)
            if len(unique) >= limit:
                stop = "requested_unique_result_limit_reached"
                break
            if not items:
                stop = "pagination_fallback_empty_page"
                break
            if fingerprint and fingerprint in previous:
                stop = "pagination_fallback_repeated_page"
                break
            if fingerprint:
                previous.add(fingerprint)
            if added == 0:
                stop = "pagination_fallback_page_added_no_new_urls"
                break
            if query_delay_seconds > 0:
                time.sleep(query_delay_seconds)
    if not pages and errors:
        stop = "all_query_variants_failed"
    return _bundle(query, region, limit, "hybrid", pages, raw, unique, errors, variants, stop)


def write_json(data: Any, path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_summary(output_dir: Path, query: str, limit: int, region: str,
                  raw_count: int, cleaned_count: int, pages_succeeded: int,
                  stop_reason: str, status: str, strategy: str,
                  queries_attempted: int, error: str = "") -> None:
    lines = [
        "DUCKDUCKGO SEARCH COLLECTION REPORT", "=" * 38,
        f"Status                  : {status}", f"Search query            : {query}",
        f"Search engine           : {SEARCH_ENGINE}", f"Strategy                : {strategy}",
        f"Region                  : {region}", f"Requested unique limit  : {limit}",
        f"Raw provider records    : {raw_count}", f"Unique cleaned records  : {cleaned_count}",
        f"Successful pages        : {pages_succeeded}", f"Queries attempted       : {queries_attempted}",
        f"Stop reason             : {stop_reason}", f"Collected at (UTC)      : {utc_now()}",
        "", "Run files:",
        "- raw_results.json       (original page responses + flattened raw records and provenance)",
        "- cleaned_results.json  (normalized, deduplicated results)",
        "- cleaned_results.csv   (spreadsheet export)",
        "- run.log               (workflow and collector invocation log)",
        "- collector.log         (application logs)",
        "- metadata.json         (GitHub execution provenance)",
        "- repository_writeback.log (Git synchronization and commit log)",
        "- summary.txt           (run-level counts and status)",
    ]
    if error:
        lines.extend(["", f"Error: {error}"])
    (output_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_queries(value: str) -> list[str]:
    return [line.strip() for line in re.split(r"[\n;]+", value or "") if line.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DuckDuckGo hybrid and paginated search collector.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", required=True, type=int, choices=sorted(ALLOWED_LIMITS))
    parser.add_argument("--region", default=DEFAULT_REGION, choices=["in-en", "us-en", "uk-en", "wt-wt"])
    parser.add_argument("--strategy", choices=["hybrid", "paginated"], default="hybrid")
    parser.add_argument("--additional-queries", default="", help="Optional newline/semicolon-separated related queries.")
    parser.add_argument("--max-queries", type=int, default=DEFAULT_MAX_QUERIES)
    parser.add_argument("--max-pages", type=int, default=None, help="Hard page cap for paginated mode.")
    parser.add_argument("--max-fallback-pages", type=int, default=8)
    parser.add_argument("--page-delay", type=float, default=3.0)
    parser.add_argument("--blocked-cooldown", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    query = args.query.strip()
    args.output.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(args.output / "collector.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    LOGGER.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    LOGGER.addHandler(stream_handler)
    LOGGER.setLevel(logging.INFO)

    collected_at = utc_now()
    bundle: dict[str, Any] = {"search_engine": SEARCH_ENGINE, "strategy": args.strategy,
                              "query": query, "pages": [], "raw_results": []}
    cleaned: list[dict[str, Any]] = []
    try:
        extra = _parse_queries(args.additional_queries)
        LOGGER.info("Starting collection | strategy=%s | query=%r | target=%d | region=%s",
                    args.strategy, query, args.limit, args.region)
        common = {"query": query, "limit": args.limit, "region": args.region}
        if args.strategy == "hybrid":
            bundle = fetch_hybrid_results(**common, additional_queries=extra,
                max_queries=args.max_queries, max_fallback_pages=args.max_fallback_pages,
                query_delay_seconds=args.page_delay, blocked_cooldown_seconds=args.blocked_cooldown)
        else:
            bundle = fetch_paginated_results(**common, max_pages=args.max_pages,
                page_delay_seconds=args.page_delay, blocked_cooldown_seconds=args.blocked_cooldown)
        write_json(bundle, args.output / "raw_results.json")
        cleaned = clean_results(bundle["raw_results"], query, args.region, collected_at, args.limit)
        write_json(cleaned, args.output / "cleaned_results.json")
        write_csv(cleaned, args.output / "cleaned_results.csv")
        status = ("FAILED" if not bundle["pages"] and bundle["page_errors"] else
                  "SUCCESS" if len(cleaned) >= args.limit else "PARTIAL" if cleaned else "NO_RESULTS")
        write_summary(args.output, query, args.limit, args.region, bundle["raw_result_count"],
            len(cleaned), bundle["pages_succeeded"], bundle["stop_reason"], status,
            args.strategy, bundle["queries_attempted"])
        LOGGER.info("Collection finished | requested=%d | raw=%d | unique=%d | status=%s | stop=%s",
                    args.limit, bundle["raw_result_count"], len(cleaned), status, bundle["stop_reason"])
        return 1 if status == "FAILED" else 0
    except Exception as exc:
        LOGGER.exception("Collection failed.")
        write_json(bundle, args.output / "raw_results.json")
        write_json(cleaned, args.output / "cleaned_results.json")
        write_csv(cleaned, args.output / "cleaned_results.csv")
        write_summary(args.output, query, args.limit, args.region,
            len(bundle.get("raw_results", [])), len(cleaned), len(bundle.get("pages", [])),
            "collection_error", "FAILED", args.strategy, 0, str(exc))
        return 1
    finally:
        for handler in (file_handler, stream_handler):
            LOGGER.removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    sys.exit(main())
