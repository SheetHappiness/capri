import sys
from unittest.mock import AsyncMock

import pytest

from capri import cli


@pytest.mark.parametrize('probe', [None, 'answer', 'edit'])
def test_cli_selects_probe_without_starting_dm(tmp_path, monkeypatch, probe):
    (tmp_path/'bot-token').write_text('123:TEST', encoding='utf-8')
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
