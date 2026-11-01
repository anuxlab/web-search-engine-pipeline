# Output data dictionary

Each JSON array item and CSV row represents one unique search-result URL.

| Field | Type | Meaning |
|---|---|---|
| `rank` | integer | Position in the deduplicated result list, starting at 1 |
| `title` | string | Search-result title supplied by DuckDuckGo |
| `url` | string | Normalized HTTP(S) result URL, without fragment |
| `domain` | string | Hostname parsed from the result URL |
| `snippet` | string | Search-result summary/snippet |
| `query` | string | Query submitted by the user |
| `region` | string | DuckDuckGo region code used for the request |
| `search_engine` | string | Constant value `DuckDuckGo` |
| `collected_at` | string | ISO-8601 UTC timestamp for the collection batch |

## Files

### `search_results.json`

UTF-8 JSON array. Suitable for downstream Python processing and enrichment.

### `search_results.csv`

UTF-8 with BOM for improved compatibility with spreadsheet software.

### `summary.txt`

Human-readable execution report containing the query, requested maximum,
actual number of unique results, timestamp, and status.
