# Post-merge hardening — 2026-10-25

Execution follows `docs/superpowers/plans/2026-10-25-post-merge-hardening.md` from
`c8db996` on `codex/post-merge-hardening`, integrated and pushed to main as
`f442c4c`. Application changes have not been deployed
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

Real authenticated prompts and Telegram UX are not revalidated here. Required
branch protection remains pending separate repository-administration authorization.

[Remote Actions run 40225164561](https://github.com/SheetHappiness/capri/actions/runs/40225164561)
completed successfully on main at `f442c4c` on 2026-10-25. The Windows Python 3.14
job passed; the owner also inspected its output and confirmed all 208 tests passed.

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

Authenticated Telegram UX, actual conversation continuity, branch protection and
broader Windows descendant-process termination were not judged by the reviewer.
They remain outside this verification: no live deployment or model prompt occurred,
and the documented SDK guarantee is the Windows leader process only. Remote
publication and Actions acceptance were completed after the local review.
No deferred correctness review findings remain.

The managed worktree denied filesystem writes, so implementation used the allowed
original checkout on a dedicated branch. Commit `f442c4c` was subsequently merged
into local main and pushed to origin/main at the owner's request.

## Delivery semantics limit

If OMP has persisted a turn before a final Telegram edit returns UNCERTAIN, the
next model turn can remember a response the user may not have received. Activity
is not touched without ACK, but the persistent transcript has already advanced.
This is an acknowledged delivery ambiguity; no automatic retry or transcript
rollback is introduced.

## Post-review CI/documentation cleanup

- Checkout v7.0.1 and setup-python v7.1.0 are pinned to their official release
  commit SHAs. Both action manifests declare Node 24.
- Full history is fetched. Whitespace checks compare push before/after commits,
  or the PR merge-base to its head; a new branch compares against the empty tree.
  The PowerShell step explicitly returns Git's exit code.
- Parsed workflow YAML and exercised its exact PowerShell body against six local
  Git fixtures: clean push, multi-commit push with an earlier whitespace error,
  clean/error initial pushes, PR with an error, and clean PR diverging from a base
  with an unrelated error. Clean cases returned 0; error cases returned 2.
- Full local suite: **208 passed in 5.00 seconds**. Production code is unchanged.
  This validates the cleanup locally; its own remote run requires publication.
- Removed the local attachment path and redacted owner identifiers from historical
  verification examples. Existing Git history is unchanged.
