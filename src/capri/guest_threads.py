"""Chat-scoped routing metadata; OMP alone owns guest transcripts."""
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
import re
import secrets
import time
from .config import write_json


class ThreadError(ValueError):
    pass


def normalize_title(title: str | None) -> str | None:
    if title is None:
        return None
    if not isinstance(title, str):
        raise ThreadError('Invalid guest title')
    return ' '.join(title.split())[:100].strip() or None


@dataclass(frozen=True)
class GuestThread:
    id: str
    chat_id: int
    title: str | None
    created_at: float
    updated_at: float


class GuestThreadStore:
    def __init__(self, data: Path):
        self.root = (data / 'guest').resolve()
        self.path = self.root / 'threads.json'
        self._threads = {}
        self._current = {}
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if set(raw) != {'threads', 'current'} or not isinstance(raw['threads'], list):
                raise ValueError
            for record in raw['threads']:
                thread = GuestThread(**record)
                self._validate(thread)
                if thread.id in self._threads: raise ValueError
                self._threads[thread.id] = thread
            for chat, thread_id in raw['current'].items():
                if str(int(chat)) != chat or self._threads[thread_id].chat_id != int(chat):
                    raise ValueError
                self._current[int(chat)] = thread_id
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
            raise ThreadError('Guest thread store unavailable') from None

    @staticmethod
    def _validate(thread):
        if (type(thread.chat_id) is not int or not isinstance(thread.id, str)
                or re.fullmatch(r'[0-9a-f]{12}', thread.id) is None
                or (thread.title is not None and not isinstance(thread.title, str))
                or any(type(t) not in (int, float) or not math.isfinite(t)
                       for t in (thread.created_at, thread.updated_at))):
            raise ThreadError('Invalid guest thread')

    def _save(self):
        write_json(self.path, {'threads': [asdict(t) for t in self._threads.values()],
                              'current': {str(k): v for k, v in self._current.items()}})

    def current(self, chat_id: int) -> GuestThread | None:
        return self._threads.get(self._current.get(chat_id))

    def ensure_current(self, chat_id: int) -> GuestThread:
        return self.current(chat_id) or self.new(chat_id)

    def new(self, chat_id: int, title: str | None = None) -> GuestThread:
        now = time.time()
        thread = GuestThread(secrets.token_hex(6), chat_id, normalize_title(title), now, now)
        self._validate(thread)
        self._threads[thread.id] = thread
        self._current[chat_id] = thread.id
        self._save()
        return thread

    def list(self, chat_id: int) -> tuple[GuestThread, ...]:
        current = self._current.get(chat_id)
        return tuple(sorted((t for t in self._threads.values() if t.chat_id == chat_id),
                            key=lambda t: (t.id == current, t.updated_at), reverse=True))

    def resume(self, chat_id: int, selector: str) -> GuestThread:
        threads = self.list(chat_id)
        exact = [t for t in threads if t.id == selector]
        matches = exact or [t for t in threads if t.id.startswith(selector)
                           or (t.title is not None and t.title.casefold() == selector.casefold())]
        if len(matches) != 1:
            raise ThreadError('Thread не знайдено або назва неоднозначна. Скористайся /threads та ID.')
        self._current[chat_id] = matches[0].id
        self._save()
        return matches[0]

    def rename_current(self, chat_id: int, title: str) -> GuestThread:
        thread = self.current(chat_id)
        if thread is None: raise ThreadError('Немає поточного thread. Скористайся /newthread.')
        title = normalize_title(title)
        if title is None: raise ThreadError('Вкажи назву: /title <назва>')
        updated = replace(thread, title=title, updated_at=time.time())
        self._threads[thread.id] = updated
        self._save()
        return updated

    def touch(self, chat_id: int):
        thread = self.current(chat_id)
        if thread is not None:
            self._threads[thread.id] = replace(thread, updated_at=time.time())
            self._save()

    def session_dir(self, thread: GuestThread) -> Path:
        self._validate(thread)
        root = (self.root / 'sessions').resolve()
        directory = (root / str(thread.chat_id) / thread.id).resolve()
        if not directory.is_relative_to(root): raise ThreadError('Invalid guest directory')
        return directory
