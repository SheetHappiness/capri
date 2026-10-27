import os
from pathlib import Path

import pytest

from capri.config import Pairing, omp_environment


@pytest.mark.parametrize('name', ['data', 'Capri data', 'Capri дані'])
@pytest.mark.parametrize('relative', [False, True])
def test_omp_environment_uses_absolute_private_paths(tmp_path, monkeypatch, name, relative):
    monkeypatch.chdir(tmp_path)
    data = Path(name) if relative else tmp_path / name
    root = data.resolve()
    env = omp_environment(data)
    assert env == {
        'CAPRI_OMP_ROOT': str(root / 'omp-root'),
        'PI_CODING_AGENT_DIR': str(root / 'agent'),
        'PI_NATIVES_DIR': str(root / 'cache/natives'),
        'BUN_INSTALL_CACHE_DIR': str(root / 'cache/bun'),
        'BUN_RUNTIME_TRANSPILER_CACHE_PATH': str(root / 'cache/transpiler'),
        'TEMP': str(root / 'tmp'), 'TMP': str(root / 'tmp'),
        'OMP_PROFILE': '', 'PI_PROFILE': '', 'PI_CONFIG_DIR': '.capri-omp',
    }
    monkeypatch.chdir(tmp_path.parent)
    for key in ('CAPRI_OMP_ROOT', 'PI_CODING_AGENT_DIR', 'PI_NATIVES_DIR', 'BUN_INSTALL_CACHE_DIR',
                'BUN_RUNTIME_TRANSPILER_CACHE_PATH', 'TEMP', 'TMP'):
        assert Path(env[key]).is_absolute() and Path(env[key]).is_dir()
    assert omp_environment(root) == env


def test_omp_environment_does_not_mutate_parent(tmp_path, monkeypatch):
    for key in ('OMP_PROFILE', 'PI_PROFILE', 'CAPRI_OMP_ROOT', 'PI_CODING_AGENT_DIR',
                'PI_NATIVES_DIR', 'BUN_INSTALL_CACHE_DIR', 'BUN_RUNTIME_TRANSPILER_CACHE_PATH',
                'TEMP', 'TMP', 'HOME', 'USERPROFILE'):
        monkeypatch.setenv(key, 'inherited-value')
    before = dict(os.environ)
    env = omp_environment(tmp_path)
    assert env['OMP_PROFILE'] == env['PI_PROFILE'] == ''
    for key in ('CAPRI_OMP_ROOT', 'PI_CODING_AGENT_DIR', 'PI_NATIVES_DIR', 'BUN_INSTALL_CACHE_DIR',
                'BUN_RUNTIME_TRANSPILER_CACHE_PATH', 'TEMP', 'TMP'):
        assert env[key] != before[key]
    assert 'HOME' not in env and 'USERPROFILE' not in env
    assert dict(os.environ) == before


def test_omp_environment_refuses_unusable_temp(tmp_path):
    (tmp_path / 'tmp').write_text('not a directory')
    with pytest.raises(OSError):
        omp_environment(tmp_path)

def test_explicit_one_time_pairing_and_persistence(tmp_path):
    p=Pairing(tmp_path/'owner.json')
    nonce=p.nonce
    assert not p.accept(100,'/start wrong')
    assert not p.accept(100,'hello')
    assert p.accept(200,'/start '+nonce)
    assert p.owner_id==200
    assert not p.accept(100,'/start '+nonce)
    assert Pairing(tmp_path/'owner.json').owner_id==200

def test_pairing_nonce_is_not_reusable_after_restart(tmp_path):
    path=tmp_path/'owner.json'
    old=Pairing(path).nonce
    fresh=Pairing(path)
    assert fresh.nonce != old
    assert not fresh.accept(100,'/start '+old)

def test_unpaired_unicode_message_is_ignored_without_crash(tmp_path):
    p=Pairing(tmp_path/'owner.json')
    assert not p.accept(100,'Привіт')
    assert p.owner_id is None
