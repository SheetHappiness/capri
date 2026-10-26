"""Seams are dormant, offline, scoped and preserve extracted utility behavior."""
import threading
from types import SimpleNamespace
import pytest

def test_auxiliary_seam_never_calls_a_model():
    from capri._vendor.hermes.compat import auxiliary_client
    from capri._vendor.hermes.tools.approval_smart import _smart_approve
    with pytest.raises(RuntimeError,match='dormant'): auxiliary_client.call_llm(task='approval')
    assert _smart_approve('echo hi','test') == 'escalate'

def test_smart_verdict_vocabulary(monkeypatch):
    from capri._vendor.hermes.compat import auxiliary_client
    from capri._vendor.hermes.tools.approval_smart import _smart_approve
    for response,want in [('APPROVE','approve'),('DENY','deny'),('ESCALATE','escalate'),('','escalate'),('approve please','escalate')]:
        monkeypatch.setattr(auxiliary_client,'call_llm',lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=response))]))
        assert _smart_approve('echo hi','test') == want

def test_terminal_batch_is_inert():
    from capri._vendor.hermes.compat import terminal_approval_batch as batch
    assert batch.consume_prepared_guard('echo hi','local',False) is None
    assert batch.preparing_terminal_approval() is False
    assert batch.register_prepared_approval('session',object()) is None
    assert batch.approval_published() is None

@pytest.mark.parametrize('value,want',[('1',True),(' YES ',True),('false',False),('',False),('on',True),('off',False)])
def test_interrupt_debug_environment_flag(monkeypatch,value,want):
    from capri._vendor.hermes.compat.utils import env_var_enabled
    monkeypatch.setenv('HERMES_DEBUG_INTERRUPT',value)
    assert env_var_enabled('HERMES_DEBUG_INTERRUPT') is want

def test_interrupt_yield_reason_and_acting_thread():
    from capri._vendor.hermes.tools import interrupt as i
    tid=threading.get_ident()+1
    i.request_yield(tid)
    assert i.is_thread_yield_requested(tid)
    assert i.consume_yield(tid) and not i.consume_yield(tid)
    token=i.acting_for_tid.set(tid)
    try:
        i.set_interrupt(True,tid,reason='stop')
        assert i.is_interrupted()
        i.set_interrupt(False,tid)
        assert not i.is_interrupted()
    finally:
        i.set_interrupt(False,tid); i.acting_for_tid.reset(token)

def test_redaction_subset_does_not_pass_through_secrets():
    from capri._vendor.hermes.compat.redact import redact_sensitive_text as redact
    secret='sk-proj-abc123xyz4567890abcdef'
    assert secret not in redact(secret,force=True)
    assert 'Authorization: Bearer ***' in redact('Authorization: Bearer '+secret,force=True)
    assert 'mypass' not in redact('postgresql://user:mypass@host/db',force=True)
    assert redact('rm -rf /var/data',force=True) == 'rm -rf /var/data'

def test_config_boundary_never_persists(tmp_path,monkeypatch):
    from capri._vendor.hermes.compat import config
    monkeypatch.setenv('HERMES_HOME',str(tmp_path))
    assert config.load_config_readonly() == {} and config.load_config() == {}
    with pytest.raises(RuntimeError,match='dormant'): config.save_config({'approvals':{'mode':'off'}})
    assert list(tmp_path.iterdir()) == []

def test_optional_transport_fails_closed(monkeypatch):
    from capri._vendor.hermes.compat import config
    from capri._vendor.hermes.tools.approval_prompt import _present_with_selected_transport
    monkeypatch.setattr(config,'load_config_readonly',lambda: {'security':{'approval':{'transport':'missing-plugin'}}})
    result=_present_with_selected_transport(command='echo hi',description='test',pattern_key='p',pattern_keys=['p'],session_key='s',surface='cli',allow_session=True,allow_permanent=True)
    assert result['selected'] and result['choice']=='deny' and result['failure']=='unavailable'

def test_lifecycle_subset_recognizes_spliced_commands():
    from capri._vendor.hermes.compat.lifecycle_guard import contains_gateway_lifecycle_command as detect
    assert detect('launchctl kick"start" -k gui/501/ai.hermes.gateway')
    assert detect('hermes gateway restart')
    assert not detect('echo hello')

def test_runtime_self_protection_is_active():
    import sys
    from capri._vendor.hermes.compat.runtime_self_protection import command_deletes_runtime
    assert command_deletes_runtime('rm "'+sys.executable+'"')
    assert command_deletes_runtime('echo hello') is None
