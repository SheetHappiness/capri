"""Dormancy, import isolation and unchanged effective capabilities."""
import ast
import importlib
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULES = ['approval', 'approval_context', 'approval_detection', 'approval_floors', 'approval_prompt', 'approval_gateway_wait', 'approval_human_wait', 'approval_smart', 'clarify_gateway', 'interrupt']

@pytest.mark.parametrize('name', MODULES)
def test_core_is_importable(name):
    importlib.import_module('capri._vendor.hermes.tools.' + name)

def test_no_runtime_dependency_in_either_direction():
    root = ROOT / 'src/capri'
    for path in root.rglob('*.py'):
        vendor = '_vendor' in path.relative_to(root).parts
        for node in ast.walk(ast.parse(path.read_text(encoding='utf8'))):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or '']
                if node.level and not vendor:
                    names += [a.name for a in node.names]
            elif isinstance(node, ast.Import): names = [a.name for a in node.names]
            else: continue
            if vendor:
                assert all(not n.startswith('capri.') or n.startswith('capri._vendor.hermes') for n in names), path
            else:
                assert all('_vendor' not in n for n in names), path

def test_runtime_import_does_not_load_vendor():
    code = "import capri.app,capri.cli,capri.guest_engine,sys; assert not any(n.startswith('capri._vendor.hermes') for n in sys.modules)"
    subprocess.run([sys.executable, '-c', code], check=True, cwd=ROOT)

def test_core_imports_are_offline_and_do_not_write(tmp_path):
    code = """
import sys
def audit(event, args):
    if event in {'socket.connect','subprocess.Popen','os.mkdir','os.rename','os.remove'}:
        raise AssertionError((event,args))
    if event == 'open' and isinstance(args[1],str) and any(c in args[1] for c in 'wax+'):
        raise AssertionError((event,args))
sys.addaudithook(audit)
import importlib
for name in %r:
    importlib.import_module('capri._vendor.hermes.tools.'+name)
""" % MODULES
    subprocess.run([sys.executable, '-B', '-c', code], check=True, cwd=ROOT)
