# OMP Remote UI Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for inline execution, with TDD and a final review.

**Goal:** Surface native OMP activity in one live owner DM message, independently of Capri's conversational bubbles.

**Architecture:** Keep the existing SDK child, queue, steering and teardown. The owner stream carries text strings and native SDK thinking/tool event objects. A bounded `TurnActivity` projects those events into plain text; Telegram delivery coalesces updates in one paced sender. No new tool or approval framework.

**Tech Stack:** Python 3.14, pinned official omp-rpc, aiogram, pytest.

**Spec:** The user's eight-point OMP Remote UI request in this chat.

## Global constraints

- Work on main; retain owner authorization, model/session checks and Guest isolation.
- Omit the owner tool selection and tool-set equality check; OMP chooses its native tools.
- Guest keeps its existing web-only policy and public delivery.
- Only render reasoning actually supplied by SDK events; no soul.md, memory or proactive behavior.
- Use the existing draft pacing interval (0.75 seconds), plain text and shared UTF-16 limit.
- Do not retry an ambiguous initial activity send; an activity failure must not lose the answer.

## Review focus

Check large/Unicode output, parallel tool IDs, replacement snapshots versus deltas, Telegram rate limits/failures, and cancellation during an in-flight activity request.

### Task 1: Owner native SDK stream

- [x] Update engine regressions: native read/write/bash tools accepted, SDK tools argument absent, wrong model still fails, text and native activity retain order.
- [x] Observe focused failures, then remove owner restriction and forward typed thinking/tool events through the existing queue.
- [x] Verify engine tests, including existing steering and abort/reuse checks.

### Task 2: Bounded activity projection

- [x] Add `tests/test_activity.py` for thinking, interleaved tool IDs, snapshot replacement, errors and bounded Unicode rendering.
- [x] Observe failures, then add `src/capri/activity.py`: `TurnActivity.update(event)`, `finish(status)` and `render()`.
- [x] Keep only a bounded recent history and text content; never serialize image payloads or opaque result details.

### Task 3: One paced live message

- [x] Add focused Telegram regressions for one message plus edits, burst coalescing, separate bubbles, 429, uncertain send, error and cancellation cleanup.
- [x] Observe failures, then extend `deliver` to route native events into activity and strings into its existing bubble parser.
- [x] Join/cancel the activity sender with the source and draft sender; finish normal/error activity at the same pacing interval.
- [x] Update README and record exact contract provenance and remaining live acceptance.
- [x] Run the complete suite and `git diff --check`, then review the full diff.

## Execution notes

- Baseline: 208 tests passed outside sandbox. Inside sandbox Windows asyncio hangs creating its local socketpair; use the same test command with sandbox escalation and a repository-local basetemp.
- The detailed user request already fixes the architecture and authorizes implementation; proceed inline without another design approval round.

- Final verification: 220 tests passed; git diff --check passed. Independent review found a long activity flood-wait delay; a regression failed before the bounded finalization fix and passed afterward.
- Implementation calls: keep four recent tool calls with bounded excerpts; Guest stays web-only; interrupted activity keeps its last snapshot; give activity finalization two seconds before delivering the normal answer. These affect presentation only, while native OMP execution remains unchanged.
- No live authenticated OMP/Telegram acceptance was performed. Changes remain local and uncommitted on main.
