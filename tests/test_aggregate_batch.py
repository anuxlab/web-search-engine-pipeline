import csv
import json
from pathlib import Path

from scripts.aggregate_batch import aggregate


def write_artifact(root: Path, name: str, task: dict, urls: list[str]):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "task.json").write_text(json.dumps(task))
    (folder / "raw_results.json").write_text(json.dumps({
        "status": "SUCCESS", "pages_succeeded": 4, "pages_attempted": 4,
        "total_request_seconds": 3.2, "stop_reason": "requested_unique_result_limit_reached"}))
    rows = [{"rank": i + 1, "title": f"Title {i}", "url": url, "domain": "example.com",
             "snippet": "snippet", "source_page": 1, "source_engine": "duckduckgo",
             "provider": "searxng", "region": "in-en", "collected_at": "2026-11-02T00:00:00Z"}
            for i, url in enumerate(urls)]
    (folder / "cleaned_results.json").write_text(json.dumps(rows))
    (folder / "cleaned_results.csv").write_text("rank,title,url\n")


def test_aggregate_builds_query_archives_and_repeatability(tmp_path):
    downloads, output = tmp_path / "downloads", tmp_path / "batch"
    downloads.mkdir()
    task_base = {"query_index": 1, "query": "machine learning", "slug": "machine-learning", "result_limit": 2}
    write_artifact(downloads, "q1-r1", {**task_base, "repeat_index": 1}, ["https://a.example/1", "https://b.example/2"])
    write_artifact(downloads, "q1-r2", {**task_base, "repeat_index": 2}, ["https://a.example/1", "https://c.example/3"])
    manifest = {"queries": [{k: v for k, v in task_base.items() if k != "repeat_index"}],
                "repeat_count": 2, "task_count": 2, "region": "in-en", "max_pages": 20}
    summary = aggregate(downloads, output, manifest, "123", "1", "abc")
    assert summary["batch_status"] == "SUCCESS"
    query_summary = summary["queries"][0]
    assert query_summary["unique_results_per_repeat"] == [2, 2]
    assert query_summary["exact_result_set_repeatability"] is False
    assert query_summary["mean_pairwise_jaccard"] == 0.3333
    assert (output / "queries/001-machine-learning/repeat-01/raw_results.json").exists()
    with (output / "aggregate_results.csv").open(encoding="utf-8-sig") as handle:
        assert len(list(csv.DictReader(handle))) == 4


def test_aggregate_marks_missing_artifacts_partial(tmp_path):
    downloads, output = tmp_path / "downloads", tmp_path / "batch"
    downloads.mkdir()
    query = {"query_index": 1, "query": "q", "slug": "q", "result_limit": 10}
    manifest = {"queries": [query], "repeat_count": 2, "task_count": 2}
    summary = aggregate(downloads, output, manifest, "123", "1")
    assert summary["batch_status"] == "FAILED"
    assert summary["artifacts_received"] == 0


def test_aggregate_marks_batch_partial_when_a_task_does_not_reach_target(tmp_path):
    downloads, output = tmp_path / "downloads", tmp_path / "batch"
    downloads.mkdir()
    task = {"query_index": 1, "query": "q", "slug": "q", "result_limit": 10, "repeat_index": 1}
    write_artifact(downloads, "q1-r1", task, ["https://a.example/1"])
    raw_path = downloads / "q1-r1" / "raw_results.json"
    raw = json.loads(raw_path.read_text())
    raw["status"] = "PARTIAL"
    raw_path.write_text(json.dumps(raw))
    manifest = {"queries": [{k: v for k, v in task.items() if k != "repeat_index"}],
                "repeat_count": 1, "task_count": 1}
    summary = aggregate(downloads, output, manifest, "456", "1")
    assert summary["batch_status"] == "PARTIAL"


def test_single_repeat_does_not_claim_repeatability(tmp_path):
    downloads, output = tmp_path / "downloads", tmp_path / "batch"
    downloads.mkdir()
    task = {"query_index": 1, "query": "q", "slug": "q", "result_limit": 1, "repeat_index": 1}
    write_artifact(downloads, "q1-r1", task, ["https://a.example/1"])
    manifest = {"queries": [{k: v for k, v in task.items() if k != "repeat_index"}],
                "repeat_count": 1, "task_count": 1}
    summary = aggregate(downloads, output, manifest, "789", "1")
    item = summary["queries"][0]
    assert item["exact_result_set_repeatability"] is None
    assert item["mean_pairwise_jaccard"] is None
    assert item["all_repeats_reached_target"] is True


def test_empty_repeats_have_undefined_similarity(tmp_path):
    downloads, output = tmp_path / "downloads", tmp_path / "batch"
    downloads.mkdir()
    task = {"query_index": 1, "query": "q", "slug": "q", "result_limit": 10, "repeat_index": 1}
    write_artifact(downloads, "q1-r1", task, [])
    task2 = {**task, "repeat_index": 2}
    write_artifact(downloads, "q1-r2", task2, [])
    manifest = {"queries": [{k: v for k, v in task.items() if k != "repeat_index"}],
                "repeat_count": 2, "task_count": 2}
    summary = aggregate(downloads, output, manifest, "999", "1")
    item = summary["queries"][0]
    assert item["exact_result_set_repeatability"] is None
    assert item["mean_pairwise_jaccard"] is None
    assert item["all_repeats_reached_target"] is False
