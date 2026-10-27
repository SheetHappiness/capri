# Windows OMP source-build proof

Date: 2026-10-27 (Europe/Warsaw).
Scope: Task 1 only, as an isolated throwaway OMP build; no Capri integration.
Status: Task 1 standalone Windows build proof PASS. Task 2 and Task 3 results
are recorded below, followed by Task 4 Step 2 candidate-only build evidence.
Smoke/promotion/runtime switch, bootstrap and clean CI remain pending.
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

Task 2/3 results are recorded below; Tasks 4–6 remain pending. Task 6 must independently prove a
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

## Task 3 — private runtime state (2026-10-27)

Scope: shared child environment, vendored source root hook, launcher regressions
and auth-free **source** acceptance. No executable promotion, bot restart, model
prompt, credential copy or session migration. The build-proof patch remains
**NOT APPLIED**. Existing `.runtime/omp.exe` lacks the root hook, so these results
must not be described as compiled-runtime or live Telegram acceptance.

### Paths and write audit

`data` is resolved at the Python call site. Directories are created before spawn;
creation errors propagate. Only child overrides are returned; the parent env and
real HOME/USERPROFILE are preserved. Owner, Guest and config get/set use this same
builder. Profiles are explicitly empty and `PI_CONFIG_DIR=.capri-omp` is retained
for old-executable compatibility. A nonblank CAPRI_OMP_ROOT is trimmed and must
be fully qualified; Windows drive-relative/root-relative paths are rejected.

| Managed state / trigger | Owning source / resolver | Target and evidence |
|---|---|---|
| Profile-independent root and install identity | utils `dirs.ts`, `getBaseConfigRoot`, `getInstallId` | `CAPRI_OMP_ROOT=<data>/omp-root`; UUID actually persisted in fresh source child |
| Auth/settings DB, models DB, history, sessions | dirs `getAgentDbPath`, `getModelDbPath`, `getHistoryDbPath`, `getSessionsDir` | `PI_CODING_AGENT_DIR=<data>/agent`; fresh config/RPC startup created DBs, owner session path verified; no authenticated access exercised |
| Owner pointer and Guest sessions | Capri engines / guest threads | Existing `session.json`, `agent/sessions`, `guest/sessions/<chat>/<thread>` retained; fake launch/resume/privacy tests |
| Logs and stats | dirs `getLogsDir`, `getStatsDbPath` | `<data>/omp-root/logs`, `<data>/omp-root/stats.db`; log marker and source startup writes; Bun-test log fallback stays under private TEMP |
| Daemons, global services, session ownership | dirs `getDaemonRuntimeRoot`, `getGlobalDaemonRuntimeRoot`, `getSessionOwnersDir` | `<data>/omp-root/run/...`; resolver assertions and auth-free startup; no separate daemon feature acceptance |
| Native extraction | natives `loader-state.js`, `initLoaderContext`; dirs `getNativesDir` | `PI_NATIVES_DIR=<data>/cache/natives`; real resolver plus write marker. Source uses prepared same-pin addon; **new compiled extraction pending**. LOCALAPPDATA/omp is a loader search candidate, metadata unchanged |
| Temp, worker sockets and stderr capture | utils `temp.ts`; subprocess `worker-client.ts`; worker-host smoke | `TEMP=TMP=<data>/tmp`; source worker smoke passed for short/Unicode paths. Long worker socket fails explicitly; no global fallback |
| Plugins / marketplaces and managed JS environments | `extensibility/plugins/{manager,bun-cli,bun-git-cache}.ts`, `eval/js/package-installer.ts` | Resolver targets under root/plugins or agent/cache/eval-js; Bun subprocesses inherit env. Added `BUN_INSTALL_CACHE_DIR=<data>/cache/bun` after audit found default home cache. Actual `bun pm cache` resolves there; registry/git install and lifecycle scripts **static-only** |
| Bun runtime transpiler cache | Bun 1.4.4 source execution and dynamic TS imports | `BUN_RUNTIME_TRANSPILER_CACHE_PATH=<data>/cache/transpiler`; conflicting inherited override reproduced by reviewer and fixed. Final probe executes cacheable local TS and asserts a real private `.pile` file. Parent probe cache must be disabled **before invocation** |
| Transformers, fastembed, browser, grammars, model downloads | utils `runtime-install.ts`, dirs `getTinyWorkerRuntimeDir`, `getFastembedRuntimeDir`, `getPuppeteerDir`, `getNativeGrammarsDir`, `getTinyModelsCacheDir` | Managed destinations under root or agent cache, Bun installer inherits private cache. Downloads and optional packages **static-only**, not exercised |
| Python managed venv/gateway | dirs `getPythonEnvDir`, `getPythonGatewayDir`; `eval/py/runtime.ts` | root/python-env, agent/python-gateway; resolver evidence only. External uv/pip installers and their own caches are outside this runtime-only acceptance |
| Runtime update | main `checkForNewVersion`, `cli/update-cli.ts`, `cli/build-service.ts` | Source checkout skips binary update check; startup check is a notification path, executable update is explicit CLI. No update command or download run. Compiled check/install paths require Task 4/5 review and acceptance |
| Marketplace refresh | main `scheduleMarketplaceAutoUpdate`, plugins `marketplace-auto-update.ts` | Root/agent registry/cache helpers; fresh source startup has no installed marketplaces. Network updates with existing registries **static-only** |
| Discovery / project-generated files | `config.ts`, discovery helpers, dirs project helpers | Capri's existing disabled providers/flags retained. HOME/.env and discovery may be read; project tool writes and explicit user-selected external paths are not a filesystem sandbox |

