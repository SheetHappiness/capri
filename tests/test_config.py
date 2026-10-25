from capri.config import Pairing

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
