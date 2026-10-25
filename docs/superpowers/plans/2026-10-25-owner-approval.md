# Owner Telegram Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the paired Owner approve one native OMP shell call from Telegram without broadening automatic permissions.

**Architecture:** A small async Telegram approval bridge schedules native SDK UI requests off the SDK listener thread. Engine owns client/run lifetime and conservative command correlation; OMP owns policy and execution. Telegram callback handling is separate from streamed delivery and the runtime lock.

**Tech Stack:** Existing Python 3.14, aiogram, pinned official omp_rpc SDK; no additional dependencies.

**Spec:** `docs/superpowers/specs/2026-10-25-owner-approval-design.md`

## Execution status

Implementation and automated verification completed: 267 tests pass. Native pinned
OMP and actual Engine adapter probes confirmed deny/allow with marker-file evidence.
Live Telegram acceptance and safe restart remain pending; the running bot was not
force-stopped during implementation. The Owner subsequently authorized restart,
reported live approval/deny/timeout results, and authorized commit/push. These later
authorizations supersede the implementation-phase restrictions below. Follow-up
full suite: 268 passed. See `docs/verification/owner-approval.md`.

Execution refinements: Engine approval tests live in `tests/test_engine_approval.py`;
Engine also accepts `approval_notice: Callable[[str], Awaitable[None]] | None` and
ApprovalBridge has `notice(text: str) -> None` for explanatory private refusals.
Self-review hardened repeated cancellation and serialized concurrent child teardown.

## Global Constraints

- Work on main as explicitly authorized; no commits/pushes.
- Existing automatic allowlist and tools.approvalMode=write remain unchanged.
- Guest stays no_ui=True and exactly web_search-only.
- Only one-call approval; no persistent/session grants, computer-use or host tools.
- Default approval deadline 60 seconds, enclosing prompt deadline 180 seconds.
- Never grant when command/cwd correlation, identity or delivery is uncertain.
- No force-stopping active OMP or destructive live acceptance.

## Review Focus

- UI text is truncated or repeated across calls with different cwd: reject ambiguous/unseen commands (Task 1).
- Late clicks after /stop, timeout, restart or client handoff: no command execution (Tasks 1–3).
- Telegram sends succeed remotely but fail locally: invalidate token, deny, do not retry (Task 2).
- SDK listener and prompt worker race with teardown: respond only against the owning client and never block listener (Task 1).
- Owner click while streaming/Guest queued: callbacks remain responsive, Guest never receives UI access (Task 3).

## File map

- Modify `src/capri/engine.py`: native UI lifecycle, completed tool arguments, client/run correlation.
- Create `src/capri/approval.py`: private Telegram approval messages and ephemeral pending callbacks; not a policy engine.
- Modify `src/capri/app.py`: bridge construction, callback route and shutdown integration.
- Modify `tests/test_engine.py`, `tests/test_app.py`, `tests/test_guest_engine.py`; create `tests/test_approval.py`.
- Update README and verification evidence after implementation.

### Task 1: Characterize and adapt native Owner approvals

**Files:** `src/capri/engine.py`, `tests/test_engine.py`; local ignored native probe.

**Interfaces:**
- Produces `ShellApproval` immutable record in engine.py: request_id:str, command:str, cwd:Path, prompt:str, deadline:float.
- Engine constructor gains optional `approve: Callable[[ShellApproval], Awaitable[bool]] | None`.
- Engine alone sends SDK responses, tracks pending tasks and invalidates them when run/client ends.
- Consumes official `on_ui_request`, `send_ui_value`, `cancel_ui_request`, message update toolcall_end.

- [ ] Characterize real pinned RPC approval on a separate isolated runtime: record UI select title/options, cancel path, SDK thread delivery, and completed tool-call argument shape without leaking credentials. Inspect native truncateForPrompt and requestRpcSelect behavior. No product implementation until the actual once/deny wire contract is known. If native channel cannot support this safely, stop with evidence rather than emulate permissions.
- [ ] Add RED tests: no callback keeps no_ui=True; callback enables UI only for Owner; native select maps approved bool to exact `Approve`/`Approve Once`, denied to `Deny` or cancellation. Unsupported/passive dialogs never authorize execution.
- [ ] Add RED correlation tests: completed bash call command/cwd shown exactly, default cwd is data/work; native truncated command, unknown request, multiple same commands/different cwd, non-bash and mismatched arguments deny. No session choice may ever be sent.
- [ ] Add RED lifecycle tests: SDK thread listener returns promptly; /stop, prompt timeout, completion/failure, close, restart and old-client cancellation revoke pending requests; a late True cannot reach a new client or approve an ended run. Multiple requests have independent IDs and first response wins.
- [ ] Run `.venv/Scripts/python -m pytest tests/test_engine.py -q`; expected new failures with old functionality, existing tests otherwise valid.
- [ ] Implement the smallest adapter, keeping no-approval Engine construction backward compatible. Capture the running loop before start, register UI listeners before SDK start; schedule via loop.call_soon_threadsafe. Never hold stream or steer locks while responding. Pair native UI only to unique matching completed bash call; fail closed otherwise. Complete cleanup before process/session replacement.
- [ ] Run the focused command again; expected PASS. Run full suite; expected PASS. Record evidence, no commit.

