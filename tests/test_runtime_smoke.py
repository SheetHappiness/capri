import importlib.util
import json
import os
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def smoke():
    path = Path(__file__).resolve().parents[1] / 'scripts/smoke-runtime.py'
    assert path.exists(), 'auth-free smoke is missing'
    spec = importlib.util.spec_from_file_location('capri_runtime_smoke', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(smoke, tmp_path, monkeypatch, *, stopped=True, timeout=False):
    exe = tmp_path / 'candidate.exe'
    exe.write_bytes(b'candidate')
    data = tmp_path / 'scratch'
    calls = []
    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.root = Path(kwargs['env']['PI_CODING_AGENT_DIR']).parent
        def start(self):
            (self.root / 'cache/natives').mkdir(parents=True, exist_ok=True)
            (self.root / 'cache/natives/pi_natives.win32-x64-baseline.node').write_bytes(b'addon')
        def get_state(self):
            return SimpleNamespace(session_file=str(self.root / 'agent/sessions/test.jsonl'))
        def stop(self):
            return stopped
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if timeout:
            raise smoke.subprocess.TimeoutExpired(argv, 30)
        return SimpleNamespace(returncode=0, stdout='omp/18.12.6\n', stderr='')
    monkeypatch.setattr(smoke, 'RpcClient', Client)
    monkeypatch.setattr(smoke, 'run_command', run)
    # Windows socket limit is tested separately with a deliberately long path.
    monkeypatch.setattr(smoke, 'MAX_TEMP_BYTES', 1000)
    return exe, data, calls


def test_smoke_requires_confirmed_stop(smoke, tmp_path, monkeypatch):
    exe, data, _ = prepare(smoke, tmp_path, monkeypatch, stopped=False)
    with pytest.raises(RuntimeError, match='teardown'):
        smoke.run_smoke(exe, data)
    assert json.loads((data / 'smoke-result.json').read_text())['passed'] is False


def test_smoke_timeout_fails(smoke, tmp_path, monkeypatch):
    exe, data, _ = prepare(smoke, tmp_path, monkeypatch, timeout=True)
    with pytest.raises(smoke.subprocess.TimeoutExpired):
        smoke.run_smoke(exe, data)
    assert json.loads((data / 'smoke-result.json').read_text())['passed'] is False


def test_smoke_uses_fresh_private_environment(smoke, tmp_path, monkeypatch):
    exe, data, calls = prepare(smoke, tmp_path, monkeypatch)
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-secret')
    monkeypatch.setenv('CODEX_HOME', 'foreign')
    before = dict(os.environ)
    report = smoke.run_smoke(exe, data)
    assert report['passed'] and report['native_extraction'] and report['teardown']
    assert dict(os.environ) == before
    for call in calls:
        kwargs = call[1] if isinstance(call, tuple) else call
        env = kwargs['env']
        assert 'OPENAI_API_KEY' not in env and 'CODEX_HOME' not in env
        for key in ('CAPRI_OMP_ROOT', 'PI_CODING_AGENT_DIR', 'PI_NATIVES_DIR', 'TEMP'):
            assert Path(env[key]).is_relative_to(data)
        assert env['HOME'] == before.get('HOME', '')
    client = next(call for call in calls if isinstance(call, dict))
    assert client['tools'] == ()
    assert '--no-extensions' in client['extra_args']
    config = next(call[0] for call in calls if isinstance(call, tuple) and 'config' in call[0])
    assert '--config' not in config  # This subcommand has its own flag parser.


def test_smoke_rejects_nonempty_scratch(smoke, tmp_path, monkeypatch):
    exe, data, calls = prepare(smoke, tmp_path, monkeypatch)
    data.mkdir()
    (data / 'auth.db').write_bytes(b'sentinel')
    with pytest.raises(ValueError, match='empty'):
        smoke.run_smoke(exe, data)
    assert not calls and (data / 'auth.db').read_bytes() == b'sentinel'


def test_smoke_long_path_has_actionable_error(smoke, tmp_path, monkeypatch):
    exe, data, calls = prepare(smoke, tmp_path, monkeypatch)
    monkeypatch.setattr(smoke, 'MAX_TEMP_BYTES', 20)
    with pytest.raises(ValueError, match='shorter Data'):
        smoke.run_smoke(exe, data)
    assert not calls


def test_smoke_cli_handles_unicode_path_with_legacy_stdout(smoke, tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, 'run_smoke', lambda *args: {'passed': True})
    monkeypatch.setattr(sys, 'argv', ['smoke-runtime.py', '--omp', str(tmp_path / 'omp.exe'),
                                     '--data', str(tmp_path / 'Я 1')])
    class LegacyConsole(io.StringIO):
        def write(self, text):
            text.encode('cp1252')
            return super().write(text)
    output = LegacyConsole()
    with redirect_stdout(output):
        smoke.main()
    assert 'passed' in output.getvalue()
