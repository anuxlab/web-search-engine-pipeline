from pathlib import Path
import logging

import pytest

from src import search_collector as collector


def test_allowed_limits_and_page_size():
    assert collector.ALLOWED_LIMITS == {10, 30, 50, 100, 200, 500}
    assert collector.PROVIDER_PAGE_SIZE == 10


def test_url_normalization_and_validation():
    assert collector.normalize_url("HTTPS://Example.COM/path#part") == "https://example.com/path"
    assert collector.normalize_url("javascript:alert(1)") == ""
    assert collector.normalize_url("not a url") == ""


def test_query_variants_are_domain_aware_and_deduplicated():
    product = collector.build_query_variants("iphone", ["iphone reviews", "  Apple iPhone  ", ""], 8)
    assert product == ["iphone", "iphone reviews", "Apple iPhone", "iphone specifications", "iphone price", "iphone models"]
    academic = collector.build_query_variants("deep learning research", max_queries=5)
    assert "deep learning research research papers" in academic
    software = collector.build_query_variants("Python API library", max_queries=5)
    assert "Python API library documentation" in software


def test_clean_results_deduplicates_and_tracks_source_query():
    raw = [
        {"title": "First", "href": "https://Example.com/a#one", "body": "A", "_source_query": "iphone"},
        {"title": "Duplicate", "href": "https://example.com/a#two", "body": "dup"},
        {"title": "Second", "href": "https://other.example/b", "body": "B", "_source_query": "iphone reviews"},
        {"title": "Bad", "href": "javascript:alert(1)", "body": "bad"},
    ]
    cleaned = collector.clean_results(raw, "iphone", "in-en", "timestamp", 10)
    assert len(cleaned) == 2
    assert [row["rank"] for row in cleaned] == [1, 2]
    assert cleaned[0]["source_query"] == "iphone"
    assert cleaned[1]["source_query"] == "iphone reviews"


def test_paginated_mode_continues_after_short_pages(monkeypatch):
    calls = []

    class FakeDDGS:
        def __init__(self, timeout=20): pass
        def text(self, query, **kwargs):
            page = kwargs["page"]
            calls.append(page)
            if page == 1:
                return [{"title": "A", "href": "https://example.com/a"}]
            if page == 2:
                return [{"title": "B", "href": "https://example.com/b"}]
            return []

    monkeypatch.setattr(collector, "DDGS", FakeDDGS)
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.fetch_paginated_results("sample", 30, max_pages=4, page_delay_seconds=0)
    assert calls == [1, 2, 3]
    assert bundle["raw_unique_url_count"] == 2
    assert bundle["stop_reason"] == "provider_returned_empty_page"


def test_paginated_mode_preserves_partial_results_on_http_202(monkeypatch):
    class FakeDDGS:
        def __init__(self, timeout=20): pass
        def text(self, query, **kwargs):
            if kwargs["page"] == 1:
                return [{"title": f"A{i}", "href": f"https://example.com/{i}"} for i in range(10)]
            logging.getLogger().info("response: https://html.duckduckgo.com/html/ 202")
            raise RuntimeError("No results found.")

    monkeypatch.setattr(collector, "DDGS", FakeDDGS)
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.fetch_paginated_results("sample", 30, max_pages=3, page_delay_seconds=0,
        retry_delays=(), blocked_cooldown_seconds=0)
    assert bundle["pages_succeeded"] == 1
    assert bundle["raw_unique_url_count"] == 10
    assert bundle["page_errors"][0]["status_code"] == 202
    assert bundle["page_errors"][0]["category"] == "http_202_challenge_or_throttle"
    assert bundle["stop_reason"] == "provider_challenge_or_request_failure"


def test_hybrid_mode_uses_distinct_queries_and_deduplicates(monkeypatch):
    calls = []

    class FakeDDGS:
        def __init__(self, timeout=20): pass
        def text(self, query, **kwargs):
            calls.append((query, kwargs["page"]))
            return [
                {"title": f"{query} result {i}", "href": f"https://example.com/{query.replace(' ', '-')}/{i}"}
                for i in range(10)
            ]

    monkeypatch.setattr(collector, "DDGS", FakeDDGS)
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.fetch_hybrid_results("iphone", 30, max_queries=4,
        max_fallback_pages=0, query_delay_seconds=0)
    assert len(calls) == 3
    assert all(page == 1 for _, page in calls)
    assert bundle["queries_planned"] == ["iphone", "iphone reviews", "iphone specifications", "iphone price"]
    assert bundle["raw_unique_url_count"] == 30
    assert bundle["stop_reason"] == "requested_unique_result_limit_reached_during_query_diversification"


