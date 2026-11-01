# Operations Runbook

## Manual execution

1. Open **Actions → SearXNG Search Collection Pipeline → Run workflow**.
2. Enter one query per line. Add `:: <limit>` to override the default unique-result target for that query.
3. Choose region, page cap, repeat count, concurrency and page delay.
4. Start the workflow manually. No push or schedule trigger is configured.
5. Review the `prepare` job first. If it fails, inspect input validation errors.
6. Review each `collect` matrix task. A failed task does not cancel its siblings (`fail-fast: false`).
7. Review `aggregate` for artifact completeness, batch summary and repository write-back.
8. Download the `searxng-batch-*` artifact for a complete copy; query/repeat artifacts are also retained individually.

## Recommended validation progression

| Stage | Settings | Purpose |
|---|---|---|
| Smoke | 1 query, 1 repeat, 5 pages | Validate startup, JSON response and basic pagination |
| Depth | 1 query, 1 repeat, 20 pages | Observe deeper page behaviour and stop conditions |
| Stress-depth | 1 query, 1 repeat, 50 pages | Estimate practical depth without unbounded requests |
| Repeatability | 1 query, 3 repeats, 20 pages | Compare URL-set stability across runs |
| Multi-query | 3–5 queries, 1 repeat, 20 pages, parallel=2 | Validate independent targets and matrix aggregation |
| Combined | 3 queries, 3 repeats, 20 pages, parallel=3 | Validate repeatability under controlled concurrency |

Do not start with maximum pages, maximum repeats and maximum parallelism together. Increase one dimension at a time so the source of any failure remains identifiable.

## Interpreting task statuses

- `SUCCESS`: requested unique URL target reached.
- `PARTIAL`: one or more results collected, target not reached (for example, an upstream error or page cap).
- `NO_RESULTS`: no valid DuckDuckGo-attributed result returned and no request error was recorded.
- `FAILED`: collection could not complete a successful page or the collector failed.
- Batch `SUCCESS`: every expected artifact arrived and every task status is `SUCCESS`.
- Batch `PARTIAL`: some artifacts arrived, or one/more tasks were partial/failed while artifacts were preserved.
- Batch `FAILED`: no task artifact was available.

## Diagnostics

Inspect, in order:

1. `task.json`: query index, query, repeat and requested target.
2. `workflow_stage_status.json`: dependency install, SearXNG startup and collector step outcomes.
3. `raw_results.json`: page-level HTTP status, attempts, raw result count, engine counts, unresponsive engines, timings and stop reason.
4. `searxng-container.log`: engine initialization and runtime warnings/errors.
5. `collector.log` and `run.log`: request sequence, retry decisions and workflow context.
6. `batch_summary.json`: missing tasks, per-query result counts and repeatability.
7. `repository_writeback.log`: Git fetch/rebase/commit/push diagnostics.

## Failure handling

- HTTP 202: record the interstitial/challenge signal and stop that query; do not retry automatically or attempt to bypass it.
- HTTP 403: may indicate disabled JSON output, access denial or other server policy. Check local SearXNG `search.formats` and container logs.
- HTTP 429: retry within the configured bounded budget; respect numeric `Retry-After`.
- HTTP 5xx/network: bounded retries; preserve prior pages if the page ultimately fails.
- Empty page: stop with `provider_returned_empty_page`.
- Repeated page: stop with `provider_repeated_page`.
- No new URLs for three consecutive pages: stop to avoid wasting requests.
- Missing artifacts: aggregation records a partial/failed batch; investigate matrix worker startup and upload steps.
- Write-back conflict: `archive_run.sh` fetches/rebases before staging and retries bounded pushes. Do not modify `run.log` during the Git synchronization step.

## Repeatability methodology

For meaningful comparisons, keep query text, region, page cap, page delay and image version fixed. Run 3–5 repeats at a controlled concurrency of 1–2 first. Compare exact set equality and mean pairwise Jaccard similarity. Search results are dynamic; low exact equality does not automatically imply a collector defect. Inspect the source pages and time gap before attributing drift to pagination.

## Local checks

```bash
python -m pip install -r requirements-dev.txt
bash scripts/validate.sh
```

The test suite uses fake HTTP responses and never sends live search requests. Live availability, upstream page depth, Docker image pulls and GitHub write permissions must be validated by a manual Actions run.
