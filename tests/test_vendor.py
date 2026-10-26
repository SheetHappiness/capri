import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "45c35e40c46166dc726ccc52f5d27f40f2449f99"
ARCHIVE_HASH = "a8bbb85ede151ed58c100e84e6d239ca835937e04a51cd287049a9ff737fd4e2"


def verifier():
    path = ROOT / "scripts/verify-vendor.py"
    assert path.is_file(), "vendor verifier must exist"
    spec = importlib.util.spec_from_file_location("verify_vendor", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fixture(tmp_path):
    tree = tmp_path / "vendor/omp"
    tree.mkdir(parents=True)
    (tree / "source.txt").write_bytes(b"upstream\n")
    (tree / "bun.lock").write_bytes(b"locked\n")
    manifest = {
        "schema_version": 1,
        "upstream": {"commit": COMMIT, "archive_sha256": ARCHIVE_HASH},
        "files": {"source.txt": digest(b"upstream\n"), "bun.lock": digest(b"locked\n")},
        "patches": {}, "additions": {},
    }
    return tree, manifest


def test_small_pristine_fixture_is_valid(tmp_path):
    _, manifest = fixture(tmp_path)
    assert verifier().verify(tmp_path, manifest) == []


@pytest.mark.parametrize("change", ["altered", "missing", "extra", "nested_git", "unsafe_path"])
def test_verifier_rejects_unrecorded_changes(tmp_path, change):
    tree, manifest = fixture(tmp_path)
    if change == "altered":
        (tree / "source.txt").write_bytes(b"edited\n")
    elif change == "missing":
        (tree / "source.txt").unlink()
    elif change == "extra":
        (tree / "surprise.txt").write_text("extra")
    elif change == "nested_git":
        (tree / ".git").mkdir()
        (tree / ".git/config").write_text("nested repository")
    else:
        manifest["files"]["../outside"] = digest(b"outside")
    assert verifier().verify(tmp_path, manifest)


def test_patch_requires_original_and_current_hash(tmp_path):
    tree, manifest = fixture(tmp_path)
    (tree / "source.txt").write_bytes(b"patched\n")
    manifest["patches"]["source.txt"] = {
        "original_sha256": digest(b"upstream\n"), "current_sha256": digest(b"patched\n")}
    assert verifier().verify(tmp_path, manifest) == []
    manifest["patches"]["source.txt"]["original_sha256"] = digest(b"other upstream")
    assert verifier().verify(tmp_path, manifest)
    manifest["patches"]["source.txt"]["original_sha256"] = digest(b"upstream\n")
    (tree / "source.txt").write_bytes(b"patched again\n")
    assert verifier().verify(tmp_path, manifest)


def test_generated_sdk_and_build_outputs_do_not_change_source_provenance(tmp_path):
    tree, manifest = fixture(tmp_path)
    for name in ["node_modules/x/a.js", "target/debug/a.exe", "packages/natives/.build/a.node",
                 "sdk/python/omp-rpc/build/lib/omp_rpc/client.py",
                 "sdk/python/omp-rpc/src/omp_rpc.egg-info/PKG-INFO", "__pycache__/a.pyc"]:
        path = tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated")
    assert verifier().verify(tmp_path, manifest) == []


def test_snapshot_has_pinned_provenance_licenses_locks_and_complete_hashes():
    path = ROOT / "vendor/omp-source-manifest.json"
    assert path.is_file(), "pinned snapshot manifest must exist"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["upstream"]["commit"] == COMMIT
    assert manifest["upstream"]["archive_sha256"] == ARCHIVE_HASH
    for name in ["LICENSE", "THIRD-PARTY-NOTICES.txt", "bun.lock", "Cargo.lock",
                 "sdk/python/omp-rpc/LICENSE", "sdk/python/omp-rpc/src/omp_rpc/client.py",
                 "packages/natives/native/index.js"]:
        assert name in manifest["files"]
    assert any(p.startswith(".github/") for p in manifest["files"])
    assert len(manifest["files"]) == 9294
    assert verifier().verify(ROOT, manifest) == []
    result = subprocess.run([sys.executable, str(ROOT / "scripts/verify-vendor.py"),
                             "--root", str(ROOT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("path", [".runtime/agent/session.jsonl", ".venv/pyvenv.cfg",
    "vendor/omp/node_modules/pkg/index.js", "vendor/omp/target/debug/native.dll",
    "vendor/omp/packages/natives/.build/native.node", "vendor/omp/packages/ai/dist/index.js",
    "vendor/omp/packages/coding-agent/binaries/omp.exe", "vendor/omp/.cache/native.dll"])
def test_runtime_and_build_outputs_are_ignored(path):
    result = subprocess.run(["git", "check-ignore", "--no-index", "--", path], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, path


def test_all_upstream_sources_remain_visible_to_git():
    path = ROOT / "vendor/omp-source-manifest.json"
    assert path.is_file()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    paths = ["vendor/omp/" + p for p in manifest["files"]]
    result = subprocess.run(["git", "check-ignore", "--no-index", "--stdin", "-z"], cwd=ROOT,
                            input="\0".join(paths) + "\0", capture_output=True, text=True, timeout=30)
    assert result.returncode in (0, 1), result.stderr
    assert not result.stdout, result.stdout


def test_git_preserves_vendor_bytes_without_lfs_or_eol_conversion():
    paths = ["vendor/omp/scripts/install.cmd", "vendor/omp/sdk/python/omp-rpc/src/omp_rpc/client.py",
             "vendor/omp/bun.lock", "vendor/omp/assets/check.wasm",
             "vendor/omp/crates/pi-edit/tests/fixtures/apply_patch/scenarios/check.cmd"]
    result = subprocess.run(["git", "check-attr", "text", "filter", "--", *paths], cwd=ROOT,
                            capture_output=True, text=True, check=True)
    assert all(line.endswith(": unset") for line in result.stdout.splitlines()), result.stdout


def test_recorded_patch_bytes_survive_git_normalization():
    manifest = json.loads((ROOT / "vendor/omp-source-manifest.json").read_text(encoding="utf-8"))
    for name in manifest["records"]:
        path = "vendor/" + name
        raw = subprocess.run(["git", "hash-object", "--no-filters", path], cwd=ROOT,
                              capture_output=True, text=True, check=True)
        stored = subprocess.run(["git", "hash-object", "--path=" + path, path], cwd=ROOT,
                                 capture_output=True, text=True, check=True)
        assert raw.stdout == stored.stdout, f"Git normalization changes recorded bytes: {path}"
