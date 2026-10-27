# Minimal pre-PR SDK provenance fix — Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. Approved for execution on 2026-10-27 with the samefile and read_text(None) corrections below.

**Goal:** Refuse normal Capri CLI startup with an SDK installed from outside this checkout, and bring vendored provenance documentation up to date before opening the PR.

**Architecture:** Keep the existing local requirements and bootstrap flow. Add a small, read-only Python metadata guard at the CLI boundary, before importing SDK-dependent application modules or reading credentials. Update documentation and its recorded hash together. No OMP source or native build changes.

**Tech Stack:** Windows x64, Python 3.14, importlib.metadata, pathlib, pytest, existing PowerShell bootstrap and GitHub Actions.

**Spec:** User request of 2026-10-27 and the referenced conversation `6ae11284-97e0-83eb-a38a-721ef0746af5`: startup SDK provenance guard + stale UPSTREAM.md, then PR CI; native-build CI remains follow-up work. Current inspected base: `ca57099`, branch `codex/vendor-omp-snapshot`.

## Global Constraints

- Do not change OMP snapshot, patches, locks, model configuration, session behavior, or dependency declarations.
- Preserve owner/guest capability isolation and the Telegram-only guest probe.
- Never read or print credentials for provenance diagnostics. No network, automatic installation, or runtime restart in the guard.
- Resolve checkout from the Capri source file location, never current working directory or `--data`.
- A relocated checkout requires reinstalling its SDK through the supported requirements command; no bypass flag.
- This verifies installation metadata, not resistance to a malicious environment or forged metadata.
- GPT-6 Astra is prohibited for subagents. No delegation is needed for this fix.

## Review Focus

1. SDK metadata absent, unreadable, malformed, or wrong JSON shape: controlled rejection.
2. Same-version registry, archive, VCS, or another-checkout install: controlled rejection.
3. Windows file URLs with spaces, Unicode, and equivalent resolved paths: accepted when they designate this checkout's SDK directory.
4. Startup from another working directory or custom `--data`/`--omp`: cannot change expected SDK origin.
5. Guard failure: no bot-token read, Telegram startup, or OMP child; `--help` and guest probe preserve their existing behavior.

## Task 1: Guard normal CLI startup

**Files:** Create `src/capri/sdk_provenance.py`, `tests/test_sdk_provenance.py`; modify `src/capri/cli.py`, `tests/test_cli.py`, `tests/test_install.py`, `README.md`.

**Interfaces:** `SdkProvenanceError(RuntimeError)` and `verify_sdk_provenance() -> None`. The helper uses `importlib.metadata.distribution('omp-rpc')`; the CLI converts its error to `parser.error(...)` (exit 2).

