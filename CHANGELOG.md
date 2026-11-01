# Changelog

## 2026-11-01 — Pagination correction

- Fixed DuckDuckGo requests to use 10 results per page, matching the provider
  response ceiling observed in the latest Actions run.
- Removed the misleading configurable page-size dropdown from workflow inputs.
- Removed the short-page-as-exhaustion stop condition. A short response is now
  logged and the collector continues to the next page.
- Retained empty-page, repeated-page, duplicate-only, requested-target, retry,
  and safety-cap stop conditions.
- Added regression tests for short-page continuation and fixed page size.
