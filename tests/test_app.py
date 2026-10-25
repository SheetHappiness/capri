import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from capri.config import Pairing
from capri.app import handle_text

def test_owner_pairing_gate_and_group_rejection(tmp_path):
    async def run():
        pairing=Pairing(tmp_path/'owner.json'); bot=NS(send_message=AsyncMock())
        engine=NS(stream=lambda _: (_ for _ in ()))
        lock=asyncio.Lock()
        def msg(user,text,kind='private'):
            return NS(chat=NS(id=user,type=kind),from_user=NS(id=user),text=text)
        await handle_text(msg(5,'/start '+pairing.nonce,'group'),bot,engine,pairing,lock)
        assert pairing.owner_id is None
        await handle_text(msg(5,'hi'),bot,engine,pairing,lock)
        assert pairing.owner_id is None
        await handle_text(msg(7,'/start '+pairing.nonce),bot,engine,pairing,lock)
        assert pairing.owner_id==7
        bot.send_message.reset_mock()
        await handle_text(msg(5,'private question'),bot,engine,pairing,lock)
        bot.send_message.assert_not_called()
    asyncio.run(run())
