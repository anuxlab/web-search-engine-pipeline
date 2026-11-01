# DuckDuckGo Web Search Collector

A manual-only GitHub Actions pipeline that collects DuckDuckGo text-search
results, preserves the raw provider response, creates a normalized unique
dataset, logs each run, and commits the run archive back to the repository.

## What changed in this version

Every workflow execution creates a permanent run directory under `runs/`.
The runner commits that directory to the branch from which the workflow was
manually dispatched. It also uploads the same directory as a downloadable
GitHub Actions artifact (90-day retention).

Each run archive contains:

| File | Purpose |
|---|---|
| `raw_results.json` | Page-by-page raw provider dictionaries plus flattened raw records, before cleaning |
| `cleaned_results.json` | Normalized, unique records |
| `cleaned_results.csv` | Spreadsheet export of the cleaned records |
| `run.log` | Runner environment, dependency installation output, and collector console logs |
| `collector.log` | Python application log |
| `metadata.json` | Workflow run ID, attempt, actor, branch, commit and inputs |
| `summary.txt` | Requested count, raw count, cleaned count and status |

The Actions UI remains the authoritative place for the complete platform-level
job log (checkout/setup/action internals). The archived `run.log` captures the
commands and Python collection activity executed in the collector shell step.

## Workflow inputs

- Search query (required text)
- Result maximum: `10`, `30`, `50`, `100`, `200`, `500`
- Region: `in-en`, `us-en`, `uk-en`, `wt-wt`
- Page size: `10`, `20`, `25`, `30`, or `50` results per request
- Sequential pagination, exponential retries, inter-page delay, and duplicate-page detection

Only `workflow_dispatch` is configured; pushes and pull requests do not start
this workflow.

## Repository structure

```text
.github/workflows/duckduckgo-search.yml
src/search_collector.py
tests/test_search_collector.py
docs/
  ARCHITECTURE.md
  DATA_DICTIONARY.md
  OPERATIONS.md
  LIMITATIONS.md
runs/
  YYYY/MM/DD/<run-id>-attempt-<n>-<query-slug>/
    raw_results.json
    cleaned_results.json
    cleaned_results.csv
    run.log
    collector.log
    metadata.json
    summary.txt
```

## Setup and execution

1. Add the project files to a GitHub repository and push the default branch.
2. In repository **Settings → Actions → General → Workflow permissions**, allow
   **Read and write permissions**. This is required for the runner's commit.
3. Open **Actions → DuckDuckGo Web Search Collector → Run workflow**.
4. Enter a query and select the result maximum, region, and page size.
5. After completion, inspect the `runs/` directory in the repository or download
   the workflow artifact.

The workflow uses the built-in `GITHUB_TOKEN`; no personal access token or
search API key is required.

## Branch and repository requirements

- The run archive is committed to the same branch selected in the manual
  workflow dispatch (`github.ref_name`).
- The selected branch must allow pushes from `GITHUB_TOKEN`. Branch protection
  rules requiring a pull request or blocking GitHub Actions writes can prevent
  the commit.
- Commits made using `GITHUB_TOKEN` do not trigger another workflow run, which
  prevents a push-trigger loop. This workflow is manual-only in any case.
- Concurrent runs on the same branch are serialized by the workflow concurrency
  group to reduce push races.

## Local execution

Python 3.11+:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt

python src/search_collector.py \
  --query "electric vehicle routing problem" \
  --limit 50 \
  --region in-en \
  --page-size 25 \
  --page-delay 1.0 \
  --output outputs/local-test

pytest -q
```

## Important interpretation of the result limit

The selected number is a maximum requested unique-result count, not a guarantee.
The collector requests multiple pages using DDGS's `page` argument, preserves
all page responses, and deduplicates URLs across pages. Pagination stops when
the target is reached, a page is empty/short, the provider repeats a page, two
consecutive pages add no new URLs, a later page fails after retries, or the
safety page cap is reached. Provider-side result depth remains outside the
collector's control.

## Scope

This project collects search-result metadata only. It does not crawl result
pages, download PDFs, or extract full webpage text. See `docs/LIMITATIONS.md`
for the staged roadmap and operational caveats.
