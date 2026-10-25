import pytest

from capri.bubble_protocol import BubbleProtocol


def parse(parts):
    parser = BubbleProtocol()
    events = []
    for part in parts:
        events.extend(parser.feed(part))
    events.extend(parser.finish())
    return events


def visible(events):
    return ''.join(e for e in events if e is not None)


def test_short_bubbles():
    assert BubbleProtocol().feed('Привіт<bubble>Як справи?') == ['Привіт', None, 'Як справи?']


@pytest.mark.parametrize('split', range(9))
def test_every_marker_split(split):
    marker = '<bubble>'
    events = parse(['Hi' + marker[:split], marker[split:] + 'Bye'])
    assert visible(events) == 'HiBye'
    assert events.count(None) == 1


def test_character_stream():
    events = parse(list('Hi<bubble>Bye<bubble>'))
    assert visible(events) == 'HiBye'
    assert events.count(None) == 2


def test_incomplete_candidate():
    parser = BubbleProtocol()
    assert parser.feed('Привіт<bu') == ['Привіт']
    assert parser.finish() == []
    assert visible(parse(['<bu', 'tton>'])) == '<button>'


def test_empty_boundaries():
    assert parse(['<bubble><bubble>']) == [None, None]


@pytest.mark.parametrize('code', [
    '```python\n<bubble>\n```\n',
    '~~~text\n<bubble>\n~~~\n',
    '```\n<bubble>',
    '  ````python\n```\n<bubble>\n````\n',
    '`<bubble>`',
    '``a `<bubble>` b``',
])
def test_literal_code(code):
    for parts in ([code], list(code)):
        events = parse(parts)
        assert visible(events) == code
        assert None not in events


@pytest.mark.parametrize('code', ['```\n<bubble>\n```\n', '~~~\n<bubble>\n~~~\n', '`<bubble>`'])
def test_code_then_boundary_at_every_split(code):
    source = code + '<bubble>Tail'
    for split in range(len(source) + 1):
        events = parse([source[:split], source[split:]])
        assert visible(events) == code + 'Tail'
        assert events.count(None) == 1


def test_exact_token():
    assert visible(parse(['< bubble > <BUBBLE>'])) == '< bubble > <BUBBLE>'
