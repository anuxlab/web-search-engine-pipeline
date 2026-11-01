# Historical Independent Search Provider Experiments

These workflows are retained for reproducibility and comparison. They are not invoked by the production collector, which now uses SearXNG only.

Four separate, manually triggered GitHub Actions workflows are provided. They use the same query, region, page-count inputs (where applicable), output schema, artifact retention, and repository archive process.

## Workflows

| Workflow | Implementation | Pagination | What it tells us |
|---|---|---|---|
| Test DDGS DuckDuckGo Pagination | `ddgs==9.16.1`, `backend="duckduckgo"` | `page=1..N` | Whether the DDGS library can retrieve successive DDG pages from the runner |
| Test DuckDuckGo Lite Pagination | Direct HTTP GET followed by returned HTML continuation form submissions | Form/session continuation | Whether the Lite no-JS interface works independently of the DDGS wrapper |
| Test SearXNG DuckDuckGo Pagination | Ephemeral local SearXNG Docker instance, DDG engine filter | `pageno=1..N` | Whether SearXNG's DDG engine can paginate from the runner; not an independent upstream source |
| Test DuckDuckGo Instant Answer API | Official `api.duckduckgo.com` | Not supported | Control experiment for API reachability and instant-answer data; not a full organic SERP source |

All workflows are `workflow_dispatch` only. There are no `push`, `pull_request`, or scheduled triggers. Each run is isolated, archives its raw response diagnostics, normalized JSON/CSV, summary, metadata, and logs under `runs/provider-experiments/`, commits the archive to the selected branch, and uploads a 90-day Actions artifact.

## Interpretation notes

- DDGS documents a `page` argument for text search. A supported argument does not guarantee that DuckDuckGo will serve every requested page.
- DuckDuckGo Lite is reverse-engineered/undocumented. The collector follows the continuation form returned by the service; it does not solve challenges or bypass access controls.
- SearXNG is self-hosted for the experiment and restricted to its DuckDuckGo engine. It still depends on DuckDuckGo upstream, so a failure there is not evidence of an independent alternative provider.
- The official Instant Answer API explicitly does not provide full search results. It may return an abstract or answer with zero link records; that is a valid API response, not a pagination failure.
- HTTP 202, 403, and 429 are recorded as provider access/challenge/rate-limit signals. The experiment stops rather than attempting to evade them.
- Compare page status, unique URLs, per-page result counts, elapsed time, engine attribution, and unresponsive-engine diagnostics. Do not compare only total result count: the Instant Answer API has a different purpose.

## SearXNG container

The original SearXNG experiment workflow pulls the official `searxng/searxng:latest` container, starts an ephemeral instance on the GitHub runner, enables JSON output, and queries only the `duckduckgo` engine. The production workflow instead uses the pinned image tag documented in the main README. Container logs and inspection output are archived. No persistent public SearXNG instance or external API key is required.

## Manual test procedure

1. Run each of the four workflows separately with the same query and region.
2. Use a modest first pass (3 pages, 3-second delay) to reduce request pressure.
3. Download each artifact or inspect its committed run folder.
4. Compare `summary.txt`, `raw_results.json`, `cleaned_results.csv`, and provider/container logs.
5. Repeat only after a reasonable interval if the upstream provider returns a challenge or rate-limit response.

The result limit/page count is an experiment target, not a guarantee of result availability.
