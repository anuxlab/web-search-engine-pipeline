#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python -m py_compile src/search_collector.py tests/test_search_collector.py
python -m pytest -q
bash -n scripts/archive_run.sh
python - <<'PY'
from pathlib import Path
import yaml
workflow = Path('.github/workflows/duckduckgo-search.yml').read_text(encoding='utf-8')
yaml.safe_load(workflow)
assert 'workflow_dispatch:' in workflow
assert '\n  push:' not in workflow
assert 'collection_strategy:' in workflow
print('Workflow YAML and manual-only trigger checks passed.')
PY