The additional Bun cache overrides are audit-driven extensions to the plan's
initial environment table; it uses Bun's existing supported override rather than
patching installers. No lockfile/dependency source or capability policy changed.
Build/Cargo caches belong to Task 4, not this runtime environment builder.

### Source harness and reproducible commands

Bun **1.4.4 (38afee6c8)** and prepared native addon from the same pinned source
were reused from Task 1. The addon SHA-256 is
`b415765948e79603ce877a671830eaf6caec80a34c234b38f8bbc85717171371`;
it was staged beside the ignored portable Bun executable, a supported native
loader candidate, without placing a binary in tracked source. This is source
harness preparation, not a new build or a clean-machine proof.

From `vendor/omp`, with the pinned Bun on PATH **for this shell only**:

```powershell
# Disable the parent Bun transpiler cache before it parses the generator/probe.
# OMP children receive a separate prepared private cache from omp_environment.
$env:BUN_RUNTIME_TRANSPILER_CACHE_PATH = '0'
# BUN_INSTALL_CACHE_DIR and BUN_TMPDIR must point at ignored local scratch dirs.
bun install --frozen-lockfile --ignore-scripts
bun packages/collab-web/scripts/build-tool-views.ts
bun test packages/utils/test/capri-dirs.test.ts packages/utils/test/dirs.test.ts packages/utils/test/profiles.test.ts packages/utils/test/install-id.test.ts packages/utils/test/natives-dir-override.test.ts
bun ../../scripts/probe-omp-isolation.ts <absolute-unused-short-path-below-checkout-.runtime>
```

The generator creates one ignored `tool-views.generated.js` needed for raw-source
CLI imports (normally root install `prepare`). It is a temporary harness asset,
not part of the pinned snapshot; remove it after source probes before running
source provenance verification. No Task 4 build wrapper or build patch is needed.
The probe uses `.venv/Scripts/python.exe` and Capri's actual environment builder,
then installs that env before importing OMP in a fresh child. It rejects relative
paths, the active agent tree, nonempty scratch roots and junction escapes. Logs
remain ignored inside disposable data; only summarized booleans are printed.
It submits **no prompt**. RPC requests `get_state`, checks model/session location,
closes stdin and confirms the child's exit code; timed-out/forced exits fail.

