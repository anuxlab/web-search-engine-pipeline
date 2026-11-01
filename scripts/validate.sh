#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python -m py_compile \
  src/search_collector.py src/searxng_collector.py src/query_batch.py \
  scripts/provider_experiment.py scripts/prepare_batch.py scripts/aggregate_batch.py \
  tests/test_search_collector.py tests/test_provider_experiment.py \
  tests/test_searxng_collector.py tests/test_query_batch.py tests/test_aggregate_batch.py
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
    if path.name == '_provider-experiment.yml':
        assert set(triggers) == {'workflow_call'}, f'{path}: reusable workflow must only use workflow_call'
    else:
        assert set(triggers) == {'workflow_dispatch'}, f'{path}: should be manually triggered only'
    print(f'{path}: triggers={list(triggers)}')
main = yaml.safe_load(Path('.github/workflows/duckduckgo-search.yml').read_text())
assert 'collect' in main['jobs'] and 'aggregate' in main['jobs'] and 'prepare' in main['jobs']
assert main['jobs']['collect']['strategy']['fail-fast'] is False
assert main['jobs']['collect']['strategy']['matrix']['include'] == '${{ fromJSON(needs.prepare.outputs.matrix) }}'
assert 'workflow_dispatch' in str(main.get('on', main.get(True, {})))
settings = yaml.safe_load(Path('config/searxng-settings.yml').read_text())
assert settings['use_default_settings']['engines']['keep_only'] == ['duckduckgo']
assert settings['search']['formats'] == ['html', 'json']
image_tag = Path('config/searxng-image.txt').read_text(encoding='utf-8').strip()
assert image_tag and 'latest' not in image_tag
import re, subprocess, tempfile
for workflow in workflow_dir.glob('*.yml'):
    data = yaml.safe_load(workflow.read_text(encoding='utf-8'))
    for job_name, job in data.get('jobs', {}).items():
        for index, step in enumerate(job.get('steps', [])):
            run = step.get('run')
            if not run:
                continue
            shell = re.sub(r'\$\{\{.*?\}\}', 'placeholder', run, flags=re.S)
            with tempfile.NamedTemporaryFile('w', suffix='.sh', encoding='utf-8') as handle:
                handle.write(shell); handle.flush()
                subprocess.run(['bash', '-n', handle.name], check=True)
            match = re.search(r"python - <<'PY'\n(.*?)\nPY", run, re.S)
            if match:
                compile(match.group(1), f'{workflow}:{job_name}:{index}', 'exec')
print('All workflows, manual-only triggers, matrix wiring, SearXNG settings, shell blocks, and embedded Python validated.')
PY
