import asyncio
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from capri.app import OmpRuntime, handle_text
from capri.config import OMP_CONFIG, Pairing
from capri.engine import Engine, EngineError
from test_engine import SDK


def test_native_permission_cli_and_saved_config_survive_start(tmp_path, monkeypatch, assert_private_omp_environment):
    config = tmp_path/'agent/config.yml'
    config.parent.mkdir()
    original = 'tools:\n  approvalMode: write\nstartup:\n  quiet: true\n'
    config.write_text(original)
    calls = []
    saved = 'write'

    def run_cli(argv, **kw):
        nonlocal saved
        assert_private_omp_environment(kw['env'], tmp_path, merged=True)
        assert kw['env']['NO_COLOR'] == '1'
        calls.append((argv, kw))
        assert argv[:4] == [str((tmp_path/'omp.exe').resolve()), 'config', argv[2], 'tools.approvalMode']
        if argv[2] == 'set':
            saved = argv[4]
        return NS(stdout=json.dumps({'key': 'tools.approvalMode', 'value': saved}), returncode=0)

    monkeypatch.setattr(subprocess, 'run', run_cli)
    async def run():
        engine = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=SDK)
        await engine.start()
        try:
            assert config.read_text() == original
            args = engine.client.kw['extra_args']
            overlay = Path(args[args.index('--config') + 1])
            assert json.loads(overlay.read_text()) == OMP_CONFIG
            assert await engine.permission() == 'write'
            assert await engine.permission('always-ask') == 'always-ask'
            assert [argv[2] for argv, _ in calls] == ['get', 'set', 'get']
            for argv, kw in calls:
                assert argv[-1] == '--json'
                assert kw['cwd'] == tmp_path/'work'
                assert kw['env']['PI_CODING_AGENT_DIR'] == str(tmp_path/'agent')
                assert kw['env']['PI_CONFIG_DIR'] == '.capri-omp'
                assert kw['env']['OMP_PROFILE'] == kw['env']['PI_PROFILE'] == ''
                assert kw['timeout'] <= 30 and not kw.get('shell')
            with pytest.raises(ValueError):
                await engine.permission('write; dangerous')
            assert len(calls) == 3
        finally:
            await engine.close()
        resumed = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=SDK)
        await resumed.start()
        assert config.read_text() == original
        await resumed.close()
    asyncio.run(run())


@pytest.mark.parametrize('outcome', ['error', 'timeout', 'malformed', 'overridden'])
def test_native_permission_failure_is_safe(tmp_path, monkeypatch, outcome):
    def run_cli(*args, **kwargs):
        if outcome == 'error':
            raise subprocess.CalledProcessError(1, 'omp', stderr='private credential')
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired('omp', 15, stderr='private credential')
        return NS(stdout='private credential' if outcome == 'malformed' else
                  json.dumps({'key': 'tools.approvalMode', 'value': 'yolo', 'overriddenBy': 'project'}),
                  returncode=0)
    monkeypatch.setattr(subprocess, 'run', run_cli)
    async def run():
        engine = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=SDK)
        with pytest.raises(EngineError) as error:
            await engine.permission('write')
        assert 'private' not in str(error.value)
    asyncio.run(run())


def test_runtime_permission_reaps_idle_owner_and_refuses_busy_turn():
    async def run():
        client = NS(stop=lambda: True)
        owner = NS(client=client, safe=True, permission=AsyncMock(return_value='write'))
        runtime = OmpRuntime(owner, NS(safe=True))
        async with runtime.lock:
            with pytest.raises(EngineError):
                await runtime.permission('write')
        owner.permission.assert_not_called()
        assert await runtime.permission() == 'write'
        assert runtime.owner_ready and owner.client is client
        assert await runtime.permission('write') == 'write'
        assert not runtime.owner_ready and owner.client is None and runtime.safe
    asyncio.run(run())


def test_runtime_permission_unconfirmed_teardown_blocks_next_turn():
    async def run():
        owner = NS(client=NS(stop=lambda: False), safe=True, permission=AsyncMock(return_value='write'))
        runtime = OmpRuntime(owner, NS(safe=True))
        with pytest.raises(EngineError):
            await runtime.permission('write')
        assert not runtime.safe
        with pytest.raises(EngineError):
            await runtime.permission()
    asyncio.run(run())


def test_cancelled_permission_joins_native_save_before_unlock(tmp_path, monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    actions = []
    def run_cli(argv, **kw):
        actions.append(argv[2])
        entered.set()
        assert release.wait(2)
        return NS(stdout=json.dumps({'key': 'tools.approvalMode', 'value': 'write'}), returncode=0)
    monkeypatch.setattr(subprocess, 'run', run_cli)
    async def run():
        owner = Engine(tmp_path/'omp.exe', tmp_path, sdk_factory=SDK)
        await owner.start()
        client = owner.client
        runtime = OmpRuntime(owner, NS(safe=True))
        task = asyncio.create_task(runtime.permission('write'))
        assert await asyncio.to_thread(entered.wait, 1)
        try:
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0.005)
            assert runtime.lock.locked() and not task.done()
            assert client.stopped and not runtime.owner_ready
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert actions == ['set', 'get'] and runtime.safe
        assert not runtime.lock.locked() and owner.client is None
    asyncio.run(run())


