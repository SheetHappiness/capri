"""Original hashes are verified by reversing every recorded relocation."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VENDOR = ROOT / 'src/capri/_vendor/hermes'

def test_pinned_provenance_and_mechanical_changes():
    manifest = json.loads((VENDOR/'provenance.json').read_text(encoding='utf8'))
    assert manifest['repository'] == 'https://github.com/NousResearch/hermes-agent'
    assert manifest['commit'] == 'ff294849385e433dd40a993b4f07673abb95c6f5'
    docs = (VENDOR/'UPSTREAM.md').read_text(encoding='utf8')
    assert manifest['repository'] in docs and manifest['commit'] in docs
    assert (VENDOR/'LICENSE').read_text(encoding='utf8')
    for row in manifest['files']:
        local = (VENDOR/row['local']).read_text(encoding='utf8')
        lines = local.splitlines(keepends=True)
        for change in reversed(row['changes']):
            assert change['category'] in {'IMPORT_REWRITE','COMPAT_REDIRECT'}
            start, end = change['local_range']
            assert lines[start:end] == change['local_lines']
            lines[start:end] = change['original_lines']
        restored = ''.join(lines)
        assert hashlib.sha256(restored.encode()).hexdigest() == row['sha256'], row['local']
        assert row['sha256'] in docs
        # The ten canonical modules may change only import names and relocated dotted strings.
        if row['local'].startswith('tools/'):
            normalized = local
            for old,new in sorted(manifest['import_map'].items(), key=lambda x:len(x[1]), reverse=True):
                normalized = normalized.replace(new, old)
            normalized = normalized.replace('from capri._vendor.hermes.tools import ', 'from tools import ')
            assert ast.dump(ast.parse(normalized)) == ast.dump(ast.parse(restored)), row['local']
    recorded = {r['local'] for r in manifest['files']}
    assert {str(p.relative_to(VENDOR)).replace('\\','/') for p in (VENDOR/'tools').glob('*.py') if p.name!='__init__.py'} <= recorded

def test_extracted_dependency_bodies_are_unchanged():
    manifest = json.loads((VENDOR/'provenance.json').read_text(encoding='utf8'))
    for excerpt in manifest['excerpts']:
        if 'local' not in excerpt:
            continue
        tree=ast.parse((VENDOR/excerpt['local']).read_text(encoding='utf8'))
        actual={n.name: n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        for name, body in excerpt['bodies'].items():
            node=actual[name]
            value=ast.unparse(node)
            for old,new in sorted(manifest['import_map'].items(),key=lambda x:len(x[1]),reverse=True):
                value=value.replace(new,old)
            value=value.replace('from capri._vendor.hermes.tools import ', 'from tools import ')
            assert ast.dump(ast.parse(value)) == ast.dump(ast.parse(body)), (excerpt['local'],name)