The exact portable Bun used here is at
`.runtime/vendor-spike/tools/bun/bun-windows-x64-baseline/bun.exe`.
Final source probes use `.runtime/p3f` and `.runtime/Проба дані 4` as new roots;
private summaries/logs stay there and in `.runtime/task3`.

| Case | Observed result |
|---|---|
| Shared environment RED/GREEN | 8 initial failures, then 11 PASS; cache extension separately 7 failures, then 11 PASS |
| New root-hook RED/GREEN | 8 assertion failures before hook; 11 new tests PASS after hook |
| Focused new/upstream Bun tests | 44 PASS, 0 fail across 5 files |
| Owner / Guest / permission get+set boundary | 42 PASS; inherited conflicting roots/profiles/temp/cache overridden before fake start |
| Source config CLI, short and Unicode/space roots | PASS; JSON key/value validated |
| Source worker `--smoke-test`, short and Unicode/space roots | PASS, exit 0 |
| Auth-free source RPC, both roots | PASS, exact openai-codex/gpt-6-luna, session under private agent/sessions, stdin-close exit 0 |
| Install ID, native/log/temp writes, Bun install-cache resolver and runtime transpiler `.pile` | PASS from fresh source child |
| Home-directory metadata snapshots | Unchanged for `.omp`, `.capri-omp`, LOCALAPPDATA/omp in both passing probes |
| Long data root (100-character leaf suffix) | Expected limitation reproduced: worker exit 1 with ENAMETOOLONG; config and RPC still passed, child exit confirmed; overall probe correctly exits 1 |

Observation is limited to recursive size/mtime/mode inventories of the three
known directories, without reading their contents. No process file-write tracer
was available/used. Snapshots cannot exclude transient writes or writes at an
unlisted location; they are evidence of these runs, not an exhaustive syscall
audit. Optional downloads/installers, auth, arbitrary tools and compiled runtime
remain explicitly untested. Use a short checkout/data path on Windows; do not
silently redirect long private TEMP into global temp.

Bun install required execution outside the Windows sandbox after local-temp
EBADF. Python async tests also needed execution outside the sandbox because pipe
setup stalls before test bodies (same Task 2 limitation); no product workaround
was introduced. Python tests use repository-local `--basetemp`.

Final automated verification: **271 passed, 1 opt-in skipped** in 81.67s; the
skipped fresh-venv/offline install test was then enabled separately with the
existing Task 2 wheelhouse and **passed** in 24.88s (**272 distinct tests passed**).
The verifier passed for 9,294 original source files / four patched originals.
`git apply --reverse --check` passed for applied patch 0003;
`git apply --check` passed for unapplied build patch 0002; `git diff --check`
passed. Lockfiles, build-proof source files, toolchain manifest and executable
were unchanged. Probe refusal checks for relative/active/nonempty data all
returned exit 1 with their expected guard message.

Independent final review found one Important issue and no Critical/Minor issues:
an inherited `BUN_RUNTIME_TRANSPILER_CACHE_PATH` escaped the private data root.
The pinned Bun reproduced a real `.pile` outside private data. Seven regression
assertions failed before the fix, then all 11 environment tests passed. Capri now
prepares `<data>/cache/transpiler` and overrides that variable for every launcher.
The final source probe additionally executes cacheable local TypeScript and
observes a private `.pile`. The parent Bun invocation disables its cache before
entry; setting env inside the probe would be too late for its own transpilation.
Both passing source cases and the expected long-socket failure were repeated
after the fix. Final focused Bun tests: **44 passed, 0 failed**.
No second review was dispatched; the single fix pass uses RED/GREEN and the full
suite. Compiled/runtime promotion, auth/live acceptance, external installers and
non-Windows XDG remain the explicitly documented deferred scope.