@pytest.mark.parametrize('command', ['/permission', '/permissions'])
def test_permission_command_bypasses_model_and_is_owner_only(tmp_path, command):
    async def run():
        pairing = Pairing(tmp_path/'owner.json')
        pairing.accept(7, '/start ' + pairing.nonce)
        bot = NS(send_message=AsyncMock())
        runtime = NS(permission=AsyncMock(return_value='write'))
        flow = NS(submit=lambda *args: pytest.fail('permission must not enter model/steering'))
        def message(user=7, text=command, kind='private'):
            return NS(chat=NS(id=user, type=kind), from_user=NS(id=user), text=text)
        for user, kind in ((8, 'private'), (7, 'group')):
            await handle_text(message(user=user, kind=kind), bot, runtime, pairing, flow)
        runtime.permission.assert_not_called()
        await handle_text(message(), bot, runtime, pairing, flow)
        runtime.permission.assert_awaited_once_with(None)
        menu = bot.send_message.call_args.kwargs
        assert 'write' in menu['text'] and menu['parse_mode'] is None
        buttons = [button for row in menu['reply_markup'].inline_keyboard for button in row]
        assert {button.callback_data for button in buttons} == {
            'permission:yolo', 'permission:write', 'permission:always-ask', 'permission:always-ask-cached'}
        await handle_text(message(text=command + ' yolo'), bot, runtime, pairing, flow)
        assert runtime.permission.await_args.args == ('yolo',)
        calls = runtime.permission.await_count
        await handle_text(message(text=command + ' garbage'), bot, runtime, pairing, flow)
        assert runtime.permission.await_count == calls
    asyncio.run(run())


def test_permission_callback_checks_owner_and_private_chat(tmp_path):
    from capri.permission import handle_permission_callback
    async def run():
        pairing = Pairing(tmp_path/'owner.json')
        pairing.accept(7, '/start ' + pairing.nonce)
        bot = NS(answer_callback_query=AsyncMock(), edit_message_text=AsyncMock(), send_message=AsyncMock())
        runtime = NS(permission=AsyncMock(return_value='always-ask'))
        def callback(user=7, kind='private', data='permission:always-ask'):
            return NS(id='query', data=data, from_user=NS(id=user),
                      message=NS(chat=NS(id=7, type=kind), message_id=13))
        for query in (callback(user=8), callback(kind='group'), callback(data='permission:bogus')):
            await handle_permission_callback(query, bot, runtime, pairing)
        runtime.permission.assert_not_called()
        await handle_permission_callback(callback(), bot, runtime, pairing)
        runtime.permission.assert_awaited_once_with('always-ask')
        assert bot.edit_message_text.call_args.kwargs['message_id'] == 13
        bot.send_message.assert_not_called()
    asyncio.run(run())


def test_polling_shutdown_joins_permission_handler_before_closing(tmp_path, monkeypatch):
    import capri.app as app
    from capri.config import write_json
    from aiogram import Dispatcher

    async def run():
        write_json(tmp_path/'owner.json', {'owner_id': 7})
        entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        closed = []
        class Owner:
            client = NS(stop=lambda: True)
            safe = True
            async def start(self): pass
            async def permission(self, mode):
                entered.set()
                await release.wait()
                finished.set()
                return 'write'
            async def close(self):
                closed.append(finished.is_set())
        owner = Owner()
        bot = NS(get_me=AsyncMock(return_value=NS(username='Capriompbot', supports_guest_queries=False)),
                 send_message=AsyncMock(), session=NS(close=AsyncMock()))
        handler_tasks = []
        async def poll(self, actual_bot, **kw):
            handler = self.sub_routers[0].message.handlers[0].callback
            msg = NS(chat=NS(id=7, type='private'), from_user=NS(id=7), text='/permission write')
            handler_tasks.append(asyncio.create_task(handler(msg)))
            await entered.wait()
            # aiogram's polling shutdown leaves detached update handlers alive.
        monkeypatch.setattr(app, 'Engine', lambda *args: owner)
        monkeypatch.setattr(app, 'Bot', lambda *args: bot)
        monkeypatch.setattr(Dispatcher, 'start_polling', poll)
        task = asyncio.create_task(app.run('123:TEST', tmp_path/'omp.exe', tmp_path))
        await asyncio.wait_for(entered.wait(), 1)
        try:
            await asyncio.sleep(0.01)
            assert not closed and not task.done()
            bot.session.close.assert_not_awaited()
        finally:
            release.set()
        await task
        assert closed == [True]
        assert all(handler.done() for handler in handler_tasks)
        bot.send_message.assert_not_awaited()
        bot.session.close.assert_awaited_once()
    asyncio.run(run())
