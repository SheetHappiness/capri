# Windows OMP source-build proof

Date: 2026-10-27 (Europe/Warsaw).
Scope: Task 1 only, as an isolated throwaway OMP build; no Capri integration.
Status: Task 1 standalone Windows build proof PASS. Tasks 2–6 remain unstarted.
Exact observed versions, source/patch/lock hashes and artifact metadata are in
[`runtime-toolchain.json`](../../runtime-toolchain.json).

## Source and isolation

- Exact baseline: OMP 18.12.6, `45c35e40c46166dc726ccc52f5d27f40f2449f99`.
- Existing source ZIP verified before extraction: SHA-256
  `a8bbb85ede151ed58c100e84e6d239ca835937e04a51cd287049a9ff737fd4e2`.
- Full source extracted to ignored `.runtime/vendor-spike/candidate/`.
  Python extraction needed Windows extended paths for long archive paths.
- Bun frozen install passed; Cargo `fetch --locked --target x86_64-pc-windows-msvc`
  passed. Both lockfile hashes matched the original archive afterward.
- All 16 installed `@oh-my-pi/*` workspace packages resolve to local source.
  Neither lockfile contains an upstream `oh-my-pi` Git source dependency.
- A global OMP exists on this workstation. This is not a clean-machine/Task 6
  negative dependency PASS. The executable smoke explicitly removes global OMP,
  Bun and Cargo from its child PATH and uses a new private root/native cache.
- The SDK is installed from this candidate's `sdk/python/omp-rpc` into a scratch
  venv. Capri's working Python environment, runtime executable, session pointers,
  prompts and bot process are not switched by this proof.

## Prerequisites prepared

- Portable Bun 1.4.4 (`38afee6c8`) under the ignored proof directory.
  Baseline ZIP SHA-256:
  `0f20ce6674d4f2dbcc8c5d59fdf99f7ba45f8c3b367e0f5781cbfa30a1c78d99`;
  matched the official GitHub release asset digest.
- Local Rust `nightly-2026-10-06`, rustc 1.101.0-nightly
  (`ea137335b`, 2026-10-05), Cargo 1.101.0-nightly (`f3865b2a4`, 2026-09-29).
  Rustup/Cargo roots are under the proof directory; global PATH was not changed.
- The original VS Build Tools instance contained only MSBuild components.
  With explicit user approval of UAC, added Microsoft's C++ x64 tools,
  Windows SDK 26100 and CMake/Ninja; installer exit code 0, no reboot requested.
- MSVC toolset directory 14.44.35207; compiler reports 19.44.35229 for x64.
  Windows SDK 10.0.26100.0; system CMake 4.4.4; VS Ninja 1.12.1.

## Build recipe and scratch-only adjustments

Working directory: extracted OMP root. Build tools are explicitly prepended to
the build process PATH; their global installation/linking is not used for OMP.

```powershell
bun install --frozen-lockfile
cargo fetch --locked --target x86_64-pc-windows-msvc
bun run build:native
bun scripts/ci-release-build-binaries.ts --targets win32-x64
```

Native build uses profile `ci`, 8 Cargo jobs, explicit
`RUSTFLAGS=-C target-feature=+crt-static -C target-cpu=x86-64-v2`.
`CARGO_ENCODED_RUSTFLAGS` must be absent, not empty. In this PowerShell runtime,
`[Environment]::SetEnvironmentVariable(name, $null, 'Process')` left an empty
variable. `Remove-Item Env:CARGO_ENCODED_RUSTFLAGS` removed it; a Bun subprocess
confirmed absence, and completed Cargo fingerprints confirmed the intended flags.
The two attempts with empty flags were stopped and were not accepted.
The corrected build started with a new empty target directory.

The only two changed original source files are:

1. `scripts/host-detect.ts`: honor `PI_NATIVE_VARIANT=baseline` in the shared
   AVX2 helper so both the native builder and host load probe select baseline.
2. `packages/natives/scripts/build-bindings.ts`: forward `-- --locked` to
   N-API's Cargo bypass arguments.

```diff
 export function detectHostAvx2Support(): boolean {
+    if (process.env.PI_NATIVE_VARIANT === "baseline") return false;
```

Immediately before `const buildResult = await $...` in the native build runner:

```typescript
napiArgs.push("--", "--locked");
```

