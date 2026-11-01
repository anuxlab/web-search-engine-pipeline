# Operations Guide

## Recommended first run

1. Trigger the workflow manually.
2. Use a representative query and a target of 30 or 50.
3. Select `hybrid`, region `in-en`, and `max_queries=8`.
4. Review `summary.txt`, `raw_results.json`, `cleaned_results.csv`, and `repository_writeback.log`.
5. If relevance is poor, add more specific related queries in the optional multiline input. If results are too few, increase the query count or target only after inspecting the provider's stop reason.

## Interpreting HTTP 202

The previous run showed `html.duckduckgo.com/html/ 202` on page 2. This is recorded as `http_202_challenge_or_throttle`, not as an empty page. The collector waits before one retry and then continues with other hybrid query variants. It does not try to bypass the provider response.

## Interpreting collection status

- `SUCCESS`: the selected unique-result target was reached.
- `PARTIAL`: some valid unique results were collected, but fewer than requested.
- `NO_RESULTS`: no valid results were produced.
- `FAILED`: collection could not run or all initial requests failed.

A partial result set can still be a successful workflow step; the summary makes the shortfall explicit. A provider limit is not automatically a code failure.

## Repository write-back troubleshooting

The write-back script:

- fetches and rebases before staging the run folder;
- commits the run archive;
- retries a rejected push by fetching/rebasing and pushing again;
- commits a separate write-back transcript;
- keeps Git command output outside `run.log` during synchronization.

If write-back fails, inspect the workflow step and the uploaded `repository_writeback.log`. Confirm the workflow token has `contents: write` and the branch is not protected against GitHub Actions pushes.

## Logs and artifacts

The Actions artifact is uploaded under `duckduckgo-run-<run-number>-attempt-<attempt>` and retained for 90 days. The run folder is also committed under `runs/`. GitHub platform-level setup/checkout/upload logs remain visible in the Actions UI and are not all embedded in the run artifact.

## Local regression checks

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m py_compile src/search_collector.py tests/test_search_collector.py
bash -n scripts/archive_run.sh
```

Tests use mocked DDGS responses; they do not guarantee DuckDuckGo's live availability or result volume.
