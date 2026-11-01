# Limitations and Reliability Notes

- DuckDuckGo is a public search service, not a guaranteed bulk-search API. Result availability, page depth, and response behavior vary by query, region, time, and request volume.
- The requested result count is a target, not a guarantee. Hybrid mode broadens coverage through query variants; it cannot manufacture results or guarantee 500 unique URLs.
- HTTP 202 observed from the HTML endpoint is classified as a challenge/throttling signal. Its exact provider-side cause cannot be determined from the response status alone.
- The collector waits and retries conservatively. It does not solve CAPTCHAs, rotate proxies, spoof identities, or bypass access restrictions.
- Automatic query variants are heuristic and can be less relevant for ambiguous phrases. Users can supply explicit related queries and inspect `source_query`.
- URL deduplication removes fragments and lowercases scheme/host; it does not attempt full semantic canonicalization across tracking parameters or mirrored content.
- Unit tests use fake DDGS clients. A live GitHub Actions execution is needed to validate current provider availability.
- GitHub Actions write-back requires `contents: write`; repository branch protection rules can still prevent bot commits.
- The complete GitHub platform logs remain in the Actions UI. Run artifacts include workflow/application logs captured by the project, not every internal GitHub runner service message.
