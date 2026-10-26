# Vendored OMP provenance

- Repository: https://github.com/can1357/oh-my-pi
- Version: 18.12.6
- Commit: `45c35e40c46166dc726ccc52f5d27f40f2449f99`
- Source archive: https://codeload.github.com/can1357/oh-my-pi/zip/45c35e40c46166dc726ccc52f5d27f40f2449f99
- Archive SHA-256: `a8bbb85ede151ed58c100e84e6d239ca835937e04a51cd287049a9ff737fd4e2`
- Imported on: 2026-10-27
- Import: all 9294 regular files from the verified archive, including dotfiles,
  fixtures, SDKs, workspace build metadata, original lockfiles and license/notices.
  No nested Git checkout, installed packages, compiled artifacts or private state.

## Local differences

`../omp-source-manifest.json` records the SHA-256 of every original archive file.
Its `patches` records bind each applied modification to both its original and
current hash; `additions` covers this document. `records` hashes the patch files.

- APPLIED: `../omp-patches/0001-checkout-policy.patch` changes only Git checkout
  policy. Nested attributes disable CRLF conversion and LFS filtering, including
  in the apply-patch fixture directory. Ignore exceptions preserve upstream source
  files that upstream's own broad ignore rules would otherwise hide on import.
- NOT APPLIED: `../omp-patches/0002-build-proof.patch` preserves Task 1's baseline
  ISA override and Cargo `--locked` changes for Task 4. The actual build scripts
  here remain byte-identical to upstream until their regression tests are added.

No dependency cleanup or runtime behavior changes are part of this import.
The original `LICENSE`, `THIRD-PARTY-NOTICES.txt`, SDK licenses and all other
license/notice files remain in place. The source archive's LFS pointer files,
if present, remain exactly as archived; this import does not fetch LFS objects.

## Verify and install

From the Capri checkout root (Python 3.14):

```powershell
python scripts/verify-vendor.py --root .
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-runtime.txt
# Development / CI:
.venv/Scripts/python -m pip install -r requirements-test.txt
.venv/Scripts/python -m pip check
```

The requirements explicitly select `./vendor/omp/sdk/python/omp-rpc` before
resolving Capri's `omp-rpc==0.1.0`. Installing Capri alone with `pip install -e .`
does not establish SDK provenance and is not the supported installation path.
Do not substitute an arbitrary package-index distribution of the same version.
Third-party Python dependencies/build backends can still need registry access.

Capri still uses its existing executable path in Task 2. This source import does
not rebuild, replace or launch the running bot/runtime. Build wrappers, local
state paths and a clean-machine negative-dependency CI gate are later tasks.