The first baseline override was placed only in the child builder, making our
patched wrapper look for a nonexistent modern addon. Direct baseline load passed;
moving the override to the shared helper fixed the wrapper too. This was a defect
in the spike patch, not evidence of a broken upstream native binary.

Exact patch and throwaway launchers are kept under `.runtime/vendor-spike/`.
These are proof artifacts, not the production build/bootstrap implementation.
The four commands above assume the launchers' full environment setup, including
`OMP_NATIVE_BUILD_BACKEND=cargo`, tool/cache roots, baseline flags and short TEMP.
To reproduce the prepared spike on this workstation, use these retained launchers:

```powershell
& .runtime/vendor-spike/build-native.ps1
& .runtime/vendor-spike/build-binary.ps1
.runtime/vendor-spike/venv/Scripts/python.exe .runtime/vendor-spike/smoke.py
```

The last command performs the authorized two small live Codex prompts using
isolated credential copies. These ignored launchers do not exist in a fresh clone;
tracked production bootstrap/build tooling belongs to Task 4.

## Results

| Check | Result |
|---|---|
| Native Rust/C++ compilation | PASS; cold compilation completed in 6m18s |
| Corrected native host wrapper | PASS; version stamp and direct load probe, exit 0 |
| Source audit against verified ZIP | PASS; zero original files missing; only the two build-source edits above |
| Binary compilation | PASS; 60 seconds; 243,021,824 bytes |
| `--version` | PASS; `omp/18.12.6` |
| `--help` | PASS; exit 0 |
| Worker `--smoke-test` | PASS; exit 0 with short repo-local TEMP |
| Auth-free RPC `get_state` | PASS; exact `openai-codex/gpt-6-luna`, session inside test root |
| Minimal model prompt | PASS; completed with exact `PROOF_RPC_OK` |
| Native tool through compiled RPC | PASS; actual `grep` end event, `is_error=false`, fixture marker present; exact `PROOF_NATIVE_OK` answer |
| Embedded native extraction | PASS; new cache contains `18.12.6/pi_natives.win32-x64-baseline.node` |
| SDK teardown | PASS; `stop()` returned exactly `True` for both clients |
| Child PATH | PASS; neither global OMP nor Bun was discoverable |
| Existing Capri state | PASS; owner pointer, pairing and permission-config hashes unchanged |

Executable SHA-256:
`8cd72e5ccef44dc052143a61e92c012b509a8f621a6216397c871183d2670ec8`.
Extracted embedded native addon SHA-256:
`b415765948e79603ce877a671830eaf6caec80a34c234b38f8bbc85717171371`.

The first worker smoke failed with `ENAMETOOLONG`: its Unix socket path was
inside the verbose per-run state/TEMP directory. Repeating in a new empty test
state with TEMP/TMP set to the shorter `.runtime/vendor-spike/tmp` passed without
any runtime source change. The production wrapper must keep this socket-path
constraint explicit; arbitrary long checkout paths are not proven here.

Live prompt auth copied active Codex credential rows only, from the existing
read-only agent DB into a fresh test DB after auth-free initialization. The new DB
had zero credentials before this copy. No owner settings, other providers,
transcripts or session pointers were copied. Credentials/raw outputs stay ignored.
This authenticated prompt is separate from credential-free CI lifecycle smoke.

The native linker emitted LNK4217 warnings for Wasmtime/tree-sitter symbols.
Loading, worker smoke and native grep passed; broader native feature coverage and
clean-machine portability are not certified by these checks.

Private evidence and throwaway code: `.runtime/vendor-spike/{progress.md,
build-only.patch,build-native.ps1,build-binary.ps1,smoke.py,native-build.log,
native-build-result.json,binary-build.log,binary-build-result.json,smoke-result.json,
source-changes.json,verified-rustflags.json}`. No production artifact was replaced.

## Later acceptance

Task 2 results are recorded below; Tasks 3–6 remain pending. Task 6 must independently prove a
fresh Capri checkout with no global OMP, no pre-existing `~/.omp`, no upstream
OMP GitHub downloads and no cached vendored build, followed by bootstrap, build,
tests and local RPC smoke. Normal registry dependency downloads remain allowed.

No `soul.md` or personality changes are included.

