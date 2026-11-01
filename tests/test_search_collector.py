from pathlib import Path

from src import search_collector as collector
from src.search_collector import (
    ALLOWED_LIMITS,
    clean_results,
    normalize_url,
    extract_domain,
    write_csv,
    write_json,
)


def test_allowed_limits():
    assert ALLOWED_LIMITS == {10, 30, 50, 100, 200, 500}


def test_url_normalization_and_validation():
    assert normalize_url("HTTPS://Example.COM/path#part") == "https://example.com/path"
    assert normalize_url("javascript:alert(1)") == ""
    assert normalize_url("not a url") == ""


def test_domain_extraction():
    assert extract_domain("https://www.example.com/path") == "www.example.com"


def test_clean_results_deduplicates_and_ranks():
    raw = [
        {"title": "First", "href": "https://Example.com/a#one", "body": "A"},
        {"title": "Duplicate", "href": "https://example.com/a#two", "body": "dup"},
        {"title": "Second", "href": "https://other.example/b", "body": "B"},
        {"title": "Bad", "href": "javascript:alert(1)", "body": "bad"},
    ]
    cleaned = clean_results(raw, "sample", "in-en", "timestamp", 10)
    assert len(cleaned) == 2
    assert [row["rank"] for row in cleaned] == [1, 2]
    assert cleaned[0]["title"] == "First"
    assert cleaned[0]["url"] == "https://example.com/a"


def test_paginated_collection_fetches_multiple_pages_and_deduplicates(monkeypatch):
    calls = []

    class FakeDDGS:
        def __init__(self, timeout=20):
            pass

        def text(self, query, **kwargs):
            calls.append(kwargs["page"])
            if kwargs["page"] == 1:
                rows = [
                    {"title": f"Item {i}", "href": f"https://example.com/{i}"}
                    for i in range(1, 10)
                ]
                rows.append({"title": "Duplicate one", "href": "https://example.com/1#fragment"})
                return rows
            if kwargs["page"] == 2:
                rows = [
                    {"title": "Duplicate nine", "href": "https://example.com/9#fragment"},
                    {"title": "Item ten", "href": "https://example.com/10"},
                ]
                rows.extend(
                    {"title": f"Repeat {i}", "href": f"https://example.com/{i}"}
                    for i in range(1, 9)
                )
                return rows
            return []

    monkeypatch.setattr(collector, "DDGS", FakeDDGS)
    bundle = collector.fetch_paginated_results(
        "query", 10, page_size=10, page_delay_seconds=0
    )
    assert calls == [1, 2]
    assert bundle["raw_result_count"] == 20
    assert bundle["raw_unique_url_count"] == 10
    assert bundle["pages_succeeded"] == 2
    cleaned = clean_results(bundle["raw_results"], "query", "in-en", "ts", 10)
    assert len(cleaned) == 10


def test_pagination_stops_when_provider_repeats_page(monkeypatch):
    class FakeDDGS:
        def __init__(self, timeout=20):
            pass

        def text(self, query, **kwargs):
            return [
                {"title": f"A{i}", "href": "https://example.com/a"}
                for i in range(10)
            ]

    monkeypatch.setattr(collector, "DDGS", FakeDDGS)
    bundle = collector.fetch_paginated_results(
        "query", 500, page_size=10, page_delay_seconds=0
    )
    assert bundle["pages_succeeded"] == 2
    assert bundle["stop_reason"] == "provider_repeated_page"


def test_later_page_failure_returns_partial_results(monkeypatch):
    class FakeDDGS:
        def __init__(self, timeout=20):
            pass

        def text(self, query, **kwargs):
            if kwargs["page"] == 1:
                return [
                    {"title": f"A{i}", "href": f"https://example.com/{i}"}
                    for i in range(10)
                ]
            raise RuntimeError("simulated rate limit")

    monkeypatch.setattr(collector, "DDGS", FakeDDGS)
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.fetch_paginated_results(
        "query", 30, page_size=10, retries=2, page_delay_seconds=0
    )
    assert bundle["pages_succeeded"] == 1
    assert bundle["raw_result_count"] == 10
    assert bundle["stop_reason"] == "later_page_failed_partial_results"
    assert len(bundle["page_errors"]) == 1


def test_json_and_csv_exports(tmp_path: Path):
    rows = [{
        "rank": 1, "title": "Example", "url": "https://example.com",
        "domain": "example.com", "snippet": "snippet", "query": "example",
        "region": "in-en", "search_engine": "DuckDuckGo",
        "collected_at": "2026-11-01T00:00:00Z",
    }]
    json_path = tmp_path / "cleaned_results.json"
    csv_path = tmp_path / "cleaned_results.csv"
    write_json(rows, json_path)
    write_csv(rows, csv_path)
    assert '"title": "Example"' in json_path.read_text(encoding="utf-8")
    assert "Example" in csv_path.read_text(encoding="utf-8-sig")
