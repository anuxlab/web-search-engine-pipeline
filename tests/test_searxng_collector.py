from __future__ import annotations
import csv
import json
from pathlib import Path

import pytest
import requests

from src import searxng_collector as collector


class FakeResponse:
    def __init__(self, status=200, payload=None, text="", headers=None):
        self.status_code = status
        self._payload = payload if payload is not None else {"results": []}
        self.text = text
        self.headers = headers or {}
    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []
    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class SequenceClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []
    def fetch_page(self, query, page, region):
        self.calls.append((query, page, region))
        value = self.pages.pop(0)
        if isinstance(value, Exception):
            raise value
        return value, {"unresponsive_engines": []}, 200


def result(n, host="example.com", engine="duckduckgo"):
    return {"title": f"Result {n}", "url": f"https://{host}/{n}", "content": f"Snippet {n}",
            "engine": engine, "engines": [engine]}



def test_client_sends_pageno_bang_filter_and_region_mapping():
    session = FakeSession([FakeResponse(payload={"results": [result(1)]})])
    client = collector.SearXNGClient("http://localhost:8888/", session=session)
    rows, payload, status = client.fetch_page("sample query", 4, "in-en")
    assert status == 200 and len(rows) == 1
    assert session.calls[0][0] == "http://localhost:8888/search"
    assert session.calls[0][1] == {
        "q": "!ddg sample query", "format": "json", "pageno": 4,
        "language": "en-IN", "safesearch": 1,
    }


def test_client_classifies_http_202_and_403():
    client = collector.SearXNGClient("http://localhost", session=FakeSession([
        FakeResponse(202, text="interstitial"), FakeResponse(403, text="format disabled")]))
    with pytest.raises(collector.SearXNGRequestError) as e202:
        client.fetch_page("q", 1, "in-en")
    assert e202.value.status_code == 202
    assert e202.value.category == "http_202_interstitial_or_challenge_signal"
    with pytest.raises(collector.SearXNGRequestError) as e403:
        client.fetch_page("q", 1, "in-en")
    assert e403.value.category == "http_403_forbidden_or_format_disabled"


def test_client_rejects_invalid_json_and_invalid_schema():
    client = collector.SearXNGClient("http://localhost", session=FakeSession([
        FakeResponse(payload=ValueError("bad json")), FakeResponse(payload={"not_results": []})]))
    with pytest.raises(collector.SearXNGRequestError) as invalid_json:
        client.fetch_page("q", 1, "in-en")
    assert invalid_json.value.category == "invalid_json"
    with pytest.raises(collector.SearXNGRequestError) as invalid_schema:
        client.fetch_page("q", 1, "in-en")
    assert invalid_schema.value.category == "invalid_response_schema"


def test_collect_paginates_until_target_and_preserves_page_provenance(monkeypatch):
    client = SequenceClient([
        [result(i) for i in range(1, 11)],
        [result(i) for i in range(11, 21)],
    ])
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.collect_query("research", 15, max_pages=10, page_delay=0, client=client)
    assert bundle["status"] == "SUCCESS"
    assert bundle["unique_result_count"] == 15
    assert bundle["pages_succeeded"] == 2
    assert [call[1] for call in client.calls] == [1, 2]
    assert bundle["cleaned_results"][0]["source_page"] == 1
    assert bundle["cleaned_results"][-1]["source_page"] == 2
    assert all(row["source_engine"] == "duckduckgo" for row in bundle["cleaned_results"])


def test_collect_deduplicates_across_pages_and_stops_on_repeated_page(monkeypatch):
    same = [result(i) for i in range(1, 6)]
    client = SequenceClient([same, same])
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.collect_query("q", 100, max_pages=10, page_delay=0, client=client)
    assert bundle["unique_result_count"] == 5
    assert bundle["stop_reason"] == "provider_repeated_page"
    assert bundle["pages_succeeded"] == 2


def test_collect_stops_after_duplicate_only_streak(monkeypatch):
    page1 = [result(i) for i in range(1, 4)]
    # Same URLs in different orders avoid the exact-page fingerprint guard.
    page2 = [result(i) for i in (3, 2, 1)]
    page3 = [result(i) for i in (2, 1, 3)]
    page4 = [result(i) for i in (1, 3, 2)]
    client = SequenceClient([page1, page2, page3, page4])
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.collect_query("q", 100, max_pages=10, page_delay=0, client=client)
    assert bundle["pages_attempted"] == 4
    assert bundle["stop_reason"] == "3_consecutive_pages_without_new_urls"


def test_collect_preserves_partial_results_when_later_page_is_blocked(monkeypatch):
    client = SequenceClient([[result(i) for i in range(1, 6)],
                             collector.SearXNGRequestError("HTTP 202 interstitial", 202,
                                 "http_202_interstitial_or_challenge_signal")])
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.collect_query("q", 50, max_pages=5, page_delay=0, retries=0, client=client)
    assert bundle["status"] == "PARTIAL"
    assert bundle["unique_result_count"] == 5
    assert bundle["pages_succeeded"] == 1
    assert bundle["page_errors"][0]["status_code"] == 202
    assert bundle["stop_reason"] == "partial_results_provider_request_failed"


