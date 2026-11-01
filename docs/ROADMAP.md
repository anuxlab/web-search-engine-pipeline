# Roadmap: Search Collection to Web Research Infrastructure

This roadmap is intentionally staged. Do not add crawler, LLM or research-paper extraction work until the search collection layer passes its live depth and repeatability gates.

## Phase 0 — Search collection reliability (current)

- SearXNG-only production provider, restricted to DuckDuckGo.
- Manual multi-query workflow with per-query result targets.
- Bounded pagination, retries, duplicate detection and provenance checks.
- Per-query artifacts, aggregate batch archive and repeatability metrics.
- Small mocked tests for every pipeline stage.

**Exit gate:** staged smoke/depth/repeatability/multi-query runs complete without missing artifacts; all failures are explicitly classified; repository write-back is repeatable; the observed page depth and result-set stability are documented over multiple dates.

## Phase 1 — Search service hardening

- Decide whether to keep ephemeral per-run SearXNG or operate a long-lived private SearXNG service.
- If long-lived: configure reverse proxy, authentication/network policy, health/readiness checks, persistent cache, rate limiting and operational monitoring.
- Pin and upgrade the SearXNG image through explicit regression runs.
- Add query scheduling, budget controls and per-domain/result-domain statistics.
- Consider a queue for large query batches and resumable page state.

## Phase 2 — Policy-aware webpage crawler (future, not implemented)

Consume normalized result URLs from the search archive through a separate crawl queue. The crawler should have:

- URL canonicalization and crawl deduplication;
- robots.txt and site terms/policy checks;
- per-host concurrency and politeness delays;
- bounded retries, timeouts, redirects and response-size limits;
- content-type validation and HTML/PDF-specific fetch policies;
- content hashes, fetch timestamps, ETag/Last-Modified handling and immutable raw response storage;
- explicit crawl status and provenance back to the originating query/page/result.

The crawler must not be coupled to the SearXNG request loop. Search collection and page fetching have different rate limits, failure modes and compliance requirements.

## Phase 3 — Content extraction and indexing (future)

- HTML extraction with boilerplate removal and metadata preservation.
- PDF text extraction, page-level references and OCR only where required.
- Document quality checks, language detection, duplicate/similarity detection and structured metadata.
- Searchable document store or vector index only after source retention and licensing rules are clear.

## Phase 4 — AI-agent and automation integration (future)

Expose the stable search collection and crawler interfaces as explicit tools (for example, an MCP-compatible search tool and a separate fetch/extract tool). Agents should receive structured result objects with source query, engine, URL, fetch time and errors. Tool budgets, domain allow/deny policies, provenance and audit logs should be enforced outside the LLM.

## Architectural principle

Keep **search**, **fetch/crawl**, **extract**, **index**, and **reason/agent** as independent services or modules. A search provider change should not require rewriting the crawler, and a new extraction model should not alter the provenance of the original search result.
