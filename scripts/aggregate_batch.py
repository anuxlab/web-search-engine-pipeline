#!/usr/bin/env python3
"""Combine per-query/repeat artifacts into one auditable search batch."""
from __future__ import annotations
import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

AGGREGATE_FIELDS = [
    "query_index", "query", "repeat_index", "rank", "title", "url", "domain",
    "snippet", "source_page", "source_engine", "provider", "region", "collected_at",
]


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def _jaccard(left: set[str], right: set[str]) -> float | None:
    union = left | right
    return None if not union else len(left & right) / len(union)


def aggregate(download_dir: Path, output_dir: Path, manifest: dict[str, Any],
              run_id: str, attempt: str, commit_sha: str = "") -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    queries_root = output_dir / "queries"
    queries_root.mkdir(exist_ok=True)
    manifest_queries = manifest.get("queries", [])
    by_index = {int(q["query_index"]): q for q in manifest_queries}
    repeats: dict[int, dict[int, dict[str, Any]]] = {index: {} for index in by_index}
    aggregate_rows: list[dict[str, Any]] = []
    artifact_count = 0

    for artifact_dir in sorted(p for p in download_dir.iterdir() if p.is_dir()) if download_dir.exists() else []:
        task = _read_json(artifact_dir / "task.json", {})
        if not task:
            continue
        artifact_count += 1
        index = int(task["query_index"])
        repeat_index = int(task["repeat_index"])
        query_meta = by_index.get(index, task)
        query_dir = queries_root / f"{index:03d}-{query_meta['slug']}" / f"repeat-{repeat_index:02d}"
        query_dir.mkdir(parents=True, exist_ok=True)
        for source in artifact_dir.iterdir():
            if source.is_file():
                shutil.copy2(source, query_dir / source.name)
        raw = _read_json(artifact_dir / "raw_results.json", {})
        cleaned = _read_json(artifact_dir / "cleaned_results.json", [])
        url_set = {str(row.get("url")) for row in cleaned if row.get("url")}
        repeats.setdefault(index, {})[repeat_index] = {
            "query": str(task.get("query", query_meta.get("query", ""))),
            "repeat_index": repeat_index,
            "status": raw.get("status", "MISSING"),
            "unique_result_count": len(url_set),
            "requested_limit": int(task.get("result_limit", query_meta.get("result_limit", 0))),
            "pages_succeeded": int(raw.get("pages_succeeded", 0)),
            "pages_attempted": int(raw.get("pages_attempted", 0)),
            "total_request_seconds": float(raw.get("total_request_seconds", 0.0)),
            "stop_reason": raw.get("stop_reason", "artifact_missing_or_invalid"),
            "urls": url_set,
        }
        for row in cleaned:
            aggregate_rows.append({
                "query_index": index, "query": task.get("query", query_meta.get("query", "")),
                "repeat_index": repeat_index, **row,
            })

    repeatability: list[dict[str, Any]] = []
    query_summaries: list[dict[str, Any]] = []
    for index, query_meta in sorted(by_index.items()):
        runs = [repeats.get(index, {}).get(i) for i in range(1, int(manifest.get("repeat_count", 1)) + 1)]
        completed = [run for run in runs if run is not None]
        counts = [run["unique_result_count"] for run in completed]
        pairwise = [_jaccard(a["urls"], b["urls"]) for a, b in combinations(completed, 2)]
        valid_pairwise = [score for score in pairwise if score is not None]
        has_any_url = any(run["urls"] for run in completed)
        exact_repeatability = (len({tuple(sorted(run["urls"])) for run in completed}) == 1) if len(completed) >= 2 and has_any_url else None
        summary = {
            "query_index": index, "query": query_meta["query"],
            "requested_result_limit": query_meta["result_limit"],
            "repeat_count_requested": int(manifest.get("repeat_count", 1)),
            "repeat_count_completed": len(completed),
            "unique_results_per_repeat": counts,
            "minimum_unique_results": min(counts) if counts else 0,
            "maximum_unique_results": max(counts) if counts else 0,
            "mean_unique_results": round(sum(counts) / len(counts), 3) if counts else 0,
            "exact_result_set_repeatability": exact_repeatability,
            "mean_pairwise_jaccard": round(sum(valid_pairwise) / len(valid_pairwise), 4) if valid_pairwise else None,
            "all_repeats_reached_target": len(completed) == int(manifest.get("repeat_count", 1)) and bool(completed) and all(run["unique_result_count"] >= query_meta["result_limit"] for run in completed),
            "repeats": [{k: v for k, v in run.items() if k != "urls"} for run in completed],
        }
        query_summaries.append(summary)
        for run in completed:
            repeatability.append({
                "query_index": index, "query": query_meta["query"],
                "repeat_index": run["repeat_index"], "status": run["status"],
                "unique_result_count": run["unique_result_count"],
                "requested_limit": run["requested_limit"],
                "pages_attempted": run["pages_attempted"],
                "pages_succeeded": run["pages_succeeded"],
                "total_request_seconds": run["total_request_seconds"],
                "stop_reason": run["stop_reason"],
            })

    with (output_dir / "aggregate_results.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=AGGREGATE_FIELDS, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(aggregate_rows)
    repeat_fields = ["query_index", "query", "repeat_index", "status", "unique_result_count",
                     "requested_limit", "pages_attempted", "pages_succeeded", "total_request_seconds", "stop_reason"]
    with (output_dir / "repeatability.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=repeat_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(repeatability)

    expected_tasks = int(manifest.get("task_count", len(by_index) * int(manifest.get("repeat_count", 1))))
    all_artifacts_present = artifact_count == expected_tasks and all(
        q["repeat_count_completed"] == q["repeat_count_requested"] for q in query_summaries
    )
    all_tasks_successful = all(
        run.get("status") == "SUCCESS"
        for query_runs in repeats.values() for run in query_runs.values()
    )
    batch_status = "SUCCESS" if all_artifacts_present and all_tasks_successful else "PARTIAL" if artifact_count else "FAILED"
    metadata = {
        "workflow": "SearXNG Search Collection Pipeline", "provider": "SearXNG",
        "upstream_engine": "DuckDuckGo", "run_id": str(run_id), "run_attempt": str(attempt),
        "commit_sha": commit_sha, "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": manifest, "artifact_count": artifact_count, "expected_task_count": expected_tasks,
        "batch_status": batch_status,
    }
    (output_dir / "batch_metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    batch_summary = {
        "batch_status": batch_status, "query_count": len(by_index),
        "repeat_count": int(manifest.get("repeat_count", 1)), "expected_task_count": expected_tasks,
        "artifacts_received": artifact_count, "aggregate_unique_rows": len(aggregate_rows),
        "queries": query_summaries,
    }
    (output_dir / "batch_summary.json").write_text(json.dumps(batch_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["SEARXNG SEARCH BATCH SUMMARY", "=" * 30,
             f"Batch status: {batch_status}", f"Queries: {len(by_index)}",
             f"Repeats per query: {manifest.get('repeat_count', 1)}",
             f"Tasks/artifacts: {artifact_count}/{expected_tasks}",
             f"Aggregate result rows: {len(aggregate_rows)}", "", "Per-query repeatability:"]
    for item in query_summaries:
        lines.extend([
            f"{item['query_index']}. {item['query']}",
            f"   Target: {item['requested_result_limit']} | repeats: {item['repeat_count_completed']}/{item['repeat_count_requested']}",
            f"   Unique counts: {item['unique_results_per_repeat']} | mean: {item['mean_unique_results']}",
            f"   Exact set repeatability: {item['exact_result_set_repeatability']} | mean pairwise Jaccard: {item['mean_pairwise_jaccard']}",
            f"   All repeats reached target: {item['all_repeats_reached_target']}",
        ])
    (output_dir / "batch_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output_dir / "README.md").write_text(
        "# SearXNG search batch archive\n\n"
        "Each query is stored independently under `queries/<query-id>/repeat-NN/`. "
        "`aggregate_results.csv` combines cleaned records; `repeatability.csv` and "
        "`batch_summary.json` report repeat-run stability. Each result retains the "
        "DuckDuckGo source-engine attribution recorded by SearXNG.\n", encoding="utf-8")
    return batch_summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest-json", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--commit-sha", default="")
    args = parser.parse_args()
    manifest = json.loads(args.manifest_json)
    summary = aggregate(args.download_dir, args.output_dir, manifest, args.run_id, args.attempt, args.commit_sha)
    print(json.dumps(summary, indent=2))
    return 0 if summary["batch_status"] != "FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
