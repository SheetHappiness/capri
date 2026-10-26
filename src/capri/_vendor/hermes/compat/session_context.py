"""Environment fallback with no gateway/session runtime."""
import os

def get_session_env(name, default=None):
    return os.getenv(name, default)