### Task 2: Private Telegram approval bridge

**Files:** create `src/capri/approval.py`, `tests/test_approval.py`.

**Interfaces:**
- Consumes Task 1 ShellApproval.
- Produces `ApprovalBridge(bot, owner_id: Callable[[], int | None])` with async `request(request: ShellApproval) -> bool`, `handle_callback(query) -> None`, `close() -> None`.
- Pending state is memory-only, token-scoped, message-bound; Engine cancellation of request coroutine revokes its token.

- [ ] Add RED tests for exact plain-text command/cwd message, two Ukrainian buttons, and allowed callback data length. Bind random unguessable token to actual returned message, private chat and owner identity.
- [ ] Add RED authorization tests: wrong sender, wrong chat type/id, wrong message id, unavailable callback message, malformed/unknown token, stale token, duplicate and racing opposite decisions never approve. First valid click returns bool once; callback ack/keyboard edit failure cannot repeat a permission.
- [ ] Add RED failure tests: timeout after 60 seconds/before request deadline, send failure including ambiguous delivery, close/cancellation, overlong command/message (no silent truncation), failed message edit and callback answer all fail safely. No callback payload or raw command logging.
- [ ] Run `.venv/Scripts/python -m pytest tests/test_approval.py -q`; expected FAIL before bridge exists.
- [ ] Implement bridge using aiogram inline keyboards and asyncio futures. Expire state before UI cleanup; no uncertain send retries. Display exact command/cwd without parse_mode; reject unsafe-to-display controls/overlong requests rather than hide content. Background timeout tasks must be cancelled/joined on close.
- [ ] Run focused tests then full suite; expected PASS. Record evidence, no commit.

### Task 3: Wire callbacks and prove isolation / live behavior

**Files:** `src/capri/app.py`, `tests/test_app.py`, `tests/test_guest_engine.py`, README, `docs/verification/native-tools.md` or a linked approval report.

**Interfaces:** consumes Engine approve constructor option and ApprovalBridge methods; existing OmpRuntime serializes Owner/Guest unchanged.

- [ ] Add RED tests that app gives only Owner Engine the approval callback; registers callback_query route; resolved polling updates include callback_query; private Owner click is handled during an active turn without entering InboundFlow or waiting for OmpRuntime.lock.
- [ ] Add RED tests that /stop, app shutdown and owner→Guest→owner handoff expire dialogs, and Guest SDK still receives no_ui=True and only web_search. Existing Guest extra-tool rejection remains intact.
- [ ] Run `.venv/Scripts/python -m pytest tests/test_app.py tests/test_guest_engine.py -q`; expected new tests FAIL.
- [ ] Wire bridge construction before Engine startup using current pairing owner getter; route prefixed callback data only. Close/revoke bridge before stopping engine and closing bot session. Do not expose approvals in Guest or change config/prompt capabilities.
- [ ] Run `.venv/Scripts/python -m pytest -q` and `git diff --check`; expected zero failures and no whitespace errors.
- [ ] Author self-review (no subagent tool): compare actual diff against spec, explicitly inspect repeated-cancellation, stale tokens, exact command display, single-use SDK answers and Guest boundary. Fix important findings via RED→GREEN; run suite again. Do not claim independent review.
- [ ] Document automated results and native characterization separately from live Telegram evidence. Before restart inspect active processes; if a turn/OMP is active, coordinate graceful shutdown instead of forced termination.
- [ ] Controlled live checks after safe restart: exact git status has no dialog; harmless non-allowlisted inspection shows command/cwd and executes only after Allow once; Deny and timeout prevent a harmless marker-file command from creating its marker; repeated/old click cannot execute again; /stop revokes open dialog; Guest remains web-only. Do not use shutdown/reboot/game launch for testing.
- [ ] Stop before commit/push and report pending acceptance explicitly.

## Handoff / self-check

Plan checked against approved scope: bridge only, OMP remains policy authority,
no persistent grants, no new automatic PC actions. Interfaces are shared through
ShellApproval; callback auth and teardown are covered before live restart.
The characterization step must settle exact native request parsing before code;
any protocol limitation is a blocker, not permission to guess.
