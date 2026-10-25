# Capri post-merge hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Implement inline; use read-only reviewers required by the execution skill. Steps use checkbox syntax. Do not use GPT-6 Astra for subagents.

**Goal:** Establish acknowledged Guest final delivery and verified child teardown, then bound metadata and dedupe, add Windows CI, and clarify current documentation.

**Architecture:** Retain one Guest inline message and the existing serialized owner/guest runtime. Model delivery outcomes explicitly; base teardown on the exact official SDK implementation. Keep cleanup local to Guest routing and storage.

**Tech Stack:** Windows x64, Python 3.14, aiogram 3.31.0, official omp-rpc SDK.

**Spec:** User attachment `Pasted text.txt` (post-merge hardening request), supplied 2026-10-25.

## Global constraints

- Preserve paired-owner authorization, web-only OMP capability isolation, private sessions, and credentials outside Git.
- No second Guest answer, ordinary send, or DM fallback; reserve failed and uncertain query attempts too.
- Execute tasks 1–2 first, run full tests and local teardown acceptance, then perform a separate correctness/safety review before tasks 3–7.
- Unit tests require neither authenticated OMP nor Telegram. Live acceptance stays separate.
- Never automatically delete old sessions.
- Do not restart the running bot or send live Telegram messages during hardening.
- Do not claim a green Actions run or mandatory branch check until verified remotely.

## Verified starting state

- Local `codex/first-milestone` is at `8d6fc6e`; working tree was clean before this plan.
- Fetched `origin/main` is at `c8db996` and contains the Guest code missing from the local branch.
- Begin implementation from the fetched main in an isolated worktree, retaining the existing checkout.
- `src/capri/guest.py` returns `None` both for successful edits and Telegram API failures; final delivery currently ignores that distinction.
- `src/capri/guest_engine.py` uses `stop() is True`; locate and inspect `OmpRuntime` before modifying its teardown path.
- Installed `.venv/Lib/site-packages/omp_rpc/client.py` declares `stop() -> bool` and documents confirmed teardown, retained survivors, and repeated stop/reap. This alone does not prove it matches pinned upstream source.
- README already records executable/source commit `45c35e40c46166dc726ccc52f5d27f40f2449f99` and executable SHA-256 `73d73c11dc8821cf939441a964992aefc9c5b0d5a4418e9e8985a46439b60eef`; package metadata still allows any `omp-rpc==0.1.0` source.

## Review focus

- API call attempted versus ACK received: final-success tests must assert acknowledged content, including after progress failure (task 1).
- Final retry receiving another 429: terminate after one retry without another answer or success bookkeeping (task 1).
- SDK source drift under identical version numbers: compare installed and pinned source, record any patch explicitly (task 2).
- Cancellation during synchronous prompt/start and teardown exception: retain unsafe state and prevent the next child (task 2).
- Existing long titles and non-BMP characters: bound public rendering without deleting historical sessions; verify UTF-16 delivery size (task 6).

### Task 1: Final edit ACK semantics

**Files:** Modify `src/capri/guest.py`, `tests/test_guest.py`.

**Interfaces:** `_edit(inline_id, text)` returns a typed outcome carrying ACKED, RETRY_AFTER plus delay, FAILED, or UNCERTAIN. `publish(text, final=False)` reports acknowledged delivery, with progress failure allowed to continue to final.

- [x] Extend fake transport with separate attempted/acknowledged records. Add tests for final ACK, progress failure followed by acknowledged final, explicit final 429 then ACK, repeated 429, deterministic rejection, and uncertain network outcome without duplication.
- [x] Run `.venv/Scripts/python -m pytest tests/test_guest.py -q`; confirm new assertions expose current false success.
- [x] Implement typed results; successful final completion requires ACK. Retry a final once after explicit 429; permit at most one other retry only for an explicitly proven safe transient rejection. Invariant: generic network errors are UNCERTAIN and never retried without proof that Telegram did not accept the edit. Log uncertainty and final failure distinctly. Preserve pacing and one-answer reservation; avoid exception handling that publishes another final after uncertainty.
- [x] Run focused and full `.venv/Scripts/python -m pytest -q`; verify both acknowledged content and bounded attempts, not just API invocation count.

### Task 2: Exact SDK provenance and teardown contract

**Files:** Modify `src/capri/guest_engine.py`, `src/capri/engine.py` and `src/capri/app.py` (`OmpRuntime`); create `src/capri/teardown.py` as the shared teardown helper; corresponding engine/runtime tests; `pyproject.toml`, `README.md`; add reproducible bootstrap/provenance files only as required.

**Interfaces:** One shared synchronous teardown adapter invoked through `asyncio.to_thread`, returning confirmed-safe status. Its implementation must follow the audited SDK contract rather than guessing from `_process` being cleared.

