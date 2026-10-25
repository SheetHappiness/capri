"""Incremental public-text protocol. The exact token is reserved outside code."""


class BubbleProtocol:
    TOKEN = '<bubble>'

    def __init__(self):
        self._pending = ''
        self._indent = 0
        self._fence = None
        self._closing = False
        self._inline = 0

    def feed(self, delta: str) -> list[str | None]:
        self._pending += delta
        return self._drain(final=False)

    def finish(self) -> list[str | None]:
        return self._drain(final=True)

    def _advance(self, text):
        for char in text:
            if char == '\n':
                if self._closing:
                    self._fence = None
                self._closing = False
                self._indent = 0
            elif self._indent is not None and char == ' ':
                self._indent += 1
            else:
                self._indent = None
                if char not in ' \t\r':
                    self._closing = False

    def _drain(self, *, final):
        events = []

        def emit(text):
            if text:
                if events and isinstance(events[-1], str):
                    events[-1] += text
                else:
                    events.append(text)

        text = self._pending
        index = 0
        while index < len(text):
            char = text[index]
            if char in '`~':
                end = index + 1
                while end < len(text) and text[end] == char:
                    end += 1
                if end == len(text) and not final:
                    break  # A delimiter run may continue in the next delta.
                run = end - index
                at_start = self._indent is not None and self._indent <= 3
                closing = (self._fence is not None and at_start
                           and char == self._fence[0] and run >= self._fence[1])
                if self._fence is None:
                    if not self._inline and at_start and run >= 3:
                        self._fence = (char, run)
                    elif char == '`':
                        if not self._inline:
                            self._inline = run
                        elif self._inline == run:
                            self._inline = 0
                piece = text[index:end]
                emit(piece)
                self._advance(piece)
                self._closing = closing
                index = end
                continue
            if char == '<' and self._fence is None and not self._inline:
                rest = text[index:]
                if rest.startswith(self.TOKEN):
                    events.append(None)
                    index += len(self.TOKEN)
                    continue
                if self.TOKEN.startswith(rest):
                    if final:
                        index = len(text)  # Discard a reserved, unfinished token.
                    break
            emit(char)
            self._advance(char)
            index += 1
        self._pending = text[index:]
        return events
