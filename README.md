# DuckDuckGo Web Search Collection Pipeline

A manually triggered GitHub Actions workflow that collects DuckDuckGo search results, preserves provider responses, produces deduplicated JSON/CSV exports, and archives every run in the repository and as a GitHub Actions artifact.

**Search provider:** DuckDuckGo only. The project does not silently switch to Bing, Google, Brave, or another provider. No external API key is required.

## Collection strategies

The workflow offers two selectable strategies:

### 1. Hybrid (recommended default)

1. Runs the primary query.
2. Generates a small set of deterministic, domain-aware query variants (for example, product queries get review/specification/price variants; software queries get documentation/tutorial/examples variants; research queries get paper/survey/methodology variants).
3. Runs each variant as an independent first-page request and merges results by normalized URL.
4. If the requested unique-result target has not been reached, attempts further pages of the primary query as a fallback.
5. Records failed or blocked requests and continues with other variants where possible.

You can supply optional additional queries in the workflow's `additional_queries` field, one per line. These are added after the automatic variants, subject to `max_queries`.

### 2. Paginated (legacy method, retained)

Uses only the original query and requests sequential pages. Short pages do not automatically mean exhaustion. It stops on an empty page, repeated page, duplicate-only streak, requested target, safety cap, or a recorded provider error.

## Why hybrid exists

The previous run successfully collected page 1 but received HTTP 202 from `html.duckduckgo.com` on page 2. The DDGS client then surfaced a generic `No results found` exception. The collector now captures the DDGS response-status log, classifies HTTP 202 as a challenge/throttling signal rather than an empty page, waits before one retry, and preserves partial results. Hybrid mode reduces dependence on page 2 by collecting multiple query variants first.

HTTP 202 does not prove a specific cause (such as a CAPTCHA); it is recorded as `http_202_challenge_or_throttle`. The collector does not attempt to bypass access controls. DuckDuckGo may still limit or block requests, and no fixed result count is guaranteed.

## GitHub Actions setup

1. Put the project files at the root of your repository.
2. Ensure GitHub Actions is enabled.
3. In **Settings → Actions → General → Workflow permissions**, allow read and write permissions if your organization/repository policy requires this setting. The workflow also declares `permissions: contents: write`.
4. Open **Actions → DuckDuckGo Web Search Collector → Run workflow**.
5. Choose a query, result target, region, and strategy. Hybrid is recommended.
6. Optionally provide related queries, one per line.

The workflow is intentionally `workflow_dispatch` only. It does not run on `push`, `pull_request`, or a schedule. Workflow commits therefore do not trigger another search run.

### Workflow inputs

| Input | Purpose | Default |
|---|---|---|
| `search_query` | Primary search phrase | Required |
| `result_limit` | Unique cleaned URL target: 10, 30, 50, 100, 200, 500 | 50 |
| `region` | DuckDuckGo region | `in-en` |
| `collection_strategy` | `hybrid` or `paginated` | `hybrid` |
| `additional_queries` | Optional extra queries, one per line | Empty |
| `max_queries` | Maximum distinct queries including primary | 8 |

## Output files

Every execution creates a unique folder under `runs/YYYY/MM/DD/<run-id>-attempt-<n>-<query>/`.

| File | Contents |
|---|---|
| `raw_results.json` | Page-level provider responses, flattened raw records, source-query provenance, errors, and stop reason |
| `cleaned_results.json` | Deduplicated and normalized results |
| `cleaned_results.csv` | Spreadsheet-friendly cleaned results |
| `collector.log` | Collector application logs |
| `run.log` | Environment, dependency installation, collector invocation, archive preparation, and metadata logs |
| `repository_writeback.log` | Git synchronization/write-back transcript; the artifact copy contains the complete script transcript |
| `metadata.json` | Run ID, attempt, query, selected strategy, region, commit SHA, and workflow inputs |
| `summary.txt` | Counts, status, strategy, and stop reason |

The complete run folder is uploaded as a GitHub Actions artifact (90-day retention) and committed to the repository. GitHub's own platform-level job logs remain available in the Actions run UI.

## Local use

```bash
python -m pip install -r requirements.txt

# Recommended hybrid strategy
python src/search_collector.py \
  --query "iphone" --limit 100 --region in-en \
  --strategy hybrid --max-queries 8 \
  --additional-queries $'Apple iPhone\niPhone camera reviews' \
  --page-delay 3 --blocked-cooldown 20 --output outputs/example

# Retained single-query pagination strategy
python src/search_collector.py \
  --query "iphone" --limit 100 --region in-en \
  --strategy paginated --page-delay 3 --output outputs/paginated
```

## Development and tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m py_compile src/search_collector.py tests/test_search_collector.py
bash -n scripts/archive_run.sh
# or run all local checks together
bash scripts/validate.sh
```

Tests use a fake DDGS client and do not make live search requests. A live Actions run is required to assess current provider availability and practical result depth.

## Important interpretation

`result_limit` is a target, not a provider guarantee. `SUCCESS` means the target number of unique URLs was reached; `PARTIAL` means some valid results were collected but the target was not reached; `NO_RESULTS` means no valid results were returned; `FAILED` means the collector could not complete its collection operation. HTTP 202, 403, and 429 are recorded as provider request problems, not as proof that no results exist.
