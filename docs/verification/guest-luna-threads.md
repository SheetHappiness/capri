# Guest Luna threads — verification (2026-10-25)

**Status: SUPERSEDED for Guest delivery UX.** Current behavior:
[Guest live progress](guest-live-progress.md), with subsequent
[post-merge hardening](post-merge-hardening.md). This document preserves historical
thread/isolation acceptance evidence; its older delivery descriptions are not current requirements.

## Scope and status

Implementation is uncommitted on codex/first-milestone, base 8d6fc6e.
Existing Telegram-only answer/edit probes remain unchanged. Both earlier transport
stages were confirmed live by the owner; this is not proof of all new Luna scenarios.

Production startup at 17:28:43 Europe/Warsaw reported:

    Guest Mode supports_guest_queries=True
    Capri @Capriompbot ready for owner [redacted]
    Start polling
    Run polling for bot @Capriompbot

The updated process is running with both message and guest_message handled by one
poller. No computer use, commit, push, or owner transcript injection was performed.

## Automated verification

Baseline: 102 passed. Final full suite: **145 passed in 3.31s**.
Focused store/engine/service/app suites passed; git diff --check passed.
RED before implementation was observed for the missing store, engine, service and
runtime integration. Three cancellation/teardown regressions and uncertain answer
outcome regression were reproduced RED and fixed GREEN.

Covered: store persistence, scoped selectors/title/ambiguity, malformed metadata,
validated derived paths, exact Luna/web_search set, owner file isolation, new vs
resumed SDK sessions, public-only deltas, cancellation and stop joining, thread
commands without Luna, authorization before storage, reply/caption DATA, mention
stripping, dedupe, one result/no ordinary sends, UTF-16 truncation, safe errors,
missing query ID, busy rejection, single poller, disabled capability/malformed
thread store preserving DM startup. Existing DM/steer/bubble tests remain green.

## Actual OMP integration (not synthetic Telegram acceptance)

Used the real pinned runtime/OMP executable and authenticated config root, with
no owner child running. Two temporary diagnostic session directories used reserved
chat namespace 0 and random 12-hex thread IDs. They were removed after confirmed
child teardown; production thread persistence has no expiry.

Observed:

- Thread 9f95644ad47b, first child: resumed=False, tools=web_search.
- Same thread, second child: resumed=True; recovered the exact random diagnostic
  marker from the preceding invocation without the marker in the new prompt.
- Separate thread fb65c3450bb3: resumed=False, returned NONE for prior marker.
- Same first thread, subsequent child: resumed=True; tool_execution_start recorded
  actual tool_name=web_search while answering an official-source current-info query.
- Final child teardown confirmed; owner session.json and pointed-to transcript
  hashes AND nanosecond mtimes were identical before and after all four calls.

This verifies actual OMP continuation, fresh-thread separation, actual web search,
selected model/tools and owner-file isolation. It does not assert correctness of
all generated search facts or receipt of a Telegram guest reply.

## Concurrency decisions

Shared authenticated root concurrency is not assumed safe. OmpRuntime holds one
lock over child lifetimes: guest waits for active owner DM, confirms stop of the
owner child, then runs/stops a guest child. The next DM lazily starts the owner
Engine with its original session pointer. Guest turns do not restart/rewrite the
owner pointer. DM startup after guest adds latency; messages wait while guest runs.
Cancellation joins real synchronous workers before releasing the runtime lock.
Unconfirmed teardown blocks new OMP work until process restart.

Existing telegram._fit is reused directly to preserve identical UTF-16 limits
without changing frozen DM transport. Engine and telegram.py were not modified.

## Production Telegram acceptance — PENDING owner participation

The bot is running; owner was asked to send two genuine summons in a supported
human chat. No synthetic guest updates were used for live claims.

- A: normal owner DM response after integration — pending.
- B: three real guest turns retaining A+B in same thread — pending.
- C: guest Telegram web-search continuity — pending (actual isolated OMP web_search
  separately passed above).
- D/E: real /newthread and /resume context switching — pending.
- F: owner file isolation across real Telegram guest turns — pending (real OMP
  diagnostic isolation passed above; concurrent real DM would invalidate comparison).
- G: 1 answerGuestQuery plus edits of same message, zero sendMessage in real new
  Luna flow — pending. Earlier transport-only probe gates passed.
- Reply/reference visible through a real Telegram summon — pending.

## Files changed for this plan

Created:
- src/capri/guest_threads.py
- src/capri/guest_engine.py
- src/capri/guest.py
- tests/test_guest_threads.py
- tests/test_guest_engine.py
- tests/test_guest.py
- tests/test_guest_app.py
- docs/superpowers/plans/2026-10-25-guest-luna-threads.md (user-supplied plan)
- docs/verification/guest-luna-threads.md

Modified:
- src/capri/app.py
- src/capri/prompt.py
- README.md

Pre-existing uncommitted probe/CLI/tests/docs changes were preserved.

## Review

Fresh read-only reviewer found one Important issue: cancellation during lazy owner
restart could release the lock before startup completed. A delayed-start test
reproduced it; startup is now shielded/joined and child teardown confirmed under the
lock before cancellation propagates. Full suite145 passed afterward.
Documentation noted by review has been completed as planned Task8 work.
Reviewer did not run tests or judge actual OMP/Telegram behavior; actual OMP evidence
was obtained separately above and Telegram scenarios remain pending.

Final focused suites: 43 passed in 2.41s. Engine/telegram.py diff remained empty. Owner hash/mtime snapshot saved before pending Telegram acceptance; contents were not copied.

## Owner-confirmed production guest continuity

Owner confirmed: “Працює” after the requested ThinkPad T14 two-summon test.
Logs show update409541879 at17:31:24 answered/edited, thread17d0e160b163,
resumed=False; update409541880 at17:31:47 used the same chat/thread,
resumed=True, answered/edited successfully. This is PASS for two-turn guest
continuity, not the full three-turn A+B comparison or all Task7 scenarios.
A third invocation409541881 completed17:34:16, duration40.247s, with edits;
its answer content was not judged here. Owner requested replacing the fixed
Думаю… placeholder with public model progress and a clean final answer.
That delivery refinement is being discussed; no code change has been made yet.