def test_collect_retries_429_and_then_succeeds(monkeypatch):
    session = FakeSession([FakeResponse(429, text="slow down"), FakeResponse(payload={"results": [result(1)]})])
    client = collector.SearXNGClient("http://localhost", session=session)
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    monkeypatch.setattr(collector.random, "uniform", lambda a, b: 0)
    bundle = collector.collect_query("q", 1, max_pages=2, page_delay=0, retries=1,
                                     retry_backoff=0, client=client)
    assert bundle["status"] == "SUCCESS"
    assert bundle["retry_attempt_count"] == 2
    assert len(session.calls) == 2


def test_collect_retries_network_error(monkeypatch):
    session = FakeSession([requests.ConnectionError("temporary"),
                           FakeResponse(payload={"results": [result(1)]})])
    client = collector.SearXNGClient("http://localhost", session=session)
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    monkeypatch.setattr(collector.random, "uniform", lambda a, b: 0)
    bundle = collector.collect_query("q", 1, max_pages=2, page_delay=0, retries=1,
                                     retry_backoff=0, client=client)
    assert bundle["status"] == "SUCCESS"
    assert bundle["retry_attempt_count"] == 2


def test_collect_filters_non_duckduckgo_provenance():
    client = SequenceClient([[result(1, engine="google"), result(2, engine="duckduckgo")]])
    bundle = collector.collect_query("q", 1, max_pages=1, page_delay=0, client=client)
    assert bundle["raw_result_count"] == 2
    assert bundle["duckduckgo_result_count"] == 1
    assert bundle["cleaned_results"][0]["url"].endswith("/2")


def test_collect_empty_and_engine_unresponsive_paths():
    empty = SequenceClient([[]])
    no_results = collector.collect_query("q", 5, max_pages=3, page_delay=0, client=empty)
    assert no_results["status"] == "NO_RESULTS"
    assert no_results["stop_reason"] == "provider_returned_empty_page"

    class UnresponsiveClient:
        def fetch_page(self, query, page, region):
            return [], {"unresponsive_engines": ["duckduckgo"]}, 200
    unresponsive = collector.collect_query("q", 5, max_pages=3, page_delay=0, client=UnresponsiveClient())
    assert unresponsive["status"] == "FAILED"
    assert unresponsive["stop_reason"] == "duckduckgo_engine_unresponsive"


def test_short_pages_do_not_imply_exhaustion(monkeypatch):
    client = SequenceClient([[result(1)], [result(2)]])
    monkeypatch.setattr(collector.time, "sleep", lambda _: None)
    bundle = collector.collect_query("q", 2, max_pages=5, page_delay=0, client=client)
    assert bundle["status"] == "SUCCESS"
    assert bundle["pages_succeeded"] == 2


def test_collect_respects_max_page_cap_and_input_validation():
    client = SequenceClient([[result(i)] for i in range(1, 4)])
    bundle = collector.collect_query("q", 100, max_pages=2, page_delay=0, client=client)
    assert bundle["pages_attempted"] == 2
    assert bundle["stop_reason"] == "max_pages_reached"
    with pytest.raises(ValueError): collector.collect_query("", 10, client=client)
    with pytest.raises(ValueError): collector.collect_query("q", 1001, client=client)
    with pytest.raises(ValueError): collector.collect_query("q", 10, max_pages=101, client=client)
    with pytest.raises(ValueError): collector.collect_query("q", 10, region="xx-xx", client=client)
    with pytest.raises(ValueError): collector.collect_query("q", 10, retry_backoff=-1, client=client)
    with pytest.raises(ValueError): collector.collect_query("x" * 513, 10, client=client)


def test_output_files_and_csv_are_written(tmp_path: Path):
    client = SequenceClient([[result(1)]])
    bundle = collector.collect_query("q", 1, max_pages=1, page_delay=0, client=client)
    collector.write_outputs(bundle, tmp_path)
    assert json.loads((tmp_path / "raw_results.json").read_text())["provider"] == "searxng"
    assert json.loads((tmp_path / "cleaned_results.json").read_text())[0]["source_engine"] == "duckduckgo"
    assert "SUCCESS" in (tmp_path / "summary.txt").read_text()
    with (tmp_path / "cleaned_results.csv").open(encoding="utf-8-sig") as handle:
        assert len(list(csv.DictReader(handle))) == 1


def test_cli_creates_output_directory_and_files(tmp_path, monkeypatch):
    class FakeProductionClient:
        def __init__(self, base_url):
            self.base_url = base_url
        def fetch_page(self, query, page, region):
            return [result(1)], {"unresponsive_engines": []}, 200
    monkeypatch.setattr(collector, "SearXNGClient", FakeProductionClient)
    output = tmp_path / "not-yet-created" / "result"
    code = collector.main(["--query", "smoke test", "--limit", "1", "--max-pages", "1",
                           "--page-delay", "0", "--output", str(output)])
    assert code == 0
    assert (output / "raw_results.json").exists()
    assert (output / "cleaned_results.csv").exists()
    assert (output / "collector.log").exists()
