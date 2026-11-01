from argparse import Namespace

from bs4 import BeautifulSoup

from scripts.provider_experiment import (
    _lite_next_form,
    _lite_result_rows,
    _flatten_topics,
    canonical_url,
    normalize_item,
)


def test_canonical_url_removes_invalid_and_keeps_query():
    assert canonical_url("https://EXAMPLE.com/a?b=1#fragment") == "https://example.com/a?b=1"
    assert canonical_url("javascript:alert(1)") == ""


def test_normalize_item_has_provider_page_provenance():
    row = normalize_item({"title": "Example", "href": "https://example.com/x", "body": "Snippet"},
                         "ddg-lite", "test query", 2, "in-en", 1, "2026-11-01T00:00:00Z")
    assert row["provider"] == "ddg-lite"
    assert row["page"] == 2
    assert row["domain"] == "example.com"


def test_lite_result_parser_extracts_title_url_and_snippet():
    html = '''<table>
      <tr><td><a class="result-link" href="https://example.com/a">Example title</a></td></tr>
      <tr><td class="result-snippet">Example snippet</td></tr>
    </table>'''
    rows = _lite_result_rows(BeautifulSoup(html, "html.parser"))
    assert rows == [{"title": "Example title", "href": "https://example.com/a", "body": "Example snippet"}]


def test_lite_next_form_uses_server_returned_continuation_fields():
    html = '''<form action="/lite/" method="post">
      <input type="hidden" name="q" value="test">
      <input type="hidden" name="vqd" value="token-value">
      <input type="hidden" name="nextParams" value="">
      <input type="hidden" name="s" value="10">
      <input type="hidden" name="api" value="d.js">
    </form>'''
    result = _lite_next_form(BeautifulSoup(html, "html.parser"))
    assert result[0] == "https://lite.duckduckgo.com/lite/"
    assert result[1]["vqd"] == "token-value"
    assert result[1]["s"] == "10"


def test_flatten_topics_handles_nested_topics():
    items = _flatten_topics([
        {"Name": "Group", "Topics": [{"Text": "Topic", "FirstURL": "https://example.com"}]},
        {"Text": "Other", "FirstURL": "https://other.example"},
    ])
    assert len(items) == 2
    assert items[0]["source_type"] == "related_topic"
