"""Inert terminal-batch boundary; Port 01 has no terminal executor."""
def consume_prepared_guard(command, env_type, has_host_access=False):
    return None

def preparing_terminal_approval():
    return False

def register_prepared_approval(session_key, entry):
    return None

def approval_published():
    return None
