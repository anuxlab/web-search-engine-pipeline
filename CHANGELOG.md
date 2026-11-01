# Changelog

## 2.0.0 — Hybrid collection and write-back repair

- Added a selectable hybrid collector that runs domain-aware query variants before primary-query pagination fallback.
- Retained the original single-query paginated collector as a selectable strategy.
- Added explicit capture/classification of DDGS HTTP response status logs, including HTTP 202 challenge/throttling signals.
- Added conservative cooldown handling and continued hybrid collection after an individual variant fails.
- Preserved page-level raw provider responses and source-query/source-page provenance in flattened records.
- Added source query to cleaned JSON and CSV exports.
- Fixed premature stop behavior for short pages.
- Replaced the faulty `git commit → git pull --rebase` flow with `git fetch/rebase → stage → commit → push` and bounded push retries.
- Separated repository write-back logs from `run.log` to prevent unstaged-file rebase failures.
- Kept the workflow manual-only (`workflow_dispatch`) and added strategy/additional-query inputs.
- Added regression tests for HTTP 202, hybrid fallback, query diversification, and Git write-back ordering.

## 1.1.0

- Added conservative DDGS page-by-page collection, raw-page archives, URL normalization, and deduplication.
- Added manual-only workflow, run artifacts, and repository write-back.
