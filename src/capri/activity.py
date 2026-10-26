"""Bounded owner-only display of native OMP events, with no tool execution."""
from collections import OrderedDict
from dataclasses import dataclass
import json
import re

from omp_rpc import (
    RpcAgentEvent,
    MessageUpdateEvent, ToolExecutionStartEvent, ToolExecutionUpdateEvent,
    ToolExecutionEndEvent, ToolStreamUpdateEvent,
)


def _clip(text: str, units: int) -> str:
    encoded = text.encode('utf-16-le')
    if len(encoded) <= units * 2:
        return text
    return encoded[:(units - 1) * 2].decode('utf-16-le', errors='ignore') + '…'


def _text(result) -> str:
    if not isinstance(result, dict):
        return ''
    # Binary content, signatures and opaque provider/tool details are not UI.
    parts = []
    for block in result.get('content', []) or []:
        if isinstance(block, dict) and block.get('type') == 'text' and isinstance(block.get('text'), str):
            parts.append(_clip(block['text'], 500))
            if sum(len(part) for part in parts) >= 500:
                break
    return _clip('\n'.join(parts), 500)


def _plain_thinking(text: str) -> str:
    # Preserve literal code while removing prose emphasis, including an opening
    # marker whose matching end has not arrived in the stream yet.
    parts = re.split(r'(```[\s\S]*?(?:```|$)|`[^`\n]*(?:`|$))', text)
    return ''.join(part if index % 2 else part.replace('**', '').replace('__', '')
                   for index, part in enumerate(parts))


@dataclass
class _Tool:
    name: str
    args: str = ''
    output: str = ''
    status: str = '▸'


class TurnActivity:
    """Keep a recent window; tool updates replace snapshots, not append them."""
    def __init__(self):
        self.thinking = ''
        self._thinking_key = None
        self._thinking_block = ''
        self.tools: OrderedDict[str, _Tool] = OrderedDict()
        self.omitted = False
        self.status = ''

    def update(self, event: RpcAgentEvent) -> None:
        if isinstance(event, MessageUpdateEvent):
            update = event.assistant_message_event
            kind = update.get('type')
            key = (event.message_id, update.get('contentIndex'))
            if kind == 'thinking_start' or key != self._thinking_key:
                self._thinking_block = ''
                self._thinking_key = key
            if kind == 'thinking_delta' and isinstance(update.get('delta'), str):
                self._thinking_block = _clip(self._thinking_block + update['delta'], 500)
            elif kind == 'thinking_end' and isinstance(update.get('content'), str):
                self._thinking_block = _clip(update['content'], 500)
            self.thinking = self._thinking_block
            return
        if not isinstance(event, (ToolExecutionStartEvent, ToolExecutionUpdateEvent,
                                  ToolExecutionEndEvent, ToolStreamUpdateEvent)):
            return
        tool = self.tools.get(event.tool_call_id)
        if tool is None:
            tool = self.tools[event.tool_call_id] = _Tool(_clip(event.tool_name, 64))
            if len(self.tools) > 4:
                self.tools.popitem(last=False)
                self.omitted = True
        args = getattr(event, 'args', None)
        if args is not None:
            if isinstance(args, dict):
                # Keep the action target visible even when a large write/edit
                # payload was serialized before its path by the provider.
                targets = {key: args[key] for key in ('path', 'command', 'query', 'pattern') if key in args}
                args = targets | args
            tool.args = _clip(json.dumps(args, ensure_ascii=False), 250)
        if isinstance(event, ToolExecutionUpdateEvent):
            tool.output = _text(event.partial_result)
        elif isinstance(event, ToolExecutionEndEvent):
            tool.output = _text(event.result) or tool.output
            tool.status = '✗' if event.is_error else '✓'
        elif isinstance(event, ToolStreamUpdateEvent) and isinstance(event.update, dict):
            # The pinned edit stream exposes file previews. Display paths and
            # diagnostics; the authoritative text result follows at tool end.
            files = event.update.get('files')
            if isinstance(files, list):
                tool.output = _clip('\n'.join(
                    str(file.get('path', '')) + (': ' + file['error'] if file.get('error') else '')
                    for file in files if isinstance(file, dict)), 500)

    def finish(self, status: str) -> None:
        self.status = status

    def render(self) -> str:
        if not self.thinking and not self.tools:
            return ''
        sections = []
        if self.thinking:
            sections.append(_plain_thinking(self.thinking))
        if self.omitted:
            sections.append('… earlier activity omitted')
        for tool in self.tools.values():
            lines = [f'{tool.status} {tool.name}']
            if tool.args:
                lines.append('  ' + tool.args)
            if tool.output:
                lines.append('  ' + tool.output)
            sections.append(_clip('\n'.join(lines), 850))
        if self.status:
            sections.append(('✓' if self.status == 'done' else '✗') + ' ' + self.status)
        return '\n\n'.join(sections)
