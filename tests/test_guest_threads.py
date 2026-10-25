import json
from dataclasses import replace
import pytest
from capri.guest_threads import GuestThreadStore, ThreadError


def test_persistence_switching_and_chat_scoping(tmp_path):
    store = GuestThreadStore(tmp_path)
    assert store.current(-17) is None
    first = store.ensure_current(-17)
    assert store.ensure_current(-17) == first
    second = store.new(-17, 'Travel')
    assert first.id != second.id
    store = GuestThreadStore(tmp_path)
    assert store.current(-17) == second
    assert store.list(-17)[0] == second
    assert store.resume(-17, first.id[:8]).id == first.id
    store.rename_current(-17, 'Laptop')
    assert GuestThreadStore(tmp_path).current(-17).title == 'Laptop'
    assert store.resume(-17, 'travel').id == second.id
    assert store.list(18) == ()
    with pytest.raises(ThreadError): store.resume(18, first.id)
    directory = store.session_dir(first)
    assert directory == tmp_path.resolve() / 'guest' / 'sessions' / '-17' / first.id
    with pytest.raises(ThreadError): store.session_dir(replace(first, id='../escape'))
    assert str(tmp_path) not in (tmp_path/'guest/threads.json').read_text()


def test_ambiguous_selector_and_touch(tmp_path):
    store = GuestThreadStore(tmp_path)
    a = store.new(1, 'Same'); store.new(1, 'same')
    with pytest.raises(ThreadError): store.resume(1, 'SAME')
    store.resume(1, a.id)
    old = store.current(1).updated_at
    store.touch(1)
    assert store.current(1).updated_at >= old


@pytest.mark.parametrize('raw', ['', '[]', '{}', '{', '{"threads":[],"current":{"1":"../bad"}}',
    json.dumps({'threads':[{'id':'../bad','chat_id':1}], 'current':{}})])
def test_malformed_store_fails_closed(tmp_path, raw):
    path = tmp_path/'guest/threads.json'; path.parent.mkdir(); path.write_text(raw)
    with pytest.raises(ThreadError): GuestThreadStore(tmp_path)
    assert path.read_text() == raw
