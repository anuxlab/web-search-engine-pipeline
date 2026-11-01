# Operations guide

## Run manually

1. Open **Actions**.
2. Select **DuckDuckGo Web Search Collector**.
3. Click **Run workflow**.
4. Enter a query and choose the target count.
5. Choose the search region. The provider batch size is fixed internally at 10 results per page.
6. Start the workflow.
7. Inspect page-by-page logs and download the run artifact.
8. Browse the committed `runs/YYYY/MM/DD/...` directory.

## Provider page size

DuckDuckGo requests are deliberately limited to 10 results per page. The
collector automatically requests successive pages to build the requested unique
result set. There is no page-size dropdown because requesting 20–50 results in a
single call did not make DuckDuckGo return that many records in the observed run.

## Pagination and stopping

The collector stops when the unique target is reached, an empty page is
returned, the provider repeats a page, two pages in a row add no new valid URLs,
a later page exhausts retries, or the safety cap is reached. Check `summary.txt`
for the stop reason and `raw_results.json` for page-level counts.

## Troubleshooting

### Fewer results than requested

Check the number of successful pages and `stop_reason` in `raw_results.json`.
The provider may have exhausted its available results or repeated a page.
Try a different query formulation or region; do not assume that increasing
provider page size alone will overcome provider-side limits.

### Later page fails

Previously collected pages are retained. The run is marked partial rather than
discarding valid results. Inspect `page_errors` in `raw_results.json` and the
page-level logs.

### Provider throttles requests

Avoid rapid reruns and allow the configured inter-page delay.
The collector already retries transient failures with exponential backoff.

### Push rejected

Check repository workflow permissions and branch protection. The job needs
`contents: write`.