- [x] Read the installed SDK and `.runtime/source/oh-my-pi-45c35e40c46166dc726ccc52f5d27f40f2449f99/sdk/python/omp-rpc` teardown implementations, process termination helpers, survivor handling, and installation provenance. Compare with immutable upstream source. Determine whether the installed SDK contains local changes.
- [x] Record exact `stop()` signature/return, already-exited behavior, failed termination behavior, process reaping and worker guarantees. Retain boolean confirmation if the exact source reliably defines it; a cleared process attribute alone is insufficient when survivors are retained.
- [x] Write regression tests using faithful process/client fakes: normal stop, already exited, failed/raising stop, cancel with blocked prompt, owner→guest→owner, and unsafe teardown preventing the next child. Run them before the relevant production change.
- [x] Implement the smallest shared adapter/lifecycle changes supported by the audit. Ensure cancellation joins the real synchronous worker and failure cannot release the runtime as safe.
- [x] Pin SDK installation to immutable official source with verifiable provenance; a local patch, if needed, must be recorded and reproduced explicitly rather than hidden behind version 0.1.0. Keep binary commit/hash verification documented.
- [x] Run real local child start/stop/reap acceptance without Telegram sends; capture only redacted process/exit evidence. Run full pytest.
- [x] Perform a separate review of tasks 1–2 and record findings before continuing. Stop for user input only if an unresolved contract/provenance issue prevents safe implementation.

### Task 3: Bounded Guest query dedupe

**Files:** `src/capri/guest.py`, `tests/test_guest.py`.

**Interfaces:** Reservation remains synchronous before any await; a FIFO deque and membership set retain at most 2048 query IDs.

- [x] Write and run failing tests for oldest eviction and both collections staying bounded; cover duplicates and failed/uncertain attempts remaining reserved within the window.
- [x] Evict the oldest ID from membership before appending at capacity; keep reservation before network work.
- [x] Run Guest tests, including concurrent duplicate updates.

### Task 4: Windows GitHub CI

**Files:** Create `.github/workflows/test.yml` and a reproducible test dependency definition if needed; update installation instructions as necessary.

**Interfaces:** Stable named test check on pull requests and main pushes, Windows runner, Python 3.14, exact SDK source from task 2.

- [x] Define minimal read-only workflow permissions; checkout, set up Python 3.14, install reproducible dependencies, run `python -m pytest -q` and `git diff --check`. Explicitly propagate failures of both commands on PowerShell.
- [x] Verify installation and tests in a fresh local environment without binary/auth/token requirements.
- [x] Validate workflow syntax and inspect a real Actions run: run 40225164561 succeeded on main at `f442c4c`.
- [ ] Configure the stable check as required only with repository-administration authorization; this remains a separate admin acceptance item.

### Task 5: Remove only invocation mentions

**Files:** `src/capri/guest.py`, `tests/test_guest.py`.

**Interfaces:** A small invocation-removal helper consumes the original text and Telegram entities, preserving all text outside the selected invocation occurrence.

- [x] Write and run tests for leading mention, unquoted middle invocation, mixed case, quoted/content username, repeated mentions, longer lookalike username, and non-BMP prefix with Telegram UTF-16 offsets. Caption entities follow the selected caption input.
- [x] Remove exactly the UTF-16 range of the first Telegram `mention` entity case-insensitively equal to the configured bot username (`@Capriompbot`). Preserve all other occurrences, including repeated mentions. Without a matching entity, remove at most one invocation-like occurrence; preserve literal content such as `Скажи, що означає @Capriompbot`. Keep any entity-less fallback narrow and conservative rather than globally substituting regex matches.
- [x] Run Guest tests and verify command parsing still works after invocation removal.

### Task 6: Bound thread titles and listings

**Files:** `src/capri/guest_threads.py`, `src/capri/guest.py`, `tests/test_guest_threads.py`, `tests/test_guest.py`.

**Interfaces:** Normalize new/renamed titles to one line, strip whitespace, cap at 100 Unicode code points. Empty creation title becomes `None`; empty rename is rejected. Listings show the current entry first and at most 20 entries total, retaining existing store ordering.

- [x] Write and run failing tests for oversized, multiline, whitespace-only and Unicode titles, empty rename, and listings with more than 20 threads and non-BMP titles staying within Telegram delivery limits.
- [x] Normalize writes and bound display of legacy titles on read/render without deleting records or sessions. Pass the rendered `/threads` listing through `_fit` and assert its final UTF-16 size is at most 4096 units, including non-BMP titles. Preserve existing IDs, resume selectors and current-thread behavior; show a brief omitted-entry count when appropriate.
- [x] Run focused tests and full pytest.

### Task 7: Current verification documentation

**Files:** `docs/verification/guest-luna-threads.md`, `docs/verification/guest-live-progress.md`, `README.md`; create a hardening verification record.

- [x] Mark the old Guest document `SUPERSEDED for Guest delivery UX`, linking current `guest-live-progress.md`; preserve historical evidence.
- [x] Update README to current delivery, teardown, dedupe, parsing, metadata and reproducibility behavior; distinguish automated verification from pending Telegram/Actions acceptance.
- [x] Record task 1–2 review evidence, exact SDK contract/provenance, full test results, and local teardown acceptance with no credentials or raw transcripts.
- [x] Run full pytest and `git diff --check`; review the complete diff for scope, privacy and false success paths. Report remaining remote/manual checks explicitly.

## Execution handoff

Implementation proceeded against fetched `origin/main` in the allowed original checkout after the native worktree denied writes. Correctness review found and fixed repeated-cancellation cleanup races before cleanup work. Recommended method: inline implementation with the correctness/safety review after task 2. Approved by the user with four incorporated clarifications on 2026-10-25; execute inline. Commit, push, live Telegram acceptance and repository branch protection changes are separate publication/acceptance decisions.

Integration completed: `f442c4c` was committed, merged into main and pushed.
[Remote Windows run 40225164561](https://github.com/SheetHappiness/capri/actions/runs/40225164561) succeeded.
