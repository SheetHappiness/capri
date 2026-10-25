"""Small append-only public-text chunker inspired by OpenClaw's block streaming."""
import re


class BubbleComposer:
    def __init__(self, min_chars=140, soft_max=800):
        if not 1 <= min_chars <= soft_max <= 4096:
            raise ValueError('Require 1 <= min_chars <= soft_max <= 4096')
        self.min_chars = min_chars
        self.soft_max = soft_max
        self.pending = ''

    def append(self, delta):
        self.pending += delta

    def boundary(self):
        """Return a safe source boundary; never consume before the send succeeds.

        An indivisible span (including oversized code) retains Phase 1's visible
        truncation fallback at final delivery rather than cutting a code fence.
        """
        text = self.pending
        if len(text) < self.soft_max:
            return None
        fences = []
        opened = None
        offset = 0
        for line in text.splitlines(keepends=True):
            match = re.match(r' {0,3}(`{3,}|~{3,})(.*)', line)
            if match:
                marker, rest = match.groups()
                if opened is None:
                    opened = (offset, marker)
                elif marker[0] == opened[1][0] and len(marker) >= len(opened[1]) and not rest.strip():
                    fences.append((opened[0], offset + len(line)))
                    opened = None
            offset += len(line)
        if opened:
            fences.append((opened[0], len(text) + 1))

        def safe(index):
            return (self.min_chars <= index <= 4096
                    and len(text[:index].encode('utf-16-le')) // 2 <= 4096
                    and not any(start < index < end for start, end in fences))

        paragraphs = [m.end() for m in re.finditer(r'\n[ \t]*\n', text) if safe(m.end())]
        if paragraphs:
            return next((i for i in paragraphs if i >= self.soft_max), paragraphs[-1])
        for pattern in (r'[.!?…]["\x27»”)]*\s+', r'\s+'):
            candidates = [m.end() for m in re.finditer(pattern, text) if safe(m.end())]
            if candidates:
                return next((i for i in candidates if i >= self.soft_max), candidates[-1])
        return None
