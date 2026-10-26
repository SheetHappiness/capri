"""Verify the byte-preserved OMP snapshot without network access or build tools."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath


def safe_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (bool(name) and not path.is_absolute() and "\\" not in name
            and ":" not in name and all(part not in (".", "..", ".git") for part in path.parts)
            and path.as_posix() == name)


def generated(name: str) -> bool:
    """Ignore only known build/cache locations, never arbitrary source extensions."""
    parts = PurePosixPath(name).parts
    if any(p in {"node_modules", "__pycache__", ".pytest_cache", ".cache"}
           or p.endswith(".egg-info") for p in parts):
        return True
    prefixes = ("target/", ".xwin-cache/", "packages/natives/.build/",
                "packages/natives/npm/", "packages/coding-agent/binaries/",
                "sdk/python/omp-rpc/build/")
    if any(name == p.rstrip("/") or name.startswith(p) for p in prefixes):
        return True
    return (len(parts) >= 3 and parts[0] == "packages"
            and parts[2] in {"dist", "dist-chrome", "dist-firefox"})


def verify(root: Path, manifest: dict) -> list[str]:
    errors = []
    tree = root / "vendor/omp"
    files = manifest["files"]
    patches = manifest.get("patches", {})
    additions = manifest.get("additions", {})
    expected = dict(files)
    for name, patch in patches.items():
        if name not in files or files[name] != patch["original_sha256"]:
            errors.append(f"patch baseline mismatch: {name}")
        expected[name] = patch["current_sha256"]
    for name, sha in additions.items():
        if name in files:
            errors.append(f"addition shadows upstream: {name}")
        expected[name] = sha
    for name, sha in expected.items():
        if not safe_path(name):
            errors.append(f"unsafe manifest path: {name}")
            continue
        path = tree / name
        if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
            errors.append(f"symlink source: {name}")
        elif not path.is_file():
            errors.append(f"missing source: {name}")
        else:
            with path.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != sha:
                    errors.append(f"source hash mismatch: {name}")
    for directory, dirs, names in os.walk(tree):
        base = Path(directory).relative_to(tree)
        for name in list(dirs):
            relative = (base / name).as_posix()
            if name == ".git" or (Path(directory) / name).is_symlink():
                errors.append(f"nested repository or symlink: {relative}")
                dirs.remove(name)
            elif generated(relative):
                dirs.remove(name)
        for name in names:
            relative = (base / name).as_posix()
            if relative not in expected and (name == ".git" or not generated(relative)):
                errors.append(f"extra source: {relative}")
    for name, sha in manifest.get("records", {}).items():
        if not safe_path(name):
            errors.append(f"unsafe record path: {name}")
            continue
        path = root / "vendor" / name
        if not path.is_file() or path.is_symlink():
            errors.append(f"missing record: {name}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            errors.append(f"record hash mismatch: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        manifest = json.loads((root / "vendor/omp-source-manifest.json").read_text(encoding="utf-8"))
        if manifest["schema_version"] != 1:
            raise ValueError("unsupported manifest schema")
        errors = verify(root, manifest)
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"Vendor verification failed: {error}")
        return 1
    if errors:
        print("\n".join(errors))
        return 1
    print(f"OMP snapshot verified: {len(manifest['files'])} upstream files; "
          f"{len(manifest.get('patches', {}))} recorded patches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
