# Data Dictionary

## `raw_results.json`

| Field | Description |
|---|---|
| `search_engine` | Always `DuckDuckGo` |
| `strategy` | `hybrid` or `paginated` |
| `query` | Primary user query |
| `region` | DDGS region code |
| `requested_unique_result_limit` | User-selected target |
| `provider_page_size` | Fixed at 10 per request |
| `queries_planned` | Distinct query variants scheduled by hybrid mode |
| `queries_attempted` | Distinct queries with a successful or failed request |
| `pages_attempted` | Successful pages plus failed page requests |
| `pages_succeeded` | Successfully returned pages, including empty pages |
| `raw_result_count` | Number of flattened raw records |
| `raw_unique_url_count` | Number of unique valid URLs before final output truncation |
| `stop_reason` | Machine-readable completion/stop reason |
| `page_errors` | Failed query/page, HTTP status if observed, classification, and message |
| `pages[]` | Query, page number, requested size, returned count, new unique count, and original provider response objects |
| `raw_results[]` | Flattened provider records with `_source_query` and `_source_page` provenance |

## `cleaned_results.json` / `cleaned_results.csv`

| Field | Description |
|---|---|
| `rank` | Sequential rank in cleaned export |
| `title` | Provider result title |
| `url` | Normalized URL |
| `domain` | URL hostname |
| `snippet` | Provider description/snippet |
| `query` | Original user query |
| `source_query` | Query variant that returned the result |
| `region` | Search region |
| `search_engine` | `DuckDuckGo` |
| `collected_at` | UTC collection timestamp |

## `metadata.json`

Stores GitHub workflow name, run ID/attempt/number, actor, ref, source SHA, primary query, requested limit, region, strategy, user-supplied additional queries, max query count, provider page size, collector step outcome, and UTC timestamp.

## Stop reasons

Examples include `requested_unique_result_limit_reached`, `requested_unique_result_limit_reached_during_query_diversification`, `provider_returned_empty_page`, `provider_repeated_page`, `provider_challenge_or_request_failure`, `pagination_fallback_blocked_or_failed`, `query_variants_exhausted`, and `page_cap_reached`.
