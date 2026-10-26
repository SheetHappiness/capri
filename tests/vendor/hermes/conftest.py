"""Only local vendor tests: no sys.modules aliases or upstream runtime fixtures."""
import importlib.util
import os
import sys
import pytest

def pytest_configure(config):
    config.addinivalue_line('markers','platforms(*names): upstream operating-system gate')
    config.addinivalue_line('markers','require_symlinks: requires OS symbolic-link capability')

@pytest.fixture(autouse=True)
def isolated_hermes_environment(monkeypatch, tmp_path, request):
    for name in list(os.environ):
        if name.startswith('HERMES_'):
            monkeypatch.delenv(name)
    monkeypatch.setenv('HERMES_HOME',str(tmp_path/'hermes'))
    mark=request.node.get_closest_marker('platforms')
    host='windows' if sys.platform=='win32' else 'macos' if sys.platform=='darwin' else 'linux'
    if mark and host not in mark.args and 'any' not in mark.args and not ('posix' in mark.args and host!='windows'):
        pytest.skip('upstream platform gate: '+','.join(mark.args))
    if request.node.get_closest_marker('require_symlinks'):
        target=tmp_path/'target'; target.mkdir()
        try: (tmp_path/'link').symlink_to(target,target_is_directory=True)
        except OSError: pytest.skip('upstream symlink capability unavailable on this host')
    yield
