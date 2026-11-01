import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.query_batch import build_matrix, parse_query_lines


def test_parse_queries_with_independent_limits_and_default():
    specs = parse_query_lines("machine learning papers :: 100\nSearXNG pagination\t50\nagentic search", 25)
    assert [(x.query, x.result_limit) for x in specs] == [
        ("machine learning papers", 100), ("SearXNG pagination", 50), ("agentic search", 25)]
    assert specs[0].query_index == 1
    assert specs[1].slug == "searxng-pagination"


def test_parse_ignores_blank_and_comment_lines():
    specs = parse_query_lines("# comment\n\n  first query  \n", 10)
    assert len(specs) == 1 and specs[0].query == "first query"


@pytest.mark.parametrize("value", ["", "   ", "q\t0", "q\t1001", "q\tnope", "same\nSAME"])
def test_invalid_batch_inputs_are_rejected(value):
    with pytest.raises(ValueError):
        parse_query_lines(value, 50)


def test_batch_caps_query_count_and_length():
    with pytest.raises(ValueError): parse_query_lines("\n".join(f"q{i}" for i in range(21)), 50)
    with pytest.raises(ValueError): parse_query_lines("x" * 513, 50)


def test_build_matrix_creates_query_repeat_cross_product():
    specs = parse_query_lines("q1\t10\nq2\t20", 50)
    tasks = build_matrix(specs, 3)
    assert len(tasks) == 6
    assert [(x["query_index"], x["repeat_index"]) for x in tasks] == [
        (1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3)]
    with pytest.raises(ValueError): build_matrix(specs, 4)


def test_prepare_batch_script_emits_matrix_and_manifest(tmp_path):
    output = tmp_path / "github-output.txt"
    env = os.environ.copy()
    env.update({"SEARCH_QUERIES": "alpha :: 10\nbeta :: 20", "DEFAULT_RESULT_LIMIT": "50",
                "SEARCH_REGION": "in-en", "MAX_PAGES": "30", "REPEAT_COUNT": "2",
                "MAX_PARALLEL": "3", "PAGE_DELAY": "2", "MAX_QUERIES": "20",
                "GITHUB_OUTPUT": str(output)})
    root = Path(__file__).parents[1]
    subprocess.run([sys.executable, "scripts/prepare_batch.py"], cwd=root, env=env, check=True,
                   capture_output=True, text=True)
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    matrix = json.loads(values["matrix"])
    manifest = json.loads(values["manifest"])
    assert len(matrix) == 4
    assert manifest["task_count"] == 4
    assert manifest["max_pages"] == 30


def test_workflow_is_manual_dynamic_matrix_and_searxng_only():
    import yaml
    workflow = yaml.safe_load((Path(__file__).parents[1] / ".github/workflows/duckduckgo-search.yml").read_text())
    triggers = workflow.get("on", workflow.get(True, {}))
    assert set(triggers) == {"workflow_dispatch"}
    assert workflow["jobs"]["collect"]["strategy"]["fail-fast"] is False
    assert workflow["jobs"]["collect"]["strategy"]["matrix"]["include"] == "${{ fromJSON(needs.prepare.outputs.matrix) }}"
    assert "aggregate" in workflow["jobs"]
    assert "result_limit" in triggers["workflow_dispatch"]["inputs"]
    assert "default_result_limit" not in triggers["workflow_dispatch"]["inputs"]
    workflow_text = (Path(__file__).parents[1] / ".github/workflows/duckduckgo-search.yml").read_text()
    assert "searxng_collector.py" in workflow_text
    assert "ddgs" not in workflow_text.lower()
    settings = yaml.safe_load((Path(__file__).parents[1] / "config/searxng-settings.yml").read_text())
    assert settings["use_default_settings"]["engines"]["keep_only"] == ["duckduckgo"]
    image_tag = (Path(__file__).parents[1] / "config/searxng-image.txt").read_text().strip()
    assert image_tag and "latest" not in image_tag
