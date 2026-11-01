from pathlib import Path

import pytest

from src.search_collector import (
    ALLOWED_LIMITS,
    collect_results,
    extract_domain,
    normalize_url,
    write_csv,
    write_json,
)


def test_allowed_limits_are_expected():
    assert ALLOWED_LIMITS == {10, 30, 50, 100, 200, 500}


def test_normalize_url_removes_fragment_and_normalizes_scheme_host():
    assert normalize_url("HTTPS://Example.COM/a#section") == "https://example.com/a"


def test_normalize_url_rejects_non_http_urls():
    assert normalize_url("javascript:alert(1)") == ""
    assert normalize_url("not a url") == ""


def test_extract_domain():
    assert extract_domain("https://www.example.com/path") == "www.example.com"


def test_collect_results_deduplicates_and_respects_limit(monkeypatch):
    import src.search_collector as collector

    class FakeDDGS:
        def text(self, *args, **kwargs):
            return [
                {"title": "First", "href": "https://example.com/a#one", "body": "A"},
                {"title": "Duplicate", "href": "https://example.com/a#two", "body": "A"},
                {"title": "Second", "href": "https://other.example/b", "body": "B"},
            ]

    monkeypatch.setattr(collector, "DDGS", FakeDDGS)
    rows = collect_results("sample query", 10)

    assert len(rows) == 2
    assert [row["rank"] for row in rows] == [1, 2]
    assert rows[0]["url"] == "https://example.com/a"
    assert rows[0]["domain"] == "example.com"
    assert rows[0]["search_engine"] == "DuckDuckGo"


def test_collect_results_rejects_invalid_limit():
    with pytest.raises(ValueError):
        collect_results("query", 25)


def test_export_files(tmp_path: Path):
    rows = [{
        "rank": 1,
        "title": "Example",
        "url": "https://example.com",
        "domain": "example.com",
        "snippet": "A snippet",
        "query": "example",
        "region": "in-en",
        "search_engine": "DuckDuckGo",
        "collected_at": "2026-11-01T00:00:00+00:00",
    }]

    json_path = write_json(rows, tmp_path)
    csv_path = write_csv(rows, tmp_path)

    assert json_path.exists()
    assert csv_path.exists()
    assert '"title": "Example"' in json_path.read_text(encoding="utf-8")
    assert "Example" in csv_path.read_text(encoding="utf-8-sig")
