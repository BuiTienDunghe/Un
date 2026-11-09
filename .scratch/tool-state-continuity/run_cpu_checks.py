"""CPU-only validation against disposable local services; never starts models."""
import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('--database', required=True)
p.add_argument('--redis', required=True)
p.add_argument('--qdrant', required=True)
p.add_argument('--phase', choices=['focused', 'full', 'eval', 'bfcl'], default='focused')
p.add_argument('--label', required=True)
a = p.parse_args()
repo = Path(__file__).resolve().parents[2]
out = repo / 'data/logs/tool-state-continuity-2026-11-09' / a.label
out.mkdir(parents=True, exist_ok=False)
env = os.environ.copy()
env.update({
    'PYTHONPATH': os.pathsep.join([str(repo / '.scratch/backend-small-fixes-followups/cpu_guard'), str(repo / 'backend'), str(repo)]),
    'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1',
    'CUDA_VISIBLE_DEVICES': '', 'NVIDIA_VISIBLE_DEVICES': 'void',
    'DATABASE_URL': a.database, 'POSTGRES_TEST_URL': a.database,
    'REDIS_URL': a.redis, 'REDIS_TEST_URL': a.redis, 'QDRANT_URL': a.qdrant,
    'OLLAMA_BASE_URL': 'http://127.0.0.1:1', 'GEMINI_API_KEY': '',
    'ANTHROPIC_API_KEY': '', 'DEEPSEEK_API_KEY': '', 'MODEL_STARTUP_PROBES': 'false',
    'RAG_RERANKER_ENABLED': 'false', 'RAG_CONTEXTUAL_RETRIEVAL_ENABLED': 'false',
    'RQ_QUEUE_PREFIX': 'codex-state', 'NO_PROXY': '127.0.0.1,localhost',
})
env.pop('HF_HUB_OFFLINE', None)
env.pop('TRANSFORMERS_OFFLINE', None)
records = []
def run(label, args, cwd):
    started = datetime.now(UTC).isoformat()
    with (out / (label + '.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run([sys.executable, '-B', *args], cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    records.append({'step': label, 'exit': result.returncode, 'started': started, 'finished': datetime.now(UTC).isoformat()})
    (out / 'steps.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print(json.dumps(records[-1]), flush=True)
    return result.returncode
probe = 'import app,pathlib,os,socket; p=pathlib.Path(app.__file__).resolve(); print(p); assert p.is_relative_to(pathlib.Path(' + repr(str(repo)) + ')); assert os.environ["CUDA_VISIBLE_DEVICES"]==""; assert socket.socket.connect.__module__=="sitecustomize"'
if run('cpu-guard', ['-c', probe], repo / 'backend'):
    sys.exit(2)
if run('migration', ['-m', 'alembic', 'upgrade', 'head'], repo):
    sys.exit(3)
tests = (['tests/test_bfcl_tool_state.py', 'tests/test_bfcl_run.py', 'tests/test_tool_state_chat.py',
          'tests/test_tool_state.py', 'tests/test_tool_state_eval.py', 'tests/test_input_metrics.py']
         if a.phase == 'bfcl' else ['tests/test_tool_state_eval.py'] if a.phase == 'eval' else ['tests'] if a.phase == 'full' else [
    'tests/test_tool_state.py', 'tests/test_tool_state_chat.py', 'tests/test_tool_state_store.py',
    'tests/test_input_metrics.py', 'tests/test_agent_promise_check.py',
    'tests/test_tool_state_eval.py',
    'tests/test_discord_tool_state_context.py', 'tests/test_forget_tool_state.py',
    'tests/test_agent_service.py', 'tests/test_context_budget.py',
    'tests/test_source_page_counts.py', 'tests/test_batched_document_listing.py',
    'tests/test_database_url_contract.py', 'tests/test_frontend_error_contract.py',
])
code = run('pytest', ['-m', 'pytest', *tests, '-q', '-p', 'no:cacheprovider', '--tb=short', '--junitxml=' + str(out / 'pytest.xml')], repo / 'backend')
schema = run('schema-check', ['-m', 'alembic', 'check'], repo)
sys.exit(code or schema)
