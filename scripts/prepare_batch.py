#!/usr/bin/env python3
"""Validate workflow inputs and emit a GitHub Actions dynamic matrix."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.query_batch import build_matrix, parse_query_lines  # noqa: E402


def main() -> int:
    queries = os.environ.get("SEARCH_QUERIES", "")
    legacy = os.environ.get("SEARCH_QUERY", "").strip()
    if queries.strip() and legacy:
        raise ValueError("Use either 'queries' or legacy 'search_query', not both")
    source = queries if queries.strip() else legacy
    default_limit = int(os.environ.get("DEFAULT_RESULT_LIMIT", "50"))
    repeat_count = int(os.environ.get("REPEAT_COUNT", "1"))
    max_queries = int(os.environ.get("MAX_QUERIES", "20"))
    specs = parse_query_lines(source, default_limit, max_queries)
    tasks = build_matrix(specs, repeat_count)
    region = os.environ.get("SEARCH_REGION", "in-en")
    max_pages = int(os.environ.get("MAX_PAGES", "20"))
    page_delay = float(os.environ.get("PAGE_DELAY", "2"))
    max_parallel = int(os.environ.get("MAX_PARALLEL", "3"))
    if region not in {"in-en", "us-en", "uk-en", "wt-wt"}:
        raise ValueError("unsupported region")
    if not 1 <= max_pages <= 100:
        raise ValueError("max_pages must be between 1 and 100")
    if not 0 <= page_delay <= 30:
        raise ValueError("page_delay must be between 0 and 30 seconds")
    if max_parallel not in {1, 2, 3, 4}:
        raise ValueError("max_parallel must be 1, 2, 3, or 4")
    manifest = {
        "queries": [spec.to_dict() for spec in specs],
        "repeat_count": repeat_count,
        "task_count": len(tasks),
        "region": region,
        "max_pages": max_pages,
        "page_delay": page_delay,
        "max_parallel": max_parallel,
    }
    matrix_json = json.dumps(tasks, ensure_ascii=False, separators=(",", ":"))
    manifest_json = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"matrix={matrix_json}\n")
            handle.write(f"manifest={manifest_json}\n")
    print(json.dumps({"matrix": tasks, "manifest": manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"INPUT VALIDATION ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
