"""Reject undeclared, external Hermes and Capri-runtime dependencies."""
import ast
import importlib
import json
from pathlib import Path
import sys

VENDOR = Path(__file__).resolve().parents[3]/'src/capri/_vendor/hermes'

def test_all_imports_are_closed_and_classified():
    manifest = json.loads((VENDOR/'provenance.json').read_text(encoding='utf8'))
    mapped = set(manifest['import_map'].values())
    optional = set(manifest['optional_targets'])
    for path in VENDOR.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf8'))):
            if isinstance(node,ast.ImportFrom):
                assert node.level == 0, path
                names=[node.module] if node.module != 'capri._vendor.hermes.tools' else [node.module+'.'+a.name for a in node.names]
            elif isinstance(node,ast.Import): names=[a.name for a in node.names]
            else: continue
            for name in names:
                assert name.split('.')[0] in sys.stdlib_module_names or name in mapped or name.startswith('prompt_toolkit.'), (path,name)
                if name.startswith('capri.'):
                    assert name in mapped, (path,name)
                    if name not in optional: importlib.import_module(name)

def test_optional_subsystems_cannot_load_from_installed_hermes():
    manifest = json.loads((VENDOR/'provenance.json').read_text(encoding='utf8'))
    for target in manifest['optional_targets']:
        try: importlib.import_module(target)
        except ModuleNotFoundError as error:
            assert error.name.startswith('capri._vendor.hermes.compat._optional')
        else: raise AssertionError(target)