def test_hybrid_continues_to_other_variants_after_202(monkeypatch):
    calls = []

    class FakeDDGS:
        def __init__(self, timeout=20): pass
        def text(self, query, **kwargs):
            calls.append(query)
            if query == "iphone":
                logging.getLogger().info("response: https://html.duckduckgo.com/html/ 202")
                raise RuntimeError("No results found.")
            return [{"title": f"{query} {i}", "href": f"https://example.com/{query.replace(' ', '-')}/{i}"} for i in range(10)]

    monkeypatch.setattr(collector, "DDGS", FakeDDGS)
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.fetch_hybrid_results("iphone", 10, max_queries=3,
        max_fallback_pages=0, query_delay_seconds=0, retry_delays=(), blocked_cooldown_seconds=0)
    assert calls == ["iphone", "iphone reviews"]
    assert bundle["raw_unique_url_count"] == 10
    assert bundle["page_errors"][0]["status_code"] == 202
    assert bundle["pages"][0]["query"] == "iphone reviews"


def test_repeated_page_is_detected(monkeypatch):
    class FakeDDGS:
        def __init__(self, timeout=20): pass
        def text(self, query, **kwargs):
            return [{"title": f"A{i}", "href": "https://example.com/a"} for i in range(10)]

    monkeypatch.setattr(collector, "DDGS", FakeDDGS)
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.fetch_paginated_results("sample", 500, max_pages=4, page_delay_seconds=0)
    assert bundle["pages_succeeded"] == 2
    assert bundle["stop_reason"] == "provider_repeated_page"


def test_json_csv_exports_include_source_query(tmp_path: Path):
    rows = [{
        "rank": 1, "title": "Example", "url": "https://example.com", "domain": "example.com",
        "snippet": "snippet", "query": "example", "source_query": "example overview",
        "region": "in-en", "search_engine": "DuckDuckGo", "collected_at": "2026-11-01T00:00:00Z",
    }]
    json_path, csv_path = tmp_path / "cleaned.json", tmp_path / "cleaned.csv"
    collector.write_json(rows, json_path)
    collector.write_csv(rows, csv_path)
    assert '"source_query": "example overview"' in json_path.read_text(encoding="utf-8")
    assert "example overview" in csv_path.read_text(encoding="utf-8-sig")


def test_writeback_script_fetches_before_staging_and_uses_separate_log():
    script = (Path(__file__).parents[1] / "scripts" / "archive_run.sh").read_text(encoding="utf-8")
    assert script.index("sync_branch\n\ngit add") < script.index('git commit -m "chore(search): archive')
    assert "git pull --rebase" not in script
    assert 'tee -a "$RUN_DIR/run.log"' not in script
    assert "repository_writeback.log" in script


def test_hybrid_preserves_variant_results_when_pagination_fallback_gets_202(monkeypatch):
    class FakeDDGS:
        def __init__(self, timeout=20): pass
        def text(self, query, **kwargs):
            if kwargs["page"] == 1:
                return [{"title": f"{query}-{i}", "href": f"https://example.com/{query.replace(' ', '-')}/{i}"} for i in range(10)]
            logging.getLogger().info("response: https://html.duckduckgo.com/html/ 202")
            raise RuntimeError("No results found.")

    monkeypatch.setattr(collector, "DDGS", FakeDDGS)
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.fetch_hybrid_results("iphone", 100, max_queries=3,
        max_fallback_pages=2, query_delay_seconds=0, retry_delays=(), blocked_cooldown_seconds=0)
    assert bundle["pages_succeeded"] == 3
    assert bundle["raw_unique_url_count"] == 30
    assert bundle["stop_reason"] == "pagination_fallback_blocked_or_failed"
    assert bundle["page_errors"][-1]["status_code"] == 202


def test_all_hybrid_variants_blocked_are_returned_as_diagnostics(monkeypatch):
    class FakeDDGS:
        def __init__(self, timeout=20): pass
        def text(self, query, **kwargs):
            logging.getLogger().info("response: https://html.duckduckgo.com/html/ 202")
            raise RuntimeError("No results found.")

    monkeypatch.setattr(collector, "DDGS", FakeDDGS)
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.fetch_hybrid_results("iphone", 50, max_queries=2,
        max_fallback_pages=0, query_delay_seconds=0, retry_delays=(), blocked_cooldown_seconds=0)
    assert bundle["pages"] == []
    assert bundle["stop_reason"] == "all_query_variants_failed"
    assert len(bundle["page_errors"]) == 2
    assert all(error["category"] == "http_202_challenge_or_throttle" for error in bundle["page_errors"])
