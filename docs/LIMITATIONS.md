# Limitations and roadmap

## Current phase

- One manual query per workflow run.
- Sequential page-by-page DuckDuckGo requests using DDGS `page`.
- Fixed 10-result provider batches and conservative inter-page delay.
- Short pages do not terminate pagination; the collector continues until an empty page or another explicit stop condition.
- Exponential retries for transient page failures.
- Raw page response archive plus flattened raw records.
- Cross-page URL normalization and deduplication.
- Partial results retained if a later page fails.
- Per-run logs, metadata, repository commit and Actions artifact.

## Provider constraints

The DDGS library documents a `page` parameter and recommends iterating over
pages. However, DuckDuckGo does not provide this unofficial integration with a
guaranteed result quota or contractual pagination depth. The provider may
return fewer results, repeat pages, throttle requests, block traffic, or change
its response behaviour. Therefore 500 is a target ceiling, not a promise.

Short pages do not terminate pagination; the collector continues until an empty page, repeated page, duplicate-only threshold, target, error, or safety cap.

The collector deliberately does not switch to Google, Bing, or other providers:
the selected backend remains `duckduckgo`. If DuckDuckGo stops returning new
pages, the run records the stop reason and preserves all results collected so
far rather than silently changing search engines.

## Next phases

- Query expansion and multiple related search phrases.
- Domain and file-type classification.
- Controlled webpage extraction with timeouts, size limits, and site-policy
  awareness.
- PDF/document discovery and extraction.
- Search quality and recall evaluation across repeated runs.
