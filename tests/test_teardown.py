"""Capri's confirmation rule against the pinned SDK's real stop implementation."""
from types import SimpleNamespace as NS
import pytest
from omp_rpc import RpcClient
from capri.teardown import stop_child


@pytest.mark.parametrize('result,want', [(True,True),(False,False),(None,False),(1,False),('yes',False)])
def test_only_explicit_confirmation_releases_child(result,want):
    assert stop_child(NS(stop=lambda: result)) is want


def test_stop_exception_is_unsafe():
    def fail(): raise OSError('private detail')
    assert stop_child(NS(stop=fail)) is False


class Process:
    """Only the subprocess boundary is fake; RpcClient.stop remains real."""
    stdin = stdout = stderr = None
    pid = 123

    def __init__(self, exited=False, unkillable=False):
        self.returncode=0 if exited else None
        self.unkillable=unkillable

    def poll(self): return self.returncode
    def terminate(self):
        if not self.unkillable: self.returncode=1
    def kill(self): self.terminate()
    def wait(self, timeout):
        import subprocess
        if self.returncode is None: raise subprocess.TimeoutExpired('fake',timeout)
        return self.returncode


@pytest.mark.parametrize('exited', [False,True])
def test_sdk_normal_and_already_exited_stop(exited):
    client=RpcClient()
    process=Process(exited=exited)
    client._process=process
    assert stop_child(client) is True
    assert process.poll() is not None and client.survivor_pids==()
    assert stop_child(client) is True


def test_sdk_failed_stop_retains_survivor_until_reaped():
    client=RpcClient()
    process=Process(unkillable=True)
    client._process=process
    assert stop_child(client) is False
    assert client._process is None  # Clearing this is NOT proof of safety.
    assert client.survivor_pids==(123,)
    assert stop_child(client) is False
    process.unkillable=False
    assert stop_child(client) is True
    assert process.poll() is not None and client.survivor_pids==()
