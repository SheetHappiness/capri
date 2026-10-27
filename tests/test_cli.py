import sys
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from capri import cli
from capri.sdk_provenance import SdkProvenanceError


@pytest.fixture(autouse=True)
def valid_sdk(monkeypatch):
    monkeypatch.setattr(cli, 'verify_sdk_provenance', lambda: None, raising=False)


@pytest.mark.parametrize('probe', [None, 'answer', 'edit'])
def test_cli_selects_probe_without_starting_dm(tmp_path, monkeypatch, probe):
    (tmp_path/'bot-token').write_text('123:TEST', encoding='utf-8')
    (tmp_path/'bin').mkdir()
    (tmp_path/'bin/omp.exe').write_bytes(b'exe')
    args = ['capri', '--data', str(tmp_path)]
    if probe:
        args += ['--guest-probe', probe]
    monkeypatch.setattr(sys, 'argv', args)
    dm, guest = AsyncMock(), AsyncMock()
    monkeypatch.setattr('capri.app.run', dm)
    monkeypatch.setattr('capri.guest_probe.run_guest_probe', guest)
    cli.main()
    if probe:
        guest.assert_awaited_once_with('123:TEST', tmp_path.resolve(), phase=probe)
        dm.assert_not_called()
    else:
        dm.assert_awaited_once()
        guest.assert_not_called()


@pytest.mark.parametrize('override', [None, 'relative.exe', 'absolute'])
def test_cli_resolves_runtime_from_data_or_explicit_override(tmp_path, monkeypatch, override):
    monkeypatch.chdir(tmp_path)
    data = tmp_path / 'дані з пробілами'
    data.mkdir()
    (data / 'bot-token').write_text('123:TEST')
    runtime = data / 'bin/omp.exe' if override is None else tmp_path / 'relative.exe'
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_bytes(b'exe')
    args = ['capri', '--data', str(data)]
    if override:
        args += ['--omp', str(runtime) if override == 'absolute' else 'relative.exe']
    monkeypatch.setattr(sys, 'argv', args)
    dm = AsyncMock()
    monkeypatch.setattr('capri.app.run', dm)
    cli.main()
    dm.assert_awaited_once_with('123:TEST', runtime.resolve(), data.resolve())


def test_cli_missing_runtime_stops_before_telegram(tmp_path, monkeypatch, capsys):
    (tmp_path / 'bot-token').write_text('123:TEST')
    monkeypatch.setattr(sys, 'argv', ['capri', '--data', str(tmp_path)])
    dm = AsyncMock()
    monkeypatch.setattr('capri.app.run', dm)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert 'bootstrap.ps1 -Data' in capsys.readouterr().err
    dm.assert_not_called()


def test_guest_probe_does_not_require_runtime(tmp_path, monkeypatch):
    (tmp_path / 'bot-token').write_text('123:TEST')
    monkeypatch.setattr(sys, 'argv', ['capri', '--data', str(tmp_path), '--guest-probe', 'answer'])
    guest = AsyncMock()
    monkeypatch.setattr('capri.guest_probe.run_guest_probe', guest)
    cli.main()
    guest.assert_awaited_once()


@pytest.mark.parametrize('override', [False, True])
def test_cli_rejects_foreign_sdk_before_credentials_or_services(tmp_path, monkeypatch, capsys, override):
    def reject():
        raise SdkProvenanceError('Capri requires the SDK from this checkout. From the checkout root run:\n'
                                 '.venv/Scripts/python -m pip install -r requirements-runtime.txt')

    def forbidden(*args, **kwargs):
        pytest.fail('SDK rejection must precede token reads and service startup')

    args = ['capri', '--data', str(tmp_path)]
    if override:
        args += ['--omp', str(tmp_path / 'override.exe')]
    monkeypatch.setattr(sys, 'argv', args)
    monkeypatch.setattr(cli, 'verify_sdk_provenance', reject)
    monkeypatch.setattr(Path, 'read_text', forbidden)
    monkeypatch.setattr('capri.app.run', forbidden)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert 'requirements-runtime.txt' in capsys.readouterr().err


def test_guest_probe_skips_sdk_guard(tmp_path, monkeypatch):
    def forbidden():
        pytest.fail('Telegram-only probe must not check the SDK')

    (tmp_path / 'bot-token').write_text('123:TEST')
    monkeypatch.setattr(sys, 'argv', ['capri', '--data', str(tmp_path), '--guest-probe', 'answer'])
    monkeypatch.setattr(cli, 'verify_sdk_provenance', forbidden)
    guest = AsyncMock()
    monkeypatch.setattr('capri.guest_probe.run_guest_probe', guest)
    cli.main()
    guest.assert_awaited_once()


@pytest.mark.parametrize('mode', ['help', 'reject', 'probe'])
def test_cli_does_not_import_sdk_before_guard_or_for_help_and_probe(tmp_path, mode):
    # Fresh interpreter: existing imports in other tests cannot hide eager imports.
    script = '''
import importlib.abc
import importlib.metadata
import runpy
import sys
from pathlib import Path
class BlockSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'omp_rpc' or fullname == 'capri.app':
            raise AssertionError('SDK-dependent import before guard')
sys.meta_path.insert(0, BlockSdk())
mode, data = sys.argv[1:]
def missing(name):
    raise importlib.metadata.PackageNotFoundError(name)
importlib.metadata.distribution = missing
if mode == 'help':
    sys.argv = ['capri', '--help']
elif mode == 'probe':
    import capri.guest_probe
    async def probe(*args, **kwargs):
        print('probe started')
    capri.guest_probe.run_guest_probe = probe
    Path(data, 'bot-token').write_text('123:TEST')
    sys.argv = ['capri', '--data', data, '--guest-probe', 'answer']
else:
    sys.argv = ['capri', '--data', data]
runpy.run_module('capri.cli', run_name='__main__')
'''
    result = subprocess.run([sys.executable, '-c', script, mode, str(tmp_path)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == (2 if mode == 'reject' else 0), result.stdout + result.stderr
    if mode == 'reject':
        assert 'requirements-runtime.txt' in result.stderr
        assert 'Traceback' not in result.stderr
    elif mode == 'probe':
        assert 'probe started' in result.stdout
    else:
        assert '--help' in result.stdout
