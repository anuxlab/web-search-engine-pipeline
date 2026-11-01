# Validation Report — SearXNG Search Collection Pipeline 3.0.0

## Automated validation

Command:

```bash
bash scripts/validate.sh
```

Result from the packaging run:

- **50 tests passed**.
- Python source and test modules compiled with `py_compile`.
- All workflow YAML files parsed successfully.
- The production workflow and all independent experiment workflows were verified as `workflow_dispatch` only; the reusable provider experiment is `workflow_call` only.
- Dynamic matrix wiring, `fail-fast: false`, DuckDuckGo-only SearXNG settings, and pinned image tag were validated.
- All workflow shell `run:` blocks passed `bash -n` after GitHub expression placeholders were substituted.
- Embedded Python heredoc blocks passed Python compilation.
- Existing Git write-back ordering regression test passed.

## Coverage included

- Query parsing, per-query result limits, duplicate detection and query/repeat matrix construction.
- SearXNG request parameters, language mapping, JSON schema validation and HTTP status classification.
- Bounded retry behaviour for HTTP 429, HTTP 5xx and network exceptions.
- Pagination, short-page continuation, target completion, max-page cap, repeated pages and duplicate-only stopping.
- DuckDuckGo result provenance filtering, URL normalization and cross-page deduplication.
- Partial-result preservation after later-page failures.
- JSON/CSV/summary persistence and CLI output directory creation.
- Batch artifact aggregation, missing/partial task handling, exact set repeatability and pairwise Jaccard metrics.
- Manual-only workflow triggers, matrix and SearXNG configuration contracts.

## Live validation not performed in this environment

The packaging environment does not have Docker installed and cannot perform external network requests. Therefore this validation does **not** establish that:

- the pinned SearXNG image can currently be pulled from Docker Hub or GHCR;
- DuckDuckGo will serve deeper pages today or over a long observation window;
- repeatability metrics from live independent runs meet any chosen threshold;
- GitHub Actions artifact transfer and repository write-back succeed on the user's repository.

Those checks are intentionally delegated to the manually triggered GitHub Actions workflow. Until staged live smoke, depth, repeatability and multi-query runs complete, treat this package as a tested production-oriented release candidate rather than a live-verified reliability guarantee.
