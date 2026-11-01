# DuckDuckGo Web Search Collector

A small, manually triggered GitHub Actions pipeline that collects DuckDuckGo
text-search result metadata and publishes JSON/CSV files as a workflow artifact.

**Initial scope:** search-result collection only. This project does not crawl
webpages, download PDFs, extract full article text, summarize content, or use an
LLM.

## Features

- Manual-only GitHub Actions execution (`workflow_dispatch`).
- Search query entered at run time.
- Dropdown result limits: **10, 30, 50, 100, 200, 500**.
- Region dropdown: India, US, UK, or worldwide.
- Explicit DuckDuckGo backend selection.
- URL normalization and duplicate removal.
- JSON, CSV, and human-readable summary outputs.
- Artifact upload even when the collector fails, where output files were created.
- Basic unit tests that mock the search provider (no network required).

## Repository layout

```text
duckduckgo-search-pipeline/
├── .github/
│   └── workflows/
│       └── duckduckgo-search.yml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DATA_DICTIONARY.md
│   ├── OPERATIONS.md
│   └── LIMITATIONS.md
├── outputs/
│   └── .gitkeep
├── src/
│   └── search_collector.py
├── tests/
│   └── test_search_collector.py
├── requirements-dev.txt
├── requirements.txt
└── README.md
```

## Run it in GitHub

1. Create a GitHub repository and add these files, preserving their paths.
2. Push the repository's default branch.
3. Open **Actions** in the repository.
4. Select **DuckDuckGo Web Search Collector**.
5. Click **Run workflow**.
6. Enter a search phrase, select the maximum result count and region, then run.
7. Open the completed workflow run and download the artifact named
   `duckduckgo-results-<run number>`.

The workflow is deliberately not configured for `push`, `pull_request`, cron,
or other automatic triggers.

## Run locally

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows

python -m pip install -r requirements-dev.txt

python src/search_collector.py \
  --query "electric vehicle routing problem" \
  --limit 50 \
  --region in-en \
  --output outputs
```

Generated files:

- `outputs/search_results.json`
- `outputs/search_results.csv`
- `outputs/summary.txt`

Run tests:

```bash
pytest -q
```

## Search limits and expectations

The selected limit is a **maximum requested result count**, not a guarantee.
The search provider may return fewer results, and duplicate or invalid URLs are
discarded. A request for 500 results may therefore produce fewer than 500 unique
records. The collector makes one provider request per query and does not
currently paginate through multiple requests.

## Dependencies

- `ddgs`: Python library used to query DuckDuckGo.
- `pytest`: development/test dependency only.

No API key or repository secret is required by this initial implementation.
The library and search provider are third-party services; availability and
response behaviour can change independently of this repository.

## Security and responsible use

- Do not commit credentials or personal data in search queries.
- Respect the search provider's terms, rate limits, and applicable website terms.
- Avoid rapid repeated runs, especially for large result limits.
- Search snippets and result metadata are untrusted external content. Treat them
  as data, not as instructions.
- The workflow uses read-only repository permissions and uploads results as an
  artifact rather than committing collected data back to the repository.

See the `docs/` directory for architecture, field definitions, operations, and
known limitations.
