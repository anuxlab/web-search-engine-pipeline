#!/usr/bin/env python3
"""Run an isolated, auditable search-provider experiment.

Supported providers:
  * ddgs: DDGS Python library with DuckDuckGo backend and page parameter.
  * ddg-lite: direct, ordinary HTTP form navigation of DuckDuckGo Lite.
  * searxng: a local SearXNG instance restricted to its DuckDuckGo engine.
  * instant-api: official DuckDuckGo Instant Answer API (not organic SERP).

The script never changes provider silently and never attempts to defeat challenges.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger("provider_experiment")
CSV_FIELDS = ["rank", "title", "url", "domain", "snippet", "query", "provider", "page", "region", "collected_at"]
UA = "web-search-engine-pipeline/2.1 (+https://github.com/anuxlab/web-search-engine-pipeline; research test)"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_url(value: str) -> str:
    value = (value or "").strip()
    try:
        p = urlsplit(value)
        if p.scheme not in {"http", "https"} or not p.netloc:
            return ""
        # DDG result links can be redirect wrappers; preserve the destination URL.
        if p.hostname and p.hostname.endswith("duckduckgo.com") and p.path.startswith("/l/"):
            destination = parse_qs(p.query).get("uddg", [""])[0]
            if destination:
                return canonical_url(unquote(destination))
        return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path or ''}" + (f"?{p.query}" if p.query else "")
    except ValueError:
        return ""


def normalize_item(item: dict[str, Any], provider: str, query: str, page: int,
                   region: str, rank: int, collected_at: str) -> dict[str, Any] | None:
    url = canonical_url(str(item.get("href") or item.get("url") or item.get("first_url") or ""))
    if not url:
        return None
    return {
        "rank": rank,
        "title": str(item.get("title") or item.get("heading") or "").strip(),
        "url": url,
        "domain": urlsplit(url).hostname or "",
        "snippet": str(item.get("body") or item.get("snippet") or item.get("content") or item.get("text") or "").strip(),
        "query": query,
        "provider": provider,
        "page": page,
        "region": region,
        "collected_at": collected_at,
    }


def _ddgs_status_handler() -> tuple[logging.Handler, list[int], int]:
    codes: list[int] = []
    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            m = re.search(r"\bresponse:.*?\b(\d{3})\s*$", record.getMessage(), re.I)
            if m:
                codes.append(int(m.group(1)))
    handler = Capture(level=logging.INFO)
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    if previous > logging.INFO:
        root.setLevel(logging.INFO)
    return handler, codes, previous


def run_ddgs(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise RuntimeError("ddgs dependency is not installed") from exc
    rows: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()
    collected = now_utc()
    client = DDGS(timeout=25)
    for page in range(1, args.pages + 1):
        handler, codes, old_level = _ddgs_status_handler()
        started = time.monotonic()
        try:
            LOG.info("DDGS request page=%d backend=duckduckgo", page)
            items = client.text(args.query, region=args.region, safesearch="moderate",
                                max_results=args.page_size, page=page, backend="duckduckgo") or []
            status = codes[-1] if codes else 200
            error = None
        except Exception as exc:  # provider failures are recorded, not discarded
            items, status, error = [], (codes[-1] if codes else None), f"{type(exc).__name__}: {exc}"
        finally:
            root = logging.getLogger()
            root.removeHandler(handler)
            root.setLevel(old_level)
            handler.close()
        duration = round(time.monotonic() - started, 3)
        added = 0
        for item in items:
            normalized = normalize_item(item, "ddgs-duckduckgo", args.query, page, args.region, len(rows) + 1, collected)
            if normalized and normalized["url"] not in seen:
                seen.add(normalized["url"])
                rows.append(normalized)
                added += 1
        pages.append({"page": page, "http_status": status, "elapsed_seconds": duration,
                      "returned_count": len(items), "new_unique_count": added,
                      "error": error, "raw_results": items})
        LOG.info("DDGS page=%d status=%s returned=%d unique_added=%d elapsed=%.3fs",
                 page, status, len(items), added, duration)
        if error or status in {202, 403, 429}:
            break
        if not items or len(items) < args.page_size:
            break
        if page < args.pages:
            time.sleep(args.page_delay)
    return rows, pages, {"pagination_supported_by_client": True, "pagination_mode": "page parameter",
                         "provider_backend": "duckduckgo", "note": "Page parameter is supported by DDGS; actual depth depends on provider response."}


def _lite_result_rows(soup: BeautifulSoup) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    anchors = soup.select("a.result-link")
    if not anchors:
        anchors = [a for a in soup.select("a[href]") if a.get("href", "").startswith(("http://", "https://"))
                   and "duckduckgo.com" not in urlsplit(a.get("href", "")).netloc]
    for anchor in anchors:
        href = anchor.get("href", "")
        title = anchor.get_text(" ", strip=True)
        if not canonical_url(href) or not title:
            continue
        row = anchor.find_parent("tr")
        snippet = ""
        if row:
            snippet_node = row.find_next_sibling("tr")
            if snippet_node:
                snippet = snippet_node.get_text(" ", strip=True)
        found.append({"title": title, "href": href, "body": snippet})
    return found


def _lite_next_form(soup: BeautifulSoup) -> tuple[str, dict[str, str]] | None:
    candidates = []
    for form in soup.find_all("form"):
        data = {}
        for node in form.find_all(["input", "button"]):
            name = node.get("name")
            if name:
                data[name] = node.get("value", "")
        names = set(data)
        if names & {"vqd", "nextParams", "api", "s", "dc"}:
            candidates.append((form, data))
    if not candidates:
        return None
    form, data = candidates[-1]
    action = urljoin("https://lite.duckduckgo.com/lite/", form.get("action") or "/lite/")
    return action, data


def run_ddg_lite(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": args.region})
    rows: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()
    collected = now_utc()
    url = "https://lite.duckduckgo.com/lite/"
    method = "GET"
    payload: dict[str, str] | None = None
    for page in range(1, args.pages + 1):
        started = time.monotonic()
        try:
            response = session.get(url, params={"q": args.query, "kl": args.region} if method == "GET" else None,
                                   timeout=30) if method == "GET" else session.post(url, data=payload, timeout=30)
            status = response.status_code
            body = response.text
            error = None if status == 200 else f"HTTP {status}"
        except requests.RequestException as exc:
            status, body, error = None, "", f"{type(exc).__name__}: {exc}"
        duration = round(time.monotonic() - started, 3)
        soup = BeautifulSoup(body, "html.parser")
        raw = _lite_result_rows(soup) if status == 200 else []
        added = 0
        for item in raw:
            normalized = normalize_item(item, "ddg-lite", args.query, page, args.region, len(rows) + 1, collected)
            if normalized and normalized["url"] not in seen:
                seen.add(normalized["url"])
                rows.append(normalized)
                added += 1
        pages.append({"page": page, "http_status": status, "elapsed_seconds": duration,
                      "returned_count": len(raw), "new_unique_count": added, "error": error,
                      "response_excerpt": body[:2500] if status != 200 else ""})
        LOG.info("DDG Lite page=%d status=%s returned=%d unique_added=%d elapsed=%.3fs",
                 page, status, len(raw), added, duration)
        if error or status in {202, 403, 429}:
            break
        if not raw:
            break
        next_form = _lite_next_form(soup)
        if not next_form:
            pages[-1]["pagination_note"] = "No continuation form found in returned HTML."
            break
        url, payload = next_form
        method = "POST"
        if page < args.pages:
            time.sleep(args.page_delay)
    return rows, pages, {"pagination_supported_by_interface": True, "pagination_mode": "server-provided HTML continuation form",
                         "note": "Uses returned form fields; no challenge solving or access-control bypass. Interface is undocumented and may change."}


def run_searxng(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()
    collected = now_utc()
    language = {"in-en": "en-IN", "us-en": "en-US", "uk-en": "en-GB", "wt-wt": "all"}.get(args.region, "all")
    for page in range(1, args.pages + 1):
        started = time.monotonic()
        try:
            response = requests.get(args.searxng_url.rstrip("/") + "/search", params={
                "q": f"!ddg {args.query}", "format": "json", "pageno": page,
                "language": language, "safesearch": 1,
            }, timeout=60)
            status = response.status_code
            data = response.json() if status == 200 else {}
            error = None if status == 200 else f"HTTP {status}: {response.text[:500]}"
        except (requests.RequestException, ValueError) as exc:
            status, data, error = None, {}, f"{type(exc).__name__}: {exc}"
        duration = round(time.monotonic() - started, 3)
        raw = data.get("results", []) if isinstance(data, dict) else []
        engine_counts: dict[str, int] = {}
        added = 0
        for item in raw:
            engine = str(item.get("engine") or "unknown")
            engine_counts[engine] = engine_counts.get(engine, 0) + 1
            # Keep only results explicitly attributed to DDG; do not silently mix engines.
            if engine not in {"duckduckgo", "duckduckgo web"}:
                continue
            normalized = normalize_item(item, "searxng-duckduckgo", args.query, page, args.region, len(rows) + 1, collected)
            if normalized and normalized["url"] not in seen:
                seen.add(normalized["url"])
                rows.append(normalized)
                added += 1
        pages.append({"page": page, "http_status": status, "elapsed_seconds": duration,
                      "returned_count": len(raw), "new_unique_count": added, "engine_counts": engine_counts,
                      "unresponsive_engines": data.get("unresponsive_engines", []) if isinstance(data, dict) else [],
                      "error": error, "raw_results": raw})
        LOG.info("SearXNG/DDG page=%d status=%s returned=%d DDG_unique_added=%d engines=%s elapsed=%.3fs",
                 page, status, len(raw), added, engine_counts, duration)
        if error or status in {202, 403, 429} or not raw:
            break
        if page < args.pages:
            time.sleep(args.page_delay)
    return rows, pages, {"pagination_supported_by_searxng": True, "pagination_mode": "pageno parameter",
                         "engine_filter": "duckduckgo", "note": "SearXNG is self-hosted; the underlying DDG engine remains subject to DDG restrictions."}


def _flatten_topics(topics: list[Any]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        if isinstance(topic.get("Topics"), list):
            flattened.extend(_flatten_topics(topic["Topics"]))
        elif topic.get("FirstURL"):
            flattened.append({"title": topic.get("Text", ""), "href": topic.get("FirstURL", ""),
                              "body": topic.get("Text", ""), "source_type": "related_topic"})
    return flattened


def run_instant_api(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    started = time.monotonic()
    collected = now_utc()
    response = requests.get("https://api.duckduckgo.com/", params={
        "q": args.query, "format": "json", "no_html": 1, "no_redirect": 1,
    }, timeout=30)
    status = response.status_code
    response.raise_for_status()
    data = response.json()
    raw = list(data.get("Results", [])) + _flatten_topics(data.get("RelatedTopics", []))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        normalized = normalize_item(item, "duckduckgo-instant-answer-api", args.query, 1, args.region,
                                    len(rows) + 1, collected)
        if normalized and normalized["url"] not in seen:
            seen.add(normalized["url"])
            rows.append(normalized)
    page = {"page": 1, "http_status": status, "elapsed_seconds": round(time.monotonic() - started, 3),
            "returned_count": len(raw), "new_unique_count": len(rows), "raw_results": raw,
            "abstract": data.get("Abstract", ""), "abstract_url": data.get("AbstractURL", ""),
            "heading": data.get("Heading", ""), "answer": data.get("Answer", "")}
    return rows, [page], {"pagination_supported": False, "pagination_mode": "not applicable",
                          "api_type": "official Instant Answer API", "note": "This API does not provide the full organic web search results or SERP pagination."}


def write_outputs(args: argparse.Namespace, rows: list[dict[str, Any]], pages: list[dict[str, Any]],
                  provider_info: dict[str, Any], error: str | None) -> None:
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    raw = {"provider": args.provider, "query": args.query, "region": args.region,
           "requested_pages": args.pages, "provider_info": provider_info, "pages": pages,
           "raw_page_count": len(pages), "raw_result_count": sum(p.get("returned_count", 0) for p in pages),
           "unique_result_count": len(rows), "fatal_error": error}
    (out / "raw_results.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    (out / "cleaned_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (out / "cleaned_results.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    status_codes = [p.get("http_status") for p in pages]
    summary = ["SEARCH PROVIDER EXPERIMENT", "=" * 34, f"Provider: {args.provider}",
               f"Query: {args.query}", f"Region: {args.region}", f"Requested pages: {args.pages}",
               f"Pages attempted: {len(pages)}", f"Pages with HTTP 200: {sum(x == 200 for x in status_codes)}",
               f"Unique results: {len(rows)}", f"Pagination: {provider_info.get('pagination_mode', 'unknown')}",
               f"Fatal error: {error or 'None'}", "", "Page diagnostics:"]
    for page in pages:
        summary.append(f"  Page {page.get('page')}: HTTP {page.get('http_status')} | returned={page.get('returned_count')} | new_unique={page.get('new_unique_count')} | error={page.get('error') or 'None'}")
    summary.extend(["", "Interpretation:", provider_info.get("note", "See raw_results.json for provider diagnostics.")])
    (out / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=["ddgs", "ddg-lite", "searxng", "instant-api"])
    parser.add_argument("--query", required=True)
    parser.add_argument("--region", default="in-en")
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--page-size", type=int, default=10)
    parser.add_argument("--page-delay", type=float, default=3.0)
    parser.add_argument("--searxng-url", default="http://127.0.0.1:8888")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.query.strip() or not 1 <= args.pages <= 10 or not 1 <= args.page_size <= 20:
        parser.error("query must be non-empty; pages must be 1..10; page-size must be 1..20")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    error = None
    rows: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    info: dict[str, Any] = {}
    try:
        if args.provider == "ddgs":
            rows, pages, info = run_ddgs(args)
        elif args.provider == "ddg-lite":
            rows, pages, info = run_ddg_lite(args)
        elif args.provider == "searxng":
            rows, pages, info = run_searxng(args)
        else:
            rows, pages, info = run_instant_api(args)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        LOG.exception("Experiment failed")
    write_outputs(args, rows, pages, info, error)
    LOG.info("Experiment complete: provider=%s pages=%d unique_results=%d fatal_error=%s",
             args.provider, len(pages), len(rows), error or "none")
    if error:
        return 1
    # Instant Answer API can validly return an abstract/answer without organic links.
    if args.provider == "instant-api" and pages and pages[0].get("http_status") == 200:
        return 0
    if not rows:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
