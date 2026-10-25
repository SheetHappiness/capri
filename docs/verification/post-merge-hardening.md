# Post-merge hardening — 2026-10-25

Execution follows `docs/superpowers/plans/2026-10-25-post-merge-hardening.md` from
`c8db996` on `codex/post-merge-hardening`. Application changes have not been deployed
to the running bot. No Telegram messages or model prompts were sent in this work.

## Correctness evidence (tasks 1–2)

- Task 1 RED: six final-delivery cases exposed absent completion accounting and
  an unknown exception triggering a second edit with an error message.
- GREEN: full suite 167 passed. Transport records attempts separately from ACKs;
  only final ACK updates activity. Explicit 429 retries once on the same inline ID;
  network, server and unknown outcomes are uncertain and never retried blindly.
- Task 2 RED: runtime accepted `1` and `"yes"` as safe teardown; owner restart
  after unconfirmed close did not fail. Shared helper and owner safety state fix both.
- GREEN: full suite 183 passed, including real SDK stop with fake subprocesses,
  retained survivors, already-exited stop, cancellation of blocked prompt,
  serialized stop, lazy owner restart cancellation and owner→guest→owner scheduling.
- Restricted test attempts failed/hung during pytest temporary-directory setup;
  successful counts come from the same pytest command with filesystem access.

## Correctness/safety review gate

Independent read-only review accepted the ACK and exact-SDK contract paths, and
found an Important repeated-cancellation race in lifecycle cleanup. Three RED
regressions reproduced early lock release during owner stop, lazy owner start, and
Guest cleanup. Shared protected joins now finish cleanup despite further cancels;
safety is false while stop is pending. Full suite 186 passed after the fix.
The correctness gate is closed by these regressions before tasks 3–7.

## Exact SDK audit

Official source commit: `45c35e40c46166dc726ccc52f5d27f40f2449f99`, package version
0.1.0. Official immutable archive downloaded independently: SHA-256
`a8bbb85ede151ed58c100e84e6d239ca835937e04a51cd287049a9ff737fd4e2`, matching the
existing source archive. All nine SDK Python/type-marker files match the archive,
extracted source and installed package byte-for-byte. Upstream `client.py` blob
`93375fc12a2e8cb981363535addea9fd6d3baafc` matches local `git hash-object`.
No SDK patch is required.

`RpcClient.stop() -> bool` is explicitly documented by that source:

- `True` confirms termination/reaping of the active child and retained survivors.
- Already-exited child and repeated stop are safe; retained survivors are rechecked.
- `False` retains process handles in `survivor_pids` for another stop/reap attempt.
- `_process` is cleared even on failed teardown, so it cannot prove safety.
- Termination errors can escape; Capri maps exceptions to unsafe, retains the client
  and does not start the next child.
- Stop closes pending lifecycle waits; Capri separately joins its synchronous
  Guest worker. Stop itself uses bounded reader-thread joins.
- Windows confirms the leader with terminate/wait/kill/wait; process-group checking
  applies only on POSIX. This work does not broaden the web-only OMP tools.

`pyproject.toml` pins the source URL, commit, SDK subdirectory and archive hash.

## Real local OMP teardown acceptance

Ran the hash-pinned OMP 18.12.6 binary using the actual installed SDK, in separate
empty agent directories with explicit provider/model selection. No copied auth,
private sessions, model prompt or Telegram transport. Each child reached RPC ready
and answered `get_state`, then stopped. Observed:

| Case | PID | Confirmed stop | Exit code | Survivors |
| --- | --- | --- | --- | --- |
| owner | 22132 | true | 1 | none |
| guest | 25532 | true | 1 | none |
| owner resume phase | 17908 | true | 1 | none |
| already exited | 23392 | true | 1 | none |

Repeated stop returned true in every case. Exit code 1 records termination, not
successful model work. The labels describe serial process phases; actual owner
session continuity is tested separately with runtime fakes and earlier live evidence.
An initial empty-profile attempt omitted explicit model selection and exited before
ready; the acceptance command was corrected to select Luna without prompting it.

## Remaining acceptance

Real authenticated prompts and Telegram UX are not revalidated here. Remote Actions
success and required branch protection are pending publication/admin authorization.

## Cleanup evidence (tasks 3–7)

- Bounded dedupe RED at 2049 entries, then GREEN; full suite 188 passed.
  Concurrent duplicate and failed/uncertain answer reservations stay deduplicated.
- Windows/Python 3.14 workflow added for PRs and main pushes with read-only contents
  permission. Application/test dependencies pinned in requirements-test.txt; official
  SDK source/hash remains in project metadata. Build backend version floors remain.
- Fresh environment installation and pip check passed. Workflow YAML parsed and
  expected triggers/runner/steps verified locally. No OMP binary/auth is needed by tests.
- Mention parsing RED: five repeated/content/caption regressions, then GREEN;
  full suite 199 passed. First matching Telegram mention entity only, case-insensitive,
  exact UTF-16 range; entity-less fallback removes at most one leading invocation.
- Metadata RED: nine title/listing regressions, then GREEN; full suite 208 passed.
  Titles normalize to one line and 100 code points. Listings cap at 20 and use _fit;
  emoji output stays within 4096 UTF-16 units. Legacy display is bounded without
  rewriting stored titles or removing sessions; full-title resume still works.
- Historical Guest UX report marked superseded; README links current behavior.

## Final review and validation

Independent whole-change read-only review approved the delta against `c8db996`:
no Critical, Important or Minor findings. Reviewer independently ran the full suite:
**208 passed in 4.89 seconds**, and `git diff --check` passed. Primary final run in
the clean archive-pinned environment: **208 passed in 4.96 seconds**; `pip check`
reported no broken requirements. The OMP binary hash also matches the documented pin.

Authenticated Telegram UX, actual conversation continuity, remote Actions/branch
protection and broader Windows descendant-process termination were not judged by
the reviewer. They remain outside this local verification: no live deployment,
model prompt or remote publication occurred, and the documented SDK guarantee is
the Windows leader process only. No deferred review findings remain.

The managed worktree denied filesystem writes, so implementation used the allowed
original checkout on a dedicated branch. The application/test changes remain
uncommitted pending the owner's integration choice.
