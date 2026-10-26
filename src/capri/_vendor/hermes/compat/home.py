"""Home identity only; no directory creation, config loading or profile discovery."""
import os
from pathlib import Path

def get_hermes_home_override():
    return None

def get_hermes_home():
    return Path(os.getenv('HERMES_HOME') or '~/.hermes').expanduser()

def hermes_home_key(path=None):
    return os.path.normcase(str((Path(path) if path is not None else get_hermes_home()).expanduser().resolve()))