Independent read-only evidence review found no Critical/Important findings.
Two minor clarifications were addressed: reproduction explicitly names the prepared
launchers, and the throwaway Python process now aligns its own environment before
SDK construction, preventing the SDK's env overlay from restoring omitted keys.
The final smoke was rerun after this environment correction.

## Task 2 — pinned snapshot and local SDK (2026-10-27)

Scope: source import and Python installation only. Capri's executable selection,
session paths and running processes were not switched. No OMP rebuild or Telegram
acceptance was performed in this task.

- Imported all **9,294 files / 213,019,275 bytes** from the same hash-verified
  source archive into `vendor/omp`, including dotfiles, all SDKs, workspace metadata,
  tokenizer assets, original licenses/notices and unchanged lockfiles.
- `vendor/omp-source-manifest.json` records original per-file SHA-256 hashes,
  91 executable source file modes, current hashes for three checkout-policy
  modifications, the added `UPSTREAM.md`, and separately hashed patch records.
- Applied only `vendor/omp-patches/0001-checkout-policy.patch`: byte preservation
  and disabled Git LFS filtering in both upstream attribute files, plus exceptions
  for ten upstream tokenizer files hidden by the original tools ignore rule.
  Git verifies every original source file is visible to the index.
- Task 1's baseline/Cargo changes are recorded as
  `vendor/omp-patches/0002-build-proof.patch`, with LF line endings, **unapplied**.
  Their actual source files remain pristine until Task 4 adds build tests.
- `requirements-runtime.txt` explicitly selects the local SDK and editable Capri;
  `requirements-test.txt` includes it. Python metadata now requires
  `omp-rpc==0.1.0` without an upstream source URL. README/AGENTS installation
  instructions were updated at the same time to avoid a stale install route.

Verification:

```powershell
.venv/Scripts/python scripts/verify-vendor.py --root .
.venv/Scripts/python -m pip install --no-index --find-links .runtime/vendor-spike/task2-wheelhouse -r requirements-test.txt
.venv/Scripts/python -m pip check
$env:CAPRI_INSTALL_WHEELHOUSE = (Resolve-Path .runtime/vendor-spike/task2-wheelhouse).Path
.venv/Scripts/python -X utf8 -m pytest -q --basetemp=.runtime/task2-acceptance
```

The third-party wheelhouse was prepared from the pinned Python requirements and
setuptools; it contains no OMP SDK wheel. The opt-in install test first confirms
that `omp-rpc==0.1.0` cannot resolve from this offline wheelhouse, then installs
through the supported requirements in a fresh venv from a checkout path containing
spaces and Cyrillic characters. The installed SDK's `direct_url.json` points to
that checkout's `vendor/omp/sdk/python/omp-rpc`, and `pip check` passes.
The main development venv's SDK origin was also checked against this local source.

Baseline: **242 passed**. First full acceptance: **263 passed**, including the
offline fresh-venv install. A subsequent Git normalization regression test caught
CRLF in the copied proof patch; its text was normalized to LF and its record hash
updated. Final acceptance after that correction: **264 passed in 31.48s**, with
the offline install test enabled, no skips. Source verifier and `pip check` pass.
Both patch records pass `git apply --check` against their declared state
(checkout policy applied/reversible, build proof unapplied/applicable).

Independent read-only review found no Critical/Important issues or deferred
minors. The final index audit confirms every source blob matches its recorded
hash, all 91 upstream executable modes are preserved, the full source set is
present, and no runtime/build/private source files have entered the index.
`git ls-files .runtime .venv` is empty. Whitespace checks cover Capri changes;
pristine upstream files and unified-diff records are excluded, while patch
applicability and hashes are checked separately.

Implementation choices: the three checkout-policy changes prevent byte drift
or hidden source on Windows; regression tests gate both failure modes. Updating
installation documentation in this task avoids sending users to the old SDK
download route; Task 6 still needs to document its later bootstrap interface.
The final review's deferred scope (Tasks 3–6, runtime build/promotion/state paths,
executable switching and live acceptance) remains intentionally unimplemented.
Full upstream correctness is inherited from the pinned source, not audited here.

Sandbox limitation: Python's Windows asyncio pipe setup stalls inside this
sandbox before async test bodies. The unchanged baseline and acceptance suite
were therefore run outside the sandbox. No product workaround was added.
