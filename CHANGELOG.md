# Changelog

## 3.0.0 — SearXNG-only production collection layer

- Added a dedicated SearXNG collector; the active production workflow no longer calls DDGS.
- Configured SearXNG with `use_default_settings.engines.keep_only: [duckduckgo]` and JSON output.
- Pinned the SearXNG image to the version observed in the successful provider experiment (`2026.11.1-9ded3bec1`).
- Added bounded retries for network, HTTP 429 and HTTP 5xx errors; HTTP 202/403 are recorded without challenge bypass.
- Added page-level timings, retry counts, engine provenance, unresponsive-engine diagnostics, repeated-page detection and duplicate-only stopping.
- Added multiline query batches with per-query result limits and a dynamic query × repeat GitHub Actions matrix.
- Added configurable page depth, repeat count and matrix concurrency; workflow remains `workflow_dispatch` only.
- Added per-task artifacts, batch aggregation, exact-set repeatability and pairwise Jaccard metrics.
- Matrix workers upload artifacts only; one aggregation job performs a single repository write-back.
- Preserved the previous DDGS collector and provider experiments for historical comparison and regression testing.
- Added tests for query parsing, matrix expansion, SearXNG HTTP behaviour, retries, pagination, provenance, aggregation and repeatability.
- Explicitly kept crawling, LLMs and research-paper extraction out of scope.

## 2.1.0 — Independent provider experiments

- Added independent manually triggered workflows for DDGS, DuckDuckGo Lite, SearXNG DuckDuckGo and the Instant Answer API.
- Added provider-specific raw diagnostics and normalized JSON/CSV artifacts.

## 2.0.0 — Hybrid collection and write-back repair

- Added a selectable hybrid collector that runs domain-aware query variants before primary-query pagination fallback.
- Retained the original single-query paginated collector as a selectable strategy.
- Added explicit capture/classification of DDGS HTTP response status logs, including HTTP 202 challenge/throttling signals.
- Added conservative cooldown handling and continued hybrid collection after an individual variant fails.
- Preserved page-level raw provider responses and source-query/source-page provenance in flattened records.
- Fixed premature stop behavior for short pages.
- Replaced the faulty `git commit → git pull --rebase` flow with `git fetch/rebase → stage → commit → push` and bounded push retries.
- Separated repository write-back logs from `run.log` to prevent unstaged-file rebase failures.
- Kept the workflow manual-only (`workflow_dispatch`).

## 1.1.0

- Added conservative DDGS page-by-page collection, raw-page archives, URL normalization, and deduplication.
- Added manual-only workflow, run artifacts, and repository write-back.
