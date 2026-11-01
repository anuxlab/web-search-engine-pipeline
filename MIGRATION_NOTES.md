# Migration Notes — 3.0.0

This is an incremental extension of the existing repository, not a clean-room rewrite.

## Preserved

- Existing `src/search_collector.py` DDGS hybrid/paginated implementation and its regression tests.
- Existing provider experiment script, four independent provider experiment workflows, SearXNG experiment settings history, and provider experiment documentation.
- Existing run archive layout and `scripts/archive_run.sh` fetch/rebase-before-stage logic.
- Existing manual-only workflow policy and GitHub Actions artifact/write-back approach.

## Added

- `src/searxng_collector.py`: production collection implementation using SearXNG JSON API and DuckDuckGo-only provenance.
- `src/query_batch.py`: multiline query parsing, per-query targets, validation and query/repeat matrix construction.
- `scripts/prepare_batch.py`: GitHub Actions matrix and batch manifest preparation.
- `scripts/aggregate_batch.py`: artifact aggregation, CSV exports and repeatability metrics.
- `requirements-searxng.txt`: minimal production runtime dependency.
- `config/searxng-image.txt`: centrally pinned SearXNG image tag.
- `tests/test_searxng_collector.py`, `tests/test_query_batch.py`, `tests/test_aggregate_batch.py`.
- Production architecture, operations, test-strategy and data-dictionary documentation.

## Updated

- `.github/workflows/duckduckgo-search.yml` now displays as **SearXNG Search Collection Pipeline** and calls only the new SearXNG collector. Its path is retained so existing workflow links remain stable.
- `config/searxng-settings.yml` now uses the documented `keep_only` setting to load only DuckDuckGo.
- `scripts/archive_run.sh` retains its existing write-back ordering and retries; only its commit-message wording is generalized for batch archives.
- README, architecture, operations, limitations and changelog now describe the SearXNG production path.

## Scope exclusions

No result webpage crawling, PDF downloading, research-paper extraction, browser automation, LLM calls or agent orchestration has been introduced. Those are later extensions after search collection reliability has been validated.

## Validation boundary

`bash scripts/validate.sh` runs deterministic, mocked tests and workflow/config checks. It does not start Docker, contact DuckDuckGo or execute a GitHub Actions run. The production workflow must be manually run in the repository to validate the pinned container pull, deeper live pagination, matrix artifact transfer, and branch write-back.
