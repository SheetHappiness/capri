"""Bounded public Guest progress; no reasoning or tool payloads enter this view."""
from .bubble_protocol import BubbleProtocol
from .telegram import _TRUNCATED


class ProgressView:
    frames = ('·', '··', '···', '··', '·')

    def __init__(self):
        self.progress_text = ''
        self.current_text = ''
        self.final_text = ''
        self.completed = False
        self.protocol = BubbleProtocol()
        self.frame = 0

    @staticmethod
    def clean(text):
        protocol = BubbleProtocol()
        parts = protocol.feed(text) + protocol.finish()
        return ''.join('\n\n' if p is None else p for p in parts).replace('<bubble>', '').strip()[:8192]

    def accept(self, event):
        if event.kind == 'start':
            self.current_text = ''
            self.protocol = BubbleProtocol()
        elif event.kind == 'text':
            for part in self.protocol.feed(event.text):
                self.current_text = (self.current_text + ('\n\n' if part is None else part))[:8192]
        elif event.kind == 'message':
            self.current_text = self.clean(event.text)
        elif event.kind == 'tool_start':
            if self.current_text.strip():
                self.progress_text = '\n\n'.join(filter(None,
                    (self.progress_text, self.current_text.strip())))[-8192:]
            self.current_text = ''
            self.protocol = BubbleProtocol()
        elif event.kind == 'final':
            self.final_text = self.clean(event.text)
            self.completed = True

    def render(self):
        current = self.current_text.strip()
        progress = self.progress_text
        # Older commentary must not consume the preview budget of new tokens.
        if current and progress:
            remaining = max(0, 4092-len(current.encode('utf-16-le'))//2-2)
            if len(progress.encode('utf-16-le'))//2 > remaining:
                marker = '[…]'
                if remaining > len(marker):
                    progress = marker + progress.encode('utf-16-le')[-(remaining-len(marker))*2:].decode('utf-16-le',errors='ignore')
                else:
                    progress = ''
        text = '\n\n'.join(filter(None,(progress,current)))
        suffix = self.frames[self.frame % len(self.frames)]
        self.frame += 1
        text = text.replace('<bubble>', '')
        # Reserve space for the longest suffix even when progress is truncated.
        if len(text.encode('utf-16-le'))//2 > 4092:
            budget = 4092 - len(_TRUNCATED.encode('utf-16-le'))//2
            text = text.encode('utf-16-le')[:budget*2].decode('utf-16-le',errors='ignore') + _TRUNCATED
        return (text + ' ' + suffix).strip()

    @property
    def has_text(self):
        return bool(self.progress_text.strip() or self.current_text.strip())
