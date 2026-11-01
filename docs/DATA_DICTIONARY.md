# Data Dictionary

## Per-query `raw_results.json`

| Field | Description |
|---|---|
| `provider` | `searxng` |
| `search_engine` | Human-readable upstream engine label (`DuckDuckGo`) |
| `engine_filter` | Expected SearXNG engine name (`duckduckgo`) |
| `query` | Exact normalized user query |
| `region` / `language` | Workflow region and SearXNG language code |
| `requested_unique_result_limit` | Per-query unique URL target |
| `max_pages` | Hard page cap |
| `pages_attempted` | Successful pages plus terminal page failures |
| `pages_succeeded` / `pages_failed` | HTTP/JSON-successful pages and failed pages |
| `raw_result_count` | All result records returned by SearXNG across successful pages |
| `duckduckgo_result_count` | Raw records explicitly attributed to DuckDuckGo |
| `unique_result_count` | Valid, deduplicated DuckDuckGo URLs retained up to the target |
| `target_reached` | Whether the requested unique-result target was reached |
| `status` | `SUCCESS`, `PARTIAL`, `NO_RESULTS`, or `FAILED` |
| `stop_reason` | Explicit pagination terminal condition |
| `retry_attempt_count` | Total HTTP/network attempts, including retries |
| `total_request_seconds` | Sum of page request durations, excluding inter-page sleeps |
| `page_errors` | Page number, HTTP status, category, error and attempts |
| `pages[]` | Page diagnostics, engine counts, raw response result records and timings |
| `raw_results[]` | Flattened DuckDuckGo-attributed provider records with source query/page provenance |

## Cleaned result record

| Field | Description |
|---|---|
| `rank` | Rank in the deduplicated query result list |
| `title` | Search result title |
| `url` | Normalized HTTP(S) URL with fragment removed |
| `domain` | URL hostname |
| `snippet` | SearXNG content/snippet field |
| `query` / `source_query` | Query that generated the result |
| `source_page` | SearXNG page number |
| `source_engine` | Verified upstream engine attribution (`duckduckgo`) |
| `provider` | `searxng` |
| `region` | Requested region |
| `collected_at` | UTC timestamp for the query collection |
| `engines` | SearXNG engine attribution list |

## Batch-level files

- `batch_metadata.json`: run identifiers, commit SHA, workflow manifest, artifact count and batch status.
- `batch_summary.json`: per-query target, repeat count, counts per repeat, min/max/mean, exact set equality, mean pairwise Jaccard and target-hit status.
- `aggregate_results.csv`: all cleaned rows, with query index and repeat index.
- `repeatability.csv`: one row per query/repeat, with counts, page depth, request time and stop reason.
- `queries/<query-id>/repeat-NN/`: full raw and cleaned artifact for one independent repeat.

## Timing semantics

`elapsed_seconds` on a page is wall-clock time spent inside the SearXNG HTTP request (including response JSON decoding as part of client execution). `total_request_seconds` is the sum of those page request durations. It excludes inter-page delays, Docker startup, dependency installation, artifact transfer, aggregation and Git write-back. GitHub Actions job duration is a separate platform measurement and must not be compared directly to request latency.
