from omp_rpc import MessageUpdateEvent, ToolExecutionStartEvent, ToolExecutionUpdateEvent, ToolExecutionEndEvent

from capri.activity import TurnActivity


def thought(text):
    return MessageUpdateEvent(message={'role': 'assistant'},
        assistant_message_event={'type': 'thinking_delta', 'delta': text})


def result(text):
    return {'content': [{'type': 'text', 'text': text}, {'type': 'image', 'data': 'opaque-image'}],
            'details': {'private': 'opaque-details'}}


def test_activity_tracks_thinking_parallel_calls_snapshots_and_errors():
    state = TurnActivity()
    assert state.render() == ''
    state.update(thought('Checking '))
    state.update(thought('files'))
    state.update(ToolExecutionStartEvent(tool_call_id='a', tool_name='read', args={'path': 'note.md'}))
    state.update(ToolExecutionStartEvent(tool_call_id='b', tool_name='bash', args={'command': 'pytest'}))
    state.update(ToolExecutionUpdateEvent(tool_call_id='b', tool_name='bash', partial_result=result('12')))
    state.update(ToolExecutionUpdateEvent(tool_call_id='b', tool_name='bash', partial_result=result('12 passed')))
    state.update(ToolExecutionEndEvent(tool_call_id='a', tool_name='read', result=result('missing'), is_error=True))
    state.update(ToolExecutionEndEvent(tool_call_id='b', tool_name='bash', result=result('12 passed'), is_error=False))
    state.finish('done')
    rendered = state.render()
    assert rendered.startswith('Checking files\n\n')
    assert 'OMP activity' not in rendered and '💭' not in rendered
    assert '✗ read' in rendered and 'note.md' in rendered and 'missing' in rendered
    assert '✓ bash' in rendered and 'pytest' in rendered
    assert rendered.count('12 passed') == 1 and '\n  12\n' not in rendered
    assert rendered.endswith('✓ done')
    assert 'opaque' not in rendered


def test_activity_is_bounded_and_keeps_recent_activity_and_status():
    state = TurnActivity()
    state.update(thought('😀' * 10000))
    for number in range(100):
        state.update(ToolExecutionStartEvent(tool_call_id=str(number), tool_name='write',
            args={'path': f'{number}.txt', 'content': 'x' * 10000}))
        state.update(ToolExecutionEndEvent(tool_call_id=str(number), tool_name='write',
            result=result('😀' * 10000), is_error=False))
    state.finish('failed')
    rendered = state.render()
    assert len(rendered.encode('utf-16-le')) // 2 <= 4096
    assert '99.txt' in rendered and '0.txt' not in rendered
    assert rendered.endswith('✗ failed')
    assert '…' in rendered


def test_large_write_arguments_do_not_hide_the_file_path():
    state = TurnActivity()
    state.update(ToolExecutionStartEvent(tool_call_id='w', tool_name='write',
        args={'content': 'x' * 10000, 'path': 'notes/important.md'}))
    assert 'notes/important.md' in state.render()


def test_thinking_emphasis_is_plain_text_without_changing_code_or_tool_data():
    state = TurnActivity()
    state.update(thought('**Preparing '))
    state.update(thought('shutdown request**\n__Checking__ `a ** b`'))
    state.update(ToolExecutionStartEvent(tool_call_id='a', tool_name='bash',
        args={'command': 'echo "**literal**"'}))
    state.update(ToolExecutionEndEvent(tool_call_id='a', tool_name='bash',
        result=result('**literal output**'), is_error=False))
    rendered = state.render()
    assert rendered.startswith('Preparing shutdown request\nChecking `a ** b`\n\n')
    assert '**literal**' in rendered and '**literal output**' in rendered
    assert state.thinking.startswith('**Preparing shutdown request**')