- [ ] Write helper tests with mocked distribution metadata and isolated SDK directories. Name the cases `test_accepts_checkout_sdk`, `test_rejects_invalid_sdk_metadata`, `test_rejects_other_sdk_origins`, and `test_origin_is_independent_of_working_directory`. Parameterize missing distribution/file, invalid JSON, non-object JSON, missing/non-dict `dir_info`, missing/non-string URL, non-file URLs, wrong local directory, and unreadable metadata. Check `SdkProvenanceError` without leaking metadata contents into messages. Include spaces and Unicode in the accepted fixture path.
- [ ] Run `.venv/Scripts/python -m pytest tests/test_sdk_provenance.py -q`; confirm failure because the helper is absent.
- [ ] Implement the helper without importing `omp_rpc`. Require distribution version `0.1.0`, a JSON object with dictionary `dir_info`, and a local file URL. Decode with Python 3.14 `Path.from_uri` and use `samefile()` against `Path(__file__).resolve().parents[2] / 'vendor/omp/sdk/python/omp-rpc'` resolved. Require both directories to exist; metadata `read_text()` returning `None` is a controlled rejection. Normalize anticipated metadata/JSON/path errors into `SdkProvenanceError`. Add wrong-version and missing-source-directory cases to the tests.
- [ ] Use this diagnostic: `Capri requires the SDK from this checkout. From the checkout root run:\n.venv/Scripts/python -m pip install -r requirements-runtime.txt`. Do not include arbitrary URLs or metadata bodies.
- [ ] Add CLI regression tests `test_cli_rejects_foreign_sdk_before_credentials_or_services`, `test_cli_checks_sdk_with_runtime_override`, `test_cli_help_does_not_check_sdk`, and `test_guest_probe_skips_sdk_guard`. Assert exit 2 and the repair command on rejection, no credential read, and no application/child startup. Existing runtime-path cases must pass with a mocked successful guard.
- [ ] Run `.venv/Scripts/python -m pytest tests/test_cli.py -q`; confirm the new guard expectations fail before wiring it in.
- [ ] Call the guard after argument parsing, only for normal DM startup, before runtime/token validation and token reads. Move `app.run` and `guest_probe.run_guest_probe` imports into their selected branches so missing SDK metadata yields the controlled error before SDK-dependent imports. Update CLI tests to patch functions at their defining modules rather than removed CLI import aliases. Keep `--help` and guest-probe semantics.
- [ ] Extend the existing opt-in fresh-venv installation test to call `verify_sdk_provenance()` in the successfully installed copied checkout. This uses the existing wheelhouse when available; do not make it mandatory for ordinary pytest runs.
- [ ] Update README installation guidance to explain startup rejection and the reinstall command. Keep plain `pip install -e .` documented as unsupported for establishing SDK origin.
- [ ] Run `.venv/Scripts/python -m pytest tests/test_sdk_provenance.py tests/test_cli.py tests/test_install.py -q`; expect all enabled tests to pass, with the offline-wheelhouse test skipped unless configured.
- [ ] Review the focused diff, then commit as `Reject SDK installs outside the Capri checkout`.

## Task 2: Correct provenance documentation and its hash

**Files:** Modify `vendor/omp/UPSTREAM.md` and only its `additions.UPSTREAM.md` hash in `vendor/omp-source-manifest.json`. Existing tests: `tests/test_vendor.py`.

**Interfaces:** Preserve upstream file hashes, commit/archive identities, patch hashes, and manifest schema.

- [ ] Replace the stale closing paragraph claiming rebuild/smoke/promotion are future tasks. Describe `scripts/bootstrap.ps1`, verified source build, auth-free smoke, publication to `<data>/bin/omp.exe`, CLI default, and absence of automatic login/bot restart. Link `../../docs/verification/vendored-omp.md` for recorded acceptance and limitations.
- [ ] State that startup checks the installed SDK origin. Keep prepared-machine build evidence distinct from pending fresh-Windows and authenticated Telegram acceptance.
- [ ] Recompute SHA-256 from the saved UPSTREAM.md bytes and update only its existing `additions` entry. Do not regenerate the full manifest or rewrite historical hashes. This is necessary because the verifier hashes UPSTREAM.md too.
- [ ] Run `.venv/Scripts/python scripts/verify-vendor.py --root .` and `.venv/Scripts/python -m pytest tests/test_vendor.py -q`; expect exit 0 and passing tests. Review that no other manifest entries changed.
- [ ] Commit as `Update vendored OMP bootstrap documentation`.

## Task 3: Verify the final patch and prepare PR

- [ ] Run `.venv/Scripts/python -m pytest -q`, `.venv/Scripts/python -m pip check`, `.venv/Scripts/python scripts/verify-vendor.py --root .`, and `git diff --check`. Record actual results and skips; do not reuse the historical 335-pass count.
- [ ] Inspect `git status --short` and the final commit diff for private/runtime artifacts and unintended vendor modifications.
- [ ] When PR creation is requested, push the branch and open a PR against `main`; the existing `.github/workflows/test.yml` already triggers on `pull_request`. Attach the created PR to the chat. Wait for and inspect its actual CI result before claiming GitHub verification.
- [ ] PR description: explain the complete vendored-runtime branch, supported bootstrap path, new SDK guard, verification results, and pending fresh-Windows/authenticated acceptance. Do not describe the whole PR as only this follow-up fix.

## Deliberately deferred

Native-build CI, a new workflow trigger, fresh VM provisioning, authenticated Telegram acceptance, personality/soul integration, SDK packaging redesign, and any architecture cleanup. A full bootstrap rerun is not required by these Python/documentation changes; broaden verification only if implementation exposes a new build concern.
