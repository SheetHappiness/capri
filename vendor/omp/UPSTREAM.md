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
current hash; `additions` covers this document and local tests. `records` hashes the patch files.

- APPLIED: `../omp-patches/0001-checkout-policy.patch` changes only Git checkout
  policy. Nested attributes disable CRLF conversion and LFS filtering, including
  in the apply-patch fixture directory. Ignore exceptions preserve upstream source
  files that upstream's own broad ignore rules would otherwise hide on import.
- APPLIED: `../omp-patches/0002-build-proof.patch` carries Task 1's baseline
  ISA override and Cargo `--locked` invocation into Task 4.
  `packages/natives/test/capri-build.test.ts` exercises an AVX2 host override,
  actual canonical addon installation/flags, and the N-API argv boundary.
- APPLIED: `../omp-patches/0003-state-isolation.patch` adds the absolute
  `CAPRI_OMP_ROOT` hook in `packages/utils/src/dirs.ts` and regression tests in
  `packages/utils/test/capri-dirs.test.ts`. Missing/blank overrides retain upstream
  behavior; nonempty relative or drive-relative paths fail before root writes.
  The explicit agent/session directory is preserved. Supported scope: Windows x64.

No dependency cleanup is part of this import. Task 3's root hook is the only
local runtime behavior change; without its environment override it is inactive.
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

Capri still uses its existing executable path. Task 3 adds private source/runtime
environment paths but does not rebuild, replace or restart the running bot.
The old executable lacks the root hook. Task 4 Step 2 adds a candidate-only build wrapper: verified snapshot copy,
pinned toolchain, native build and staged exe. It does not smoke-test, promote
or switch the runtime. Compiled isolation acceptance and the clean-machine
negative-dependency CI gate remain later tasks.
