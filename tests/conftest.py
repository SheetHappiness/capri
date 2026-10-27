import os
from pathlib import Path

import pytest


@pytest.fixture
def assert_private_omp_environment(monkeypatch):
    """Check the spawn boundary with deliberately conflicting inherited state."""
    for key in ('CAPRI_OMP_ROOT', 'PI_CODING_AGENT_DIR', 'PI_NATIVES_DIR',
                'BUN_INSTALL_CACHE_DIR', 'BUN_RUNTIME_TRANSPILER_CACHE_PATH',
                'TEMP', 'TMP', 'OMP_PROFILE', 'PI_PROFILE', 'PI_CONFIG_DIR'):
        monkeypatch.setenv(key, 'foreign-state')
    home = {key: os.environ.get(key) for key in ('HOME', 'USERPROFILE')}

    def check(env, data, *, merged=False):
        expected = {'CAPRI_OMP_ROOT': 'omp-root', 'PI_CODING_AGENT_DIR': 'agent',
                    'PI_NATIVES_DIR': 'cache/natives', 'BUN_INSTALL_CACHE_DIR': 'cache/bun',
                    'BUN_RUNTIME_TRANSPILER_CACHE_PATH': 'cache/transpiler',
                    'TEMP': 'tmp', 'TMP': 'tmp'}
        for key, suffix in expected.items():
            assert env[key] == str(data.resolve() / suffix)
            assert Path(env[key]).is_dir()  # Must exist before the fake starts.
        assert env['OMP_PROFILE'] == env['PI_PROFILE'] == ''
        assert env['PI_CONFIG_DIR'] == '.capri-omp'
        for key, value in home.items():
            if merged:
                assert env.get(key) == value
            else:
                assert key not in env
    return check