Final verification after the review fix, with the offline install test enabled
in the same full run: **272 passed in 30.82s, no skips**. Source verifier,
applied/unapplied patch applicability checks and whitespace checks passed again.

Staged whitespace validation excludes unified-diff patch records, matching the
Task 2 convention: their required context prefix produces false positives for
blank lines and tab indentation. All implementation/docs/tests pass
`git diff --cached --check -- . ':!vendor/omp-patches/*.patch'`; patch bytes are
instead hash-verified and checked for applicability, without rewriting context.

## Task 4 Step 2 — candidate-only build (2026-10-27)

Scope: build a Windows x64 candidate from the verified vendored snapshot.
**No compiled CLI/RPC smoke, executable promotion, bootstrap, runtime switch,
credential copy, session migration, Telegram calls or bot restart.** Task 4 is
still incomplete: Steps 3–4 must smoke-test and promote a verified artifact.

### Implementation and regression evidence

- Applied the existing byte-preserved `0002-build-proof.patch`: forced baseline
  host detection and N-API's Cargo `-- --locked`. Recorded both original/current
  hashes, registered the regression test addition, and removed deferred status.
- Three new Bun tests first failed on the intended assertions, then passed.
  The tests force an AVX2 host in a fresh child, run the real native build driver
  against a fake N-API compiler output, and assert actual canonical installation,
  Rust flags and captured argv. They do not rely on source-text matching.
- `scripts/build-runtime.ps1` verifies Python/local SDK origin and the exact
  installed toolchain; initializes installed VS when needed; creates a unique
  manifest-only source copy; uses frozen Bun install with scripts disabled;
  builds native then Windows x64 executable; validates fresh outputs and source/
  lock hashes; stages only `bin/omp.<run-id>.candidate.exe`. A per-Data OS file
  lock protects shared build caches. Parent cwd/env, including missing versus
  empty env keys, are restored even with dot-sourcing and failure.
- Cargo/Bun cache, target and temp are private under Data. Source copy excludes
  unlisted generated outputs. A narrow verifier extension recognizes the two
  canonical Windows x64 generated addons; `unexpected.node` remains rejected.
  Original manifest files are still hash-checked before generated-file handling.
- Review found inherited compiler/wrapper/target selectors could bypass the
  checked compiler. A poisoned-environment test reproduced RED; clearing those
  overrides and pinning `CARGO_BUILD_TARGET=x86_64-pc-windows-msvc` made it GREEN.
  VS batch-path quoting also has RED/GREEN coverage. VS environment capture is
  used in memory and omitted from logs, with a private-value regression check.
- Independent scoped read-only review finished with no remaining Critical,
  Important or Minor findings. Review does not certify deferred runtime paths.

### Reproduction and real candidate builds

Prerequisites are preinstalled, not downloaded by the script. The prepared
portable Bun and Rust toolchain from Task 1 were supplied as installed tools;
their location is not hardcoded in production. Neither Task 1's OMP executable
nor its native addon/build outputs were used as candidate inputs.

From the checkout root in PowerShell 7:

```powershell
$env:RUSTUP_HOME = Join-Path (Get-Location) '.runtime/vendor-spike/tools/rustup'
$env:PATH = (Join-Path (Get-Location) '.runtime/vendor-spike/tools/bun/bun-windows-x64-baseline') + ';' + (Join-Path (Get-Location) '.runtime/vendor-spike/tools/cargo/bin') + ';' + $env:PATH
./scripts/build-runtime.ps1 -Data .runtime/t4s2
```

The first build used fresh private dependency/target caches. The second run used
a separate verified snapshot and the same private caches, and exercised the
final script after the review's compiler-selector/environment-log fixes.
Registry dependencies are permitted; no OMP source/release/native leaf download
is a substitute for the native/exe build.

