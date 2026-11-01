# Operations guide

## Run manually

1. Open **Actions**.
2. Select **DuckDuckGo Web Search Collector**.
3. Click **Run workflow**.
4. Enter a query and choose the target count.
5. Choose region and page size.
6. Start the workflow.
7. Inspect page-by-page logs and download the run artifact.
8. Browse the committed `runs/YYYY/MM/DD/...` directory.

## Page size guidance

| Page size | Guidance |
|---:|---|
| 10 | Conservative; more requests |
| 20 | Conservative |
| 25 | Recommended default |
| 30 | Moderate |
| 50 | Larger requests; may be less gentle |

A smaller page size does not guarantee more total results. It only changes how
the collector batches its pagination requests.

## Pagination and stopping

The collector stops when the unique target is reached, an empty/short page is
returned, the provider repeats a page, two pages in a row add no new valid URLs,
a later page exhausts retries, or the safety cap is reached. Check `summary.txt`
for the stop reason and `raw_results.json` for page-level counts.

## Troubleshooting

### Fewer results than requested

Check the number of successful pages and `stop_reason` in `raw_results.json`.
The provider may have exhausted its available results or repeated a page.
Try a different query formulation or region; do not assume that increasing
page size alone will overcome provider-side limits.

### Later page fails

Previously collected pages are retained. The run is marked partial rather than
discarding valid results. Inspect `page_errors` in `raw_results.json` and the
page-level logs.

### Provider throttles requests

Avoid rapid reruns. Use a smaller page size and allow the configured delay.
The collector already retries transient failures with exponential backoff.

### Push rejected

Check repository workflow permissions and branch protection. The job needs
`contents: write`.
