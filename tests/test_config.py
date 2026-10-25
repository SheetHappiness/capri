import json
from capri.config import OMP_CONFIG, Pairing


def test_native_approval_config_written_for_omp(tmp_path):
    from capri.config import write_json
    path = tmp_path/'agent/config.yml'
    write_json(path, OMP_CONFIG)
    config = json.loads(path.read_text(encoding='utf-8'))
    assert config['find']['enabled'] == 'on'
    assert config['tools']['approvalMode'] == 'write'
    assert config['tools'].get('approval', {}).get('bash') != 'allow'
    assert config['bash']['patterns'] == [
        {'match': 'git status', 'approval': 'allow'},
        {'match': 'git diff', 'approval': 'allow'},
        {'match': 'git log', 'approval': 'allow'},
        {'match': 'git show', 'approval': 'allow'},
        {'match': 'python --version', 'approval': 'allow'},
        {'match': 'node --version', 'approval': 'allow'},
    ]
    assert config['bash'].get('allowCompoundCommands', False) is False


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
