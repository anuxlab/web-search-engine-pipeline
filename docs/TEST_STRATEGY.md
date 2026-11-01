# Test Strategy and Coverage

All tests are deterministic and network-free. Provider interactions are injected through fake clients or fake `requests.Session` responses.

## Unit tests

| Layer | Cases |
|---|---|
| Query parser | blank/comment lines, `::` and TAB limit overrides, defaults, duplicates, invalid limits, empty input, query count and length caps |
| Matrix builder | query × repeat cross-product, stable indices, repeat-count validation |
| HTTP client | `!ddg` routing, `pageno`, language mapping, HTTP 202/403 classification, malformed JSON and invalid schema |
| Retry policy | 429 retry, network retry, bounded attempts, successful retry resets prior error state |
| Pagination | sequential page numbers, target stop, max-page stop, empty page, repeated page, duplicate-only streak |
| Provenance | only DuckDuckGo-attributed records are kept; other engine records are excluded |
| Data quality | URL scheme validation, host normalization, fragment removal, URL deduplication and source-page provenance |
| Failure preservation | later-page HTTP 202 retains earlier valid pages and emits a partial status |
| Persistence | raw JSON, cleaned JSON, CSV and summary are written |
| Aggregation | per-query archive layout, missing artifacts, aggregate CSV, exact repeatability and pairwise Jaccard |
| Workflow | manual-only trigger, dynamic matrix, fail-fast disabled, DuckDuckGo-only settings |
| Write-back | existing fetch/rebase-before-stage ordering remains covered by the legacy regression test |

## Acceptance criteria for a live run

A live run should be considered a valid collection-layer acceptance run only when:

1. all matrix tasks have an archived artifact or an explicit missing-artifact record;
2. SearXNG starts with the pinned image and the configured DuckDuckGo-only engine set;
3. the collector receives valid JSON and preserves page-level HTTP/timing diagnostics;
4. every retained result has DuckDuckGo engine attribution and a valid HTTP(S) URL;
5. pages are requested sequentially and stop reasons are explicit;
6. the requested unique-result target is either reached or a partial/failure reason is recorded;
7. repeated runs produce repeatability metrics;
8. aggregation creates the batch archive and one repository write-back succeeds.

A single green workflow is not enough to claim long-term reliability. Run the staged depth/repeatability progression in `docs/OPERATIONS.md` and retain its artifacts for comparison.
