#!/usr/bin/env python3
"""SearXNG-backed DuckDuckGo search collector with bounded pagination.

This module deliberately uses a single configured upstream engine (DuckDuckGo)
through a local SearXNG instance. It does not fall back to other engines and it
never solves challenges or bypasses upstream access controls.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

LOGGER = logging.getLogger("searxng_collector")
DEFAULT_MAX_PAGES = 20
MAX_ALLOWED_PAGES = 100
DEFAULT_PAGE_DELAY = 2.0
MAX_DUPLICATE_ONLY_PAGES = 3
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
ALLOWED_ENGINES = {"duckduckgo", "duckduckgo web"}
REGION_LANGUAGE = {"in-en": "en-IN", "us-en": "en-US", "uk-en": "en-GB", "wt-wt": "all"}
CSV_FIELDS = [
    "rank", "title", "url", "domain", "snippet", "query", "source_query",
    "source_page", "source_engine", "provider", "region", "collected_at",
]


class SearXNGRequestError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, category: str = "request_error", response: Any | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.category = category
        self.response = response


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(value: str) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return ""
    try:
        parts = urlsplit(candidate)
        if parts.scheme.lower() not in {"http", "https"} or not parts.netloc or not parts.hostname:
            return ""
        if parts.username or parts.password:
            return ""
        # Keep query parameters because they may identify distinct resources;
        # remove fragments, which never identify a separate HTTP resource.
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))
    except ValueError:
        return ""


def extract_domain(url: str) -> str:
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def _status_category(status: int | None) -> str:
    if status == 202:
        return "http_202_interstitial_or_challenge_signal"
    if status == 403:
        return "http_403_forbidden_or_format_disabled"
    if status == 429:
        return "http_429_rate_limited"
    if status is not None and status >= 500:
        return f"http_{status}_upstream_or_service_error"
    if status is not None:
        return f"http_{status}_request_error"
    return "network_or_request_error"


def _retry_after(response: Any, fallback: float) -> float:
    raw = getattr(response, "headers", {}).get("Retry-After")
    try:
        value = float(raw)
        return max(0.0, min(value, 60.0))
    except (TypeError, ValueError):
        return fallback


class SearXNGClient:
    """Small HTTP client; injectable sessions make all network paths testable."""

    def __init__(self, base_url: str, timeout: float = 45.0, session: Any | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "search-collection-pipeline/3.0 (+https://github.com/anuxlab/web-search-engine-pipeline)",
            "Accept": "application/json",
        })

    def fetch_page(self, query: str, page: int, region: str) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
        if region not in REGION_LANGUAGE:
            raise ValueError(f"unsupported region: {region}")
        params = {
            # !ddg constrains SearXNG to the DuckDuckGo engine. The config also
            # keeps only that engine; result-level provenance is checked again.
            "q": f"!ddg {query}",
            "format": "json",
            "pageno": page,
            "language": REGION_LANGUAGE[region],
            "safesearch": 1,
        }
        response = self.session.get(f"{self.base_url}/search", params=params, timeout=self.timeout)
        status = int(response.status_code)
        if status != 200:
            excerpt = (getattr(response, "text", "") or "")[:600]
            raise SearXNGRequestError(f"HTTP {status}: {excerpt}", status, _status_category(status), response)
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise SearXNGRequestError(f"invalid JSON response: {exc}", status, "invalid_json") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise SearXNGRequestError("JSON response did not contain a results array", status, "invalid_response_schema")
        results = [item for item in payload["results"] if isinstance(item, dict)]
        return results, payload, status


def _normalise_result(item: dict[str, Any], query: str, page: int, region: str,
                      collected_at: str, rank: int) -> dict[str, Any] | None:
    engine = str(item.get("engine") or "").strip().casefold()
    if engine not in ALLOWED_ENGINES:
        return None
    url = normalize_url(str(item.get("url") or item.get("href") or ""))
    if not url:
        return None
    engines = item.get("engines") if isinstance(item.get("engines"), list) else [engine]
    return {
        "rank": rank,
        "title": str(item.get("title") or "").strip(),
        "url": url,
        "domain": extract_domain(url),
        "snippet": str(item.get("content") or item.get("snippet") or "").strip(),
        "query": query,
        "source_query": query,
        "source_page": page,
        "source_engine": engine,
        "provider": "searxng",
        "region": region,
        "collected_at": collected_at,
        "engines": [str(value) for value in engines],
    }


def _fingerprint(items: list[dict[str, Any]]) -> tuple[str, ...]:
    urls = [normalize_url(str(item.get("url") or item.get("href") or "")) for item in items]
    return tuple(url for url in urls if url)


def collect_query(
    query: str,
    limit: int,
    region: str = "in-en",
    max_pages: int = DEFAULT_MAX_PAGES,
    page_delay: float = DEFAULT_PAGE_DELAY,
    retries: int = 2,
    retry_backoff: float = 2.0,
    duplicate_only_limit: int = MAX_DUPLICATE_ONLY_PAGES,
    client: SearXNGClient | None = None,
    rng: Any = random,
) -> dict[str, Any]:
    """Collect up to ``limit`` unique DuckDuckGo URLs for one query.

    A successful HTTP response is not automatically treated as a successful
    DuckDuckGo page: only results explicitly attributed to DuckDuckGo are kept.
    The page cap, retry budget and duplicate-only guard bound resource usage.
    """
    query = " ".join((query or "").split())
    if not query:
        raise ValueError("query must not be empty")
    if len(query) > 512:
        raise ValueError("query must not exceed 512 characters")
    if region not in REGION_LANGUAGE:
        raise ValueError(f"unsupported region: {region}")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if not 1 <= max_pages <= MAX_ALLOWED_PAGES:
        raise ValueError(f"max_pages must be between 1 and {MAX_ALLOWED_PAGES}")
    if page_delay < 0 or page_delay > 30:
        raise ValueError("page_delay must be between 0 and 30 seconds")
    if retries < 0 or retries > 5:
        raise ValueError("retries must be between 0 and 5")
    if retry_backoff < 0 or retry_backoff > 60:
        raise ValueError("retry_backoff must be between 0 and 60 seconds")
    if duplicate_only_limit < 1 or duplicate_only_limit > 10:
        raise ValueError("duplicate_only_limit must be between 1 and 10")

    client = client or SearXNGClient("http://127.0.0.1:8888")
    collected_at = utc_now()
    pages: list[dict[str, Any]] = []
    page_errors: list[dict[str, Any]] = []
    raw_results: list[dict[str, Any]] = []
    cleaned: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_fingerprints: set[tuple[str, ...]] = set()
    duplicate_only_streak = 0
    stop_reason = "max_pages_reached"
    total_request_seconds = 0.0
    total_attempts = 0

    for page_number in range(1, max_pages + 1):
        response_payload: dict[str, Any] = {}
        response_results: list[dict[str, Any]] = []
        status: int | None = None
        error: str | None = None
        category: str | None = None
        attempts_used = 0
        request_elapsed = 0.0

        for attempt in range(retries + 1):
            attempts_used += 1
            total_attempts += 1
            started = time.monotonic()
            try:
                response_results, response_payload, status = client.fetch_page(query, page_number, region)
                error, category = None, None
                request_elapsed += time.monotonic() - started
                break
            except SearXNGRequestError as exc:
                request_elapsed += time.monotonic() - started
                status = exc.status_code
                error, category = str(exc), exc.category
                retryable = status in RETRYABLE_STATUSES
                if not retryable or attempt >= retries:
                    break
                wait = _retry_after(getattr(exc, "response", None), retry_backoff * (2 ** attempt))
                wait = min(wait + rng.uniform(0, 0.25), 60.0)
                LOGGER.warning("Retryable SearXNG error | query=%r | page=%d | status=%s | wait=%.2fs",
                               query, page_number, status, wait)
                if wait:
                    time.sleep(wait)
            except requests.RequestException as exc:
                request_elapsed += time.monotonic() - started
                error, category = f"{type(exc).__name__}: {exc}", "network_or_request_error"
                if attempt >= retries:
                    break
                wait = min(retry_backoff * (2 ** attempt) + rng.uniform(0, 0.25), 60.0)
                LOGGER.warning("Retryable network error | query=%r | page=%d | wait=%.2fs", query, page_number, wait)
                if wait:
                    time.sleep(wait)

        total_request_seconds += request_elapsed
        if error:
            page_errors.append({
                "page": page_number, "http_status": status, "status_code": status, "category": category,
                "error": error, "attempts": attempts_used,
                "elapsed_seconds": round(request_elapsed, 3),
            })
            LOGGER.error("Page failed | query=%r | page=%d | category=%s", query, page_number, category)
            stop_reason = "provider_request_failed" if not pages else "partial_results_provider_request_failed"
            break

        engine_counts: dict[str, int] = {}
        for item in response_results:
            engine = str(item.get("engine") or "unknown").casefold()
            engine_counts[engine] = engine_counts.get(engine, 0) + 1
        ddg_items = [item for item in response_results
                     if str(item.get("engine") or "").strip().casefold() in ALLOWED_ENGINES]
        unresponsive = response_payload.get("unresponsive_engines", [])
        unresponsive_names = [str(item.get("name") or item) if isinstance(item, dict) else str(item)
                              for item in unresponsive] if isinstance(unresponsive, list) else []

        fingerprint = _fingerprint(ddg_items)
        new_count = 0
        for item in ddg_items:
            raw_results.append({**item, "_source_query": query, "_source_page": page_number})
            normalized = _normalise_result(item, query, page_number, region, collected_at, len(cleaned) + 1)
            if normalized is None:
                continue
            if normalized["url"] not in seen_urls and len(cleaned) < limit:
                seen_urls.add(normalized["url"])
                cleaned.append(normalized)
                new_count += 1

        page_record = {
            "page": page_number,
            "http_status": status,
            "elapsed_seconds": round(request_elapsed, 3),
            "attempts": attempts_used,
            "returned_count": len(response_results),
            "duckduckgo_result_count": len(ddg_items),
            "new_unique_count": new_count,
            "engine_counts": engine_counts,
            "unresponsive_engines": unresponsive_names,
            "results": response_results,
        }
        pages.append(page_record)
        LOGGER.info("Page %d/%d | HTTP %s | raw=%d | DDG=%d | new_unique=%d | total=%d | %.3fs",
                    page_number, max_pages, status, len(response_results), len(ddg_items),
                    new_count, len(cleaned), request_elapsed)

        if len(cleaned) >= limit:
            stop_reason = "requested_unique_result_limit_reached"
            break
        if not response_results:
            if any("duckduckgo" in name.casefold() for name in unresponsive_names):
                stop_reason = "duckduckgo_engine_unresponsive"
            else:
                stop_reason = "provider_returned_empty_page"
            break
        if response_results and not ddg_items:
            stop_reason = "no_duckduckgo_attributed_results"
            break
        if fingerprint and fingerprint in seen_fingerprints:
            stop_reason = "provider_repeated_page"
            break
        if fingerprint:
            seen_fingerprints.add(fingerprint)
        duplicate_only_streak = duplicate_only_streak + 1 if new_count == 0 else 0
        if duplicate_only_streak >= duplicate_only_limit:
            stop_reason = f"{duplicate_only_limit}_consecutive_pages_without_new_urls"
            break
        if page_number < max_pages and page_delay:
            time.sleep(page_delay)

    status = ("FAILED" if (not pages and page_errors) or
              (not cleaned and stop_reason in {"duckduckgo_engine_unresponsive", "no_duckduckgo_attributed_results"}) else
              "SUCCESS" if len(cleaned) >= limit else
              "PARTIAL" if cleaned else "NO_RESULTS")
    return {
        "provider": "searxng",
        "search_engine": "DuckDuckGo",
        "engine_filter": "duckduckgo",
        "query": query,
        "region": region,
        "language": REGION_LANGUAGE[region],
        "requested_unique_result_limit": limit,
        "max_pages": max_pages,
        "pages_attempted": len(pages) + len(page_errors),
        "pages_succeeded": len(pages),
        "pages_failed": len(page_errors),
        "raw_result_count": sum(page["returned_count"] for page in pages),
        "duckduckgo_result_count": len(raw_results),
        "unique_result_count": len(cleaned),
        "target_reached": len(cleaned) >= limit,
        "status": status,
        "stop_reason": stop_reason,
        "retry_attempt_count": total_attempts,
        "total_request_seconds": round(total_request_seconds, 3),
        "collected_at": collected_at,
        "page_errors": page_errors,
        "pages": pages,
        "raw_results": raw_results,
        "cleaned_results": cleaned,
    }


def write_outputs(bundle: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "raw_results.json").write_text(
        json.dumps({key: value for key, value in bundle.items() if key != "cleaned_results"},
                   ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    cleaned = bundle.get("cleaned_results", [])
    (output_dir / "cleaned_results.json").write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output_dir / "cleaned_results.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cleaned)
    lines = [
        "SEARXNG SEARCH COLLECTION REPORT", "=" * 36,
        f"Status: {bundle.get('status')}", f"Query: {bundle.get('query')}",
        f"Region: {bundle.get('region')}", f"Engine: {bundle.get('engine_filter')}",
        f"Requested unique results: {bundle.get('requested_unique_result_limit')}",
        f"Unique results collected: {bundle.get('unique_result_count')}",
        f"Pages attempted / succeeded / failed: {bundle.get('pages_attempted')} / {bundle.get('pages_succeeded')} / {bundle.get('pages_failed')}",
        f"Retry attempts: {bundle.get('retry_attempt_count')}",
        f"Total request time (seconds): {bundle.get('total_request_seconds')}",
        f"Target reached: {bundle.get('target_reached')}", f"Stop reason: {bundle.get('stop_reason')}",
        "", "Page diagnostics:",
    ]
    for page in bundle.get("pages", []):
        lines.append(
            f"Page {page['page']}: HTTP {page['http_status']} | raw={page['returned_count']} | "
            f"DuckDuckGo={page['duckduckgo_result_count']} | new_unique={page['new_unique_count']} | "
            f"attempts={page['attempts']} | elapsed={page['elapsed_seconds']}s"
        )
    for error in bundle.get("page_errors", []):
        lines.append(f"Page {error['page']} ERROR: {error['category']} | {error['error']}")
    (output_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8888")
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", required=True, type=int)
    parser.add_argument("--region", default="in-en", choices=sorted(REGION_LANGUAGE))
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--page-delay", type=float, default=DEFAULT_PAGE_DELAY)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-backoff", type=float, default=2.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    args.output.mkdir(parents=True, exist_ok=True)
    logger_handler = logging.FileHandler(args.output / "collector.log", encoding="utf-8")
    logger_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    LOGGER.addHandler(logger_handler)
    LOGGER.setLevel(logging.INFO)
    try:
        LOGGER.info("Starting SearXNG-only collection | query=%r | limit=%d | max_pages=%d",
                    args.query, args.limit, args.max_pages)
        bundle = collect_query(args.query, args.limit, args.region, args.max_pages,
                               args.page_delay, args.retries, args.retry_backoff,
                               client=SearXNGClient(args.base_url))
        write_outputs(bundle, args.output)
        LOGGER.info("Finished | status=%s | unique=%d/%d | stop=%s",
                    bundle["status"], bundle["unique_result_count"], args.limit, bundle["stop_reason"])
        return 1 if bundle["status"] == "FAILED" else 0
    except Exception as exc:
        LOGGER.exception("Collector crashed")
        fallback = {
            "provider": "searxng", "search_engine": "DuckDuckGo", "query": args.query,
            "region": args.region, "requested_unique_result_limit": args.limit,
            "status": "FAILED", "target_reached": False, "stop_reason": "collector_exception",
            "pages_attempted": 0, "pages_succeeded": 0, "pages_failed": 1,
            "raw_result_count": 0, "duckduckgo_result_count": 0, "unique_result_count": 0,
            "retry_attempt_count": 0, "total_request_seconds": 0.0,
            "page_errors": [{"page": 1, "category": "collector_exception", "error": f"{type(exc).__name__}: {exc}"}],
            "pages": [], "raw_results": [], "cleaned_results": [],
        }
        write_outputs(fallback, args.output)
        return 1
    finally:
        LOGGER.removeHandler(logger_handler)
        logger_handler.close()


if __name__ == "__main__":
    sys.exit(main())
