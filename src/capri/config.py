"""Local pairing and the verified OMP configuration."""
import json
from pathlib import Path
import secrets

DISCOVERY_PROVIDERS = ['agent-plugins', 'agents', 'agents-md', 'claude', 'claude-md',
    'claude-plugins', 'cline', 'codex', 'cursor', 'custom-context', 'gemini',
    'github', 'mcp-json', 'native', 'omp-plugins', 'opencode', 'skillshare',
    'ssh-json', 'vscode', 'windsurf']
OMP_CONFIG = {'modelRoles': {'web': 'openai-codex/gpt-6-luna'},
              'mcp': {'enableProjectConfig': False},
              'tools': {'approvalMode': 'write'},
              'find': {'enabled': 'on'},
              # Exact commands only: wildcard flags can enable writes or helpers.
              'bash': {'patterns': [
                  {'match': command, 'approval': 'allow'} for command in (
                      'git status', 'git diff', 'git log', 'git show',
                      'python --version', 'node --version')]},
              'disabledProviders': DISCOVERY_PROVIDERS}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


class Pairing:
    def __init__(self, path: Path):
        self.path = path
        self.owner_id = json.loads(path.read_text(encoding='utf-8'))['owner_id'] if path.exists() else None
        self.nonce = secrets.token_urlsafe(24) if self.owner_id is None else None

    def accept(self, user_id: int, text: str) -> bool:
        if self.owner_id is not None or not self.nonce:
            return False
        if not secrets.compare_digest(text.encode('utf-8'), ('/start ' + self.nonce).encode('utf-8')):
            return False
        write_json(self.path, {'owner_id': user_id})
        self.owner_id = user_id
        self.nonce = None
        return True

