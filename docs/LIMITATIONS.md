# Limitations and Risks

## Upstream search constraints

- SearXNG is an aggregator and adapter layer; it does not own or guarantee DuckDuckGo's organic index or result pages.
- The five-page experiment on 2026-11-01 demonstrated that one tested SearXNG/DuckDuckGo setup returned five HTTP 200 pages and 67 unique URLs. It is feasibility evidence, not a reliability SLA.
- The production workflow is configured to use DuckDuckGo only. It does not fall back to other search engines.
- DuckDuckGo can change response formats, ranking, throttling, or access behaviour without notice.
- HTTP 202 is recorded as an interstitial/challenge signal. It does not prove that a CAPTCHA was presented or identify the exact cause.
- HTTP 403 can indicate disabled JSON output on a SearXNG instance or another access/policy response.
- A page number is a request parameter, not a guarantee that a distinct page exists.

## Pagination and result-count limits

- The observed SearXNG experiment returned 10 records on page 1 and 15 on pages 2–5. The API's page yield is not a fixed, user-controlled contract.
- A requested result target is a target, not a guarantee. The workflow caps pages at 100 to bound requests and runtime.
- Duplicate URLs across pages are expected; normalized URL deduplication may make the number of unique records lower than raw records.
- Search rankings and results can change between repeated runs. Repeatability metrics are descriptive, not proof of a deterministic index.
- Exact result-set equality is a strict measure; pairwise Jaccard similarity is more informative for dynamic search results but is not a relevance metric.

## SearXNG deployment

- Each matrix worker starts a short-lived local SearXNG Docker container. This validates the collector in a clean runner environment but does not validate a long-lived production SearXNG service, reverse proxy, persistent cache, public-instance limiter or high availability.
- The pinned image tag reflects the version observed in the experiment. It must be deliberately upgraded and regression-tested rather than changed to `latest`.
- Docker Hub rate limits may affect image pulls; the workflow attempts the official GHCR mirror as a fallback.
- Engine registration warnings for unrelated default engines were observed in the initial experiment. The production settings now use `keep_only` to restrict loaded engines to DuckDuckGo.

## GitHub Actions constraints

- Each query/repeat matrix task starts a separate container, so concurrency increases CPU, memory, outbound requests and Docker image-pull volume.
- The workflow caps queries at 20, repeats at 5 and parallel workers at 4. Large combinations can still consume substantial runner time.
- The aggregation job can only report on artifacts that were uploaded. A hard runner cancellation or platform outage can leave missing artifacts.
- Repository write-back requires `contents: write` and compatible repository Actions permissions.

## Scope deliberately excluded

- No webpage crawling, page HTML fetching, robots-policy processing, PDF download, research-paper extraction, browser automation, LLM inference, embedding, ranking or summarization is implemented.
- Search result URLs are data only. A later crawler must have its own policy checks, per-domain rate limiting, content-type handling, retry policy, storage, deduplication and audit logs.
- No claim is made that search results are complete, unbiased, authoritative or safe to consume without validation.