After the second build, the new Bun test harness alone was refactored to follow
the nested OMP instructions: isolated `spyOn`, top-level imports and async Bun
I/O. Its three failures were reproduced again with patch 0002 temporarily
removed, then the patch was restored and all 47 focused Bun tests passed. No
production source/recipe changed after the second build. Build records retain
their original source-manifest hashes; reconstructing those manifests from the
retained run snapshots confirms that only the test addition's hash differs from
the final manifest. No historical build provenance was rewritten.

| Run | Executable bytes | SHA-256 |
|---|---:|---|
| `141de497254c` | 243018240 | `fd97f6e4ec10a2fc84b89bfc6c519248b6125449f30cab4ab31ba88148cdafd3` |
| `55aac4f29f3c` | 243018240 | `da3fa9bc6abafd478c70f397e759170e83afc99445f89729b8119c8f7cb31727` |

Latest native addon SHA-256: `bf01b257d5a5869a70c8c534edfd8636369220b51f20ca43646300112612cf16`.
Each staged exe hash was independently recomputed and matched its build record.
Both unique candidates remain present. `.runtime/t4s2/bin/omp.exe` and
`runtime-build.json` were absent afterward; there was no promotion. Synthetic
auth/session/owner/Guest/config sentinel preservation is covered by the script
tests, including successful candidate builds and failures.

The exact toolchain remains Bun 1.4.4/revision 38afee6c8, Rust nightly-2026-10-06,
MSVC toolset 14.44.35207/compiler 19.44.35229, Windows SDK 10.0.26100.0,
CMake 4.4.4 and Ninja 1.12.1. Native uses profile ci, baseline/x86-64-v2,
static CRT, eight Cargo jobs and locked dependencies. Per-run candidate records
contain source/archive/manifest/patch/lock hashes, tool versions and artifact
hashes; `runtime-toolchain.json` retains its historical Task 1 proof unchanged.

The first native build finished in 5m40s and emitted LNK4217 warnings for
Wasmtime/tree-sitter imports, the same warning family recorded in Task 1.
Build success and native driver's own addon load probe are build evidence;
the staged OMP executable has not been launched or smoke-tested here. Fresh
source copies and cached builds are not bit-for-bit reproducibility or
clean-machine/negative-dependency proof. Paths with spaces/Unicode are covered
by stubbed script tests; real compiled worker long-path behavior remains Step 3.

### Final automated verification

```powershell
$env:PYTHONUTF8 = '1'
$env:CAPRI_INSTALL_WHEELHOUSE = Join-Path (Get-Location) '.runtime/vendor-spike/task2-wheelhouse'
.venv/Scripts/python -m pytest -q --tb=short --basetemp=.runtime/t4s2-suite-final
```

Result: **300 passed, 6 expected future-step RED, no skips/warnings**, 154.57s.
The offline local-SDK install test was enabled. Existing Step 1 contracts were
retained rather than weakened to make a candidate-only pipeline appear complete.
The six expected RED cases are:

- `test_failed_stage_preserves_runtime_and_state[fail_smoke-expected_stages4]`
- `test_failed_stage_preserves_runtime_and_state[smoke_timeout-expected_stages5]`
- `test_build_overrides_inherited_flags_and_caches` (final full-stage assertion;
  all build environment assertions run first)
- `test_paths_and_caller_state[invoke-success]`
- `test_paths_and_caller_state[dot-source-success]`
- `test_build_command_contract`

All six still require the omitted smoke stage; the complete pipeline success
contract also requires later promotion. Dedicated Step 2 tests independently
verify candidate staging, fresh/unique repeated runs, hostile inherited flags,
relative/Unicode/space paths, VS setup and unchanged sentinel state.

New native regressions plus the existing five isolation test files: **47 Bun
tests passed, 0 failures**. Source verifier passed for 9,294 original source
files and six recorded patched originals; reverse application check for 0002,
whitespace checks and `pip check` passed. `git ls-files .runtime .venv` was empty.
No bootstrap or production smoke script was created. Changes remain uncommitted.
