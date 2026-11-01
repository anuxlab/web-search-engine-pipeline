"""Validation and expansion of a manually supplied multi-query search batch."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Iterable

MAX_QUERIES = 20
MAX_QUERY_LENGTH = 512
MAX_RESULT_LIMIT = 1000
ALLOWED_DEFAULT_LIMITS = {10, 25, 50, 100, 200, 500, 1000}


@dataclass(frozen=True)
class QuerySpec:
    query_index: int
    query: str
    result_limit: int
    slug: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _slug(value: str, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug[:max_length].strip("-") or "query"


def parse_query_lines(
    value: str,
    default_limit: int = 50,
    max_queries: int = MAX_QUERIES,
) -> list[QuerySpec]:
    """Parse one query per line; an optional TAB + integer overrides its limit.

    Example::

        machine learning papers :: 100
        SearXNG pagination :: 50
        agentic search systems

    A TAB may be used instead of ``::``. The last query inherits ``default_limit``. Blank lines and lines beginning
    with ``#`` are ignored. Duplicate queries are rejected rather than silently
    merging two independently requested jobs.
    """
    if default_limit not in ALLOWED_DEFAULT_LIMITS:
        raise ValueError(f"default_limit must be one of {sorted(ALLOWED_DEFAULT_LIMITS)}")
    if not 1 <= max_queries <= MAX_QUERIES:
        raise ValueError(f"max_queries must be between 1 and {MAX_QUERIES}")

    specs: list[QuerySpec] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate((value or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line or "::" in line:
            if "\t" in line:
                query, raw_limit = line.rsplit("\t", 1)
            else:
                query, raw_limit = line.rsplit("::", 1)
            query = query.strip()
            raw_limit = raw_limit.strip()
            if not raw_limit.isdigit():
                raise ValueError(f"line {line_number}: result limit after TAB must be an integer")
            limit = int(raw_limit)
        else:
            query, limit = line, default_limit
        query = " ".join(query.split())
        if not query:
            raise ValueError(f"line {line_number}: query must not be empty")
        if len(query) > MAX_QUERY_LENGTH:
            raise ValueError(f"line {line_number}: query exceeds {MAX_QUERY_LENGTH} characters")
        if not 1 <= limit <= MAX_RESULT_LIMIT:
            raise ValueError(f"line {line_number}: result limit must be between 1 and {MAX_RESULT_LIMIT}")
        key = query.casefold()
        if key in seen:
            raise ValueError(f"line {line_number}: duplicate query: {query!r}")
        seen.add(key)
        index = len(specs) + 1
        specs.append(QuerySpec(index, query, limit, _slug(query)))
        if len(specs) > max_queries:
            raise ValueError(f"batch contains more than {max_queries} queries")

    if not specs:
        raise ValueError("provide at least one search query")
    return specs


def build_matrix(specs: Iterable[QuerySpec], repeat_count: int = 1) -> list[dict[str, object]]:
    if repeat_count not in {1, 2, 3, 5}:
        raise ValueError("repeat_count must be one of 1, 2, 3, or 5")
    tasks: list[dict[str, object]] = []
    for spec in specs:
        for repeat_index in range(1, repeat_count + 1):
            tasks.append({**spec.to_dict(), "repeat_index": repeat_index})
    return tasks
