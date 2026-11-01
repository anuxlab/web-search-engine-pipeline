#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python -m py_compile src/search_collector.py scripts/provider_experiment.py tests/test_search_collector.py tests/test_provider_experiment.py
python -m pytest -q
bash -n scripts/archive_run.sh
python - <<'PY'
from pathlib import Path
import yaml
workflow_dir = Path('.github/workflows')
for path in sorted(workflow_dir.glob('*.yml')):
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    # PyYAML's YAML 1.1 resolver maps the literal GitHub key `on` to True.
    triggers = data.get('on', data.get(True, {}))
    assert triggers, f'{path}: missing trigger declaration'
    if path.name != '_provider-experiment.yml':
        assert set(triggers) == {'workflow_dispatch'}, f'{path}: should be manually triggered only'
    else:
        assert set(triggers) == {'workflow_call'}, f'{path}: reusable workflow must only use workflow_call'
    print(f'{path}: triggers={list(triggers)}')
print('All workflow YAML files parsed; dispatch workflows are manual-only.')
PY
