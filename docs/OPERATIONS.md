# Operations guide

## Run a collection

1. Open the repository's **Actions** tab.
2. Select **DuckDuckGo Web Search Collector**.
3. Choose **Run workflow**.
4. Enter a focused search query.
5. Select a result limit.
6. Select a region (`in-en` is the default).
7. Start the workflow and inspect the job log.
8. Download the result artifact after the run completes.

## Choosing a result limit

| Limit | Suggested use |
|---:|---|
| 10 | Quick sanity check |
| 30 | Focused exploratory search |
| 50 | Normal initial collection |
| 100 | Broader discovery |
| 200 | Large discovery batch |
| 500 | Maximum configured batch; provider may return fewer |

Start with 10 or 30 while validating a new query. Use 200 or 500 only when
there is a clear need for a larger batch.

## Local troubleshooting

### `ModuleNotFoundError: No module named 'ddgs'`

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

### Search returns fewer records than requested

This can be normal. The provider may return fewer results; duplicate or
non-HTTP(S) URLs are discarded. The workflow reports requested and actual
counts separately.

### Provider request fails

Inspect the Actions log. Retry later rather than rapidly rerunning the workflow.
A transient provider issue, rate limit, network failure, or upstream library
change may be responsible.

### Artifact is missing

Check that the job reached the upload step and inspect the artifact step log.
The workflow uses `if: always()` so output files can be uploaded after a failed
collector step, but an artifact cannot be created if the runner never reaches
the upload step or no files exist.

## Changing the workflow

Keep `workflow_dispatch` as the only trigger if manual-only execution is
required. If adding inputs, validate them in Python as well as defining them in
the workflow UI; workflow inputs are not a substitute for application-level
validation.
