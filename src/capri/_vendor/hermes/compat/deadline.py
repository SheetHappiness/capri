"""Exact upstream platform-safe wait cap, without deadline execution."""
import sys

_WINDOWS_MAX_WAIT_S = (0xFFFFFFFF - 1000) / 1000.0

MAX_SAFE_TIMEOUT_S = (
    _WINDOWS_MAX_WAIT_S if sys.platform == "win32" else 31_536_000.0
)
