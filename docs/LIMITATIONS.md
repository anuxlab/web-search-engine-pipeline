# Scope, limitations, and next phases

## Current scope

This version collects search-result metadata from one DuckDuckGo text search
request. It writes JSON and CSV files and uploads them as a GitHub Actions
artifact.

## Known limitations

1. **No guarantee of the requested count.** `max_results` is a request ceiling.
   Provider behaviour, availability, and duplicate filtering can reduce the
   actual number returned.
2. **No pagination strategy.** The collector makes one DDGS text-search call.
   It does not loop over pages or issue follow-up searches to fill a shortfall.
3. **No webpage extraction.** It does not fetch result URLs or extract full text.
4. **No PDF discovery or download.** Search results may point to PDFs, but those
   files are not downloaded or parsed.
5. **No persistent database.** Results live in the workflow artifact for the
   configured retention period (30 days).
6. **No guarantee of stable search ranking.** Search results can vary over time,
   by region, and with provider-side changes.
7. **Unofficial integration.** The Python client is a third-party library, not a
   contractual search API. Its interface and the provider's availability can
   change.

## Suggested roadmap

### Phase 2 — Multiple queries
Accept a list of search queries and collect a separate result set for each.
Include query-level counts and a combined export.

### Phase 3 — Search result enrichment
Normalize canonical URLs, classify file types, detect likely academic sources,
and add domain-level metadata without downloading full pages.

### Phase 4 — Controlled webpage extraction
Fetch permitted pages with timeouts, size limits, content-type checks, robots
and site-policy awareness, and per-domain rate limiting.

### Phase 5 — Research corpus
Extract article text and PDF text, retain source URLs and timestamps, and store
documents with provenance.

### Phase 6 — Analysis and retrieval
Add deduplication beyond exact URLs, relevance scoring, embeddings, and
retrieval/LLM summarization with source citations.

## Acceptance criteria for Phase 1

- Workflow appears under the Actions tab after being pushed to the default branch.
- Workflow can only be started manually.
- Query is required.
- Result dropdown contains exactly 10, 30, 50, 100, 200, and 500.
- Search call explicitly selects the DuckDuckGo backend.
- Duplicate URLs are removed.
- JSON, CSV, and summary outputs are produced.
- Outputs are uploaded as a downloadable artifact.
- Unit tests pass without making live network requests.
