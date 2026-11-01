# Data dictionary

## Raw file: `raw_results.json`

A JSON object containing the query settings, pagination summary, page-level
records, and a flattened `raw_results` array. Each `pages[]` item contains:

- `page`: page number requested from DDGS.
- `requested_batch_size`: configured results requested per page.
- `returned_count`: raw records returned on that page.
- `new_unique_url_count`: number of previously unseen valid URLs on that page.
- `results`: original dictionaries returned by the DDGS client.

Top-level fields include `requested_unique_result_limit`, `page_size`,
`pages_attempted`, `pages_succeeded`, `raw_result_count`,
`raw_unique_url_count`, `stop_reason`, `page_errors`, `pages`, and
`raw_results`. This is raw at the DDGS client-response boundary, not a
packet-level HTTP capture.

## Cleaned files: `cleaned_results.json` and `cleaned_results.csv`

| Field | Type | Description |
|---|---|---|
| `rank` | integer | Sequential rank after cleaning |
| `title` | string | Search-result title |
| `url` | string | Normalized HTTP(S) URL without fragment |
| `domain` | string | URL hostname |
| `snippet` | string | Search-result snippet/body |
| `query` | string | Submitted query |
| `region` | string | Region code |
| `search_engine` | string | `DuckDuckGo` |
| `collected_at` | string | ISO-8601 UTC timestamp |

## `metadata.json`

Contains workflow name, run ID, attempt, run number, actor, Git ref, commit SHA,
query, requested maximum, region, provider page size, collector-step outcome, and
recorded timestamp.

## Logs and summary

`run.log` captures the collector shell step, including Python version and pip
installation output. `collector.log` captures timestamped page-level application
events and exceptions. `summary.txt` reports raw, cleaned, page, and stop-reason
counts.
