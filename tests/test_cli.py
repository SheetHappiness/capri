import sys
from unittest.mock import AsyncMock

import pytest

from capri import cli


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
    monkeypatch.setattr(cli, 'run', dm)
    monkeypatch.setattr(cli, 'run_guest_probe', guest)
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
    monkeypatch.setattr(cli, 'run', dm)
    cli.main()
    dm.assert_awaited_once_with('123:TEST', runtime.resolve(), data.resolve())


def test_cli_missing_runtime_stops_before_telegram(tmp_path, monkeypatch, capsys):
    (tmp_path / 'bot-token').write_text('123:TEST')
    monkeypatch.setattr(sys, 'argv', ['capri', '--data', str(tmp_path)])
    dm = AsyncMock()
    monkeypatch.setattr(cli, 'run', dm)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert 'bootstrap.ps1 -Data' in capsys.readouterr().err
    dm.assert_not_called()


def test_guest_probe_does_not_require_runtime(tmp_path, monkeypatch):
    (tmp_path / 'bot-token').write_text('123:TEST')
    monkeypatch.setattr(sys, 'argv', ['capri', '--data', str(tmp_path), '--guest-probe', 'answer'])
    guest = AsyncMock()
    monkeypatch.setattr(cli, 'run_guest_probe', guest)
    cli.main()
    guest.assert_awaited_once()
