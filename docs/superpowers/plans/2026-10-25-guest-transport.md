# Capri Guest Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove owner-authorized Telegram guest delivery, then editing of one guest message, before connecting Luna.

**Architecture:** Add an opt-in Telegram-only probe launcher with a small native aiogram guest handler. It reads existing pairing, answers through the guest API, and never constructs Engine. The normal DM launcher stays unchanged; the two probe phases run sequentially with a live gate between them.

**Tech Stack:** Windows x64, Python 3.14, aiogram 3.31.0, asyncio, pytest and existing mocks.

**Spec:** `docs/superpowers/specs/2026-10-25-guest-transport.md`; distilled from the user's attached research. Scope proposed for review: transport stages only; Luna is a later separate plan.

## Global Constraints

- Windows x64; Python 3.14; aiogram==3.31.0; existing dependencies only.
- No guest OMP startup, owner session reads/writes, ordinary sendMessage, drafts or DM fallback.
- Owner-only access uses incoming real from_user and existing pairing; reject missing/bot/chat senders. Never substitute guest_bot_caller_user, usernames, text or chat IDs.
- Native Router.guest_message; polling uses dp.resolve_used_update_types().
- No memory, stickers, reactions, timers, soul.md, media, npm bootstrap, generic agent harness or session abstractions.
- No computer use. No commit/push without explicit authorization. Do not use GPT-6 Astra for subagents.
- One poller per token. Probe mode temporarily pauses private DM service; restore normal mode after live checks.

## Review Focus

- Anonymous sender or forged owner attribution: reject and explain the rejection category in safe logs (Task 1).
- Duplicate delivery during an in-flight answer: never create another reply for the same query in this process (Task 1).
- Expired query or uncertain answer acknowledgment: do not retry or fall back to normal sends (Task 1).
- Missing inline ID or a failed edit: stop safely without creating another guest result (Task 2).
- Cancellation during the demonstration delay: propagate cancellation, close the HTTP session and leave no background worker (Task 2).

---

## File map and execution setup

- Create `src/capri/guest_probe.py`: owner guard, in-process deduplication, probe reply/edit and Telegram-only polling lifecycle.
- Modify `src/capri/cli.py`: optional `--guest-probe {answer,edit}`; default still calls the existing DM `run`.
- Create `tests/test_guest_probe.py`: typed guest updates, fake Telegram API, handler and lifecycle checks.
- Create `tests/test_cli.py`: default/probe routing; no real network or OMP.
- Modify `README.md`: explicit probe commands and temporary DM downtime.
- Create `docs/verification/guest-transport.md`: live evidence, separate phase statuses, restoration result.
- Leave `app.py`, `engine.py`, `prompt.py`, DM delivery and existing tests unchanged.

Repository: `C:/Users/shtvl/Documents/Codex/2026-10-25/referenced-chatgpt-conversation-this-is-an-3/work/capri`, starting at `8d6fc6e`. Reuse this checkout after checking for unrelated edits; no new worktree is necessary for planning. At execution, follow using-git-worktrees if isolation is needed.

PowerShell commands below run from the repository root. Set once:

```powershell
$py = 'C:/Users/shtvl/Documents/GitHub/CapriCorn/.venv/Scripts/python.exe'
$data = 'C:/Users/shtvl/Documents/GitHub/CapriCorn/.runtime'
$env:PYTHONPATH = (Resolve-Path src).Path
```

Tests use isolated tmp_path storage, never `$data`. Do not print credentials or pass the token on the command line. No commit steps: the user's existing no-commit instruction overrides the skill default.

### Task 1: Owner-only Guest OK probe and first live gate

**Files:** Create `src/capri/guest_probe.py`, `tests/test_guest_probe.py`, `tests/test_cli.py`, `docs/verification/guest-transport.md`; modify `src/capri/cli.py`, `README.md`.

**Interfaces:**
- Consumes `Pairing(path: Path).owner_id`, `Bot`, `Dispatcher`, `Router`, typed `Message` and `SentGuestMessage`.
- Produces `GuestProbe(bot: Bot, owner_id: int)` with `async handle(message: Message) -> None`.
- Produces `async run_guest_probe(token: str, data: Path) -> None`; no Engine parameter/import/construction.
- CLI `--guest-probe answer` dispatches to run_guest_probe; absent flag preserves the current `run(token, omp, data)` path.
- Class owns a process-local set of seen query IDs; reserve before the first await. No capacity limit or persistent dedupe/cache framework for this short-lived spike.

- [x] **Step 1: Add focused failing handler tests.** Use aiogram Message/User/Chat fixtures; paired owner 7, other user 8, service sender 1087968824. Use a fake Bot that captures typed API methods through `__call__`, returning `SentGuestMessage(inline_message_id='guest-inline')` for AnswerGuestQuery and raising on any SendMessage/SendMessageDraft. Tests and assertions:

```python
# Each is a separate test using the shared typed fixture/fake.
def test_owner_gets_one_guest_result():
    # await probe.handle(owner_message) inside asyncio.run
    assert len(answers) == 1
    assert answers[0].guest_query_id == 'q1'
    assert answers[0].result.input_message_content.message_text == 'Guest OK'
    assert ordinary_sends == []

# test_rejected_identity: parameterize nonowner, absent sender, bot sender,
# sender_chat even with owner from_user, missing guest_query_id, unpaired owner.
# Each asserts zero answers and zero ordinary sends.
# test_attribution_is_not_authorization: from_user=8, caller_user=7 -> no answer.
# from_user=7 with caller_user absent remains accepted.
# test_duplicate_inflight: block first API ACK; call handle again with q1;
# release ACK; assert exactly one AnswerGuestQuery.
# test_answer_failure_no_retry: fake raises TelegramBadRequest / network error;
# call handle again with q1; assert one attempt, no ordinary sends, no raw error log.
```

- [x] **Step 2: Run the tests and confirm they fail on missing GuestProbe.**

Run: `& $py -m pytest tests/test_guest_probe.py -q`

Expected: import failure for capri.guest_probe; do not accept a dependency/setup failure as the red test.

- [x] **Step 3: Implement GuestProbe.handle with the exact Task 1 interface.** Reject invalid identity/query before API work; accept all Telegram-delivered owner text guest requests without rechecking mention position. No parsing, context extraction or media download is needed for a fixed reply. Send one article (`id='capri-guest-probe'`, title `Capri`, plain text `Guest OK`, parse_mode=None) through explicit `self.bot.answer_guest_query(guest_query_id=message.guest_query_id, result=result)`. Manually constructed Message input must work without bot context binding. Catch Telegram API/network exceptions once, log only a fixed outcome code, never retry an uncertain answer. Log authorization outcome codes, sender-is-bot and sender-chat-present booleans, but no raw text/identifiers.

- [x] **Step 4: Add failing polling/CLI lifecycle tests.** Monkeypatch Dispatcher.start_polling to inspect registration, feed one typed Update(guest_message=...), then return; monkeypatch Bot methods/session close. Assert:

```python
# test_probe_lifecycle: resolved updates == ['guest_message']; guest handler runs;
# Bot.session.close awaited on success, GetMe error and polling cancellation.
# test_unpaired_probe: missing owner.json -> clear refusal, zero polling/API replies.
# test_malformed_owner_file / test_owner_file_without_owner_id: broken JSON,
# non-object JSON or missing/invalid owner ID -> 'guest_probe: owner pairing unavailable',
# no polling/API replies, no file mutation.
# test_capability: True -> poll; False/None -> BotFather guidance and no polling.
# test_no_omp: Engine constructor/start patched to raise; probe still succeeds;
# session.json and an existing transcript keep identical bytes and timestamps.
# test_cli_default: no flag calls app.run exactly once, never probe.
# test_cli_probe: --guest-probe answer calls probe, never app.run/Engine.
```

- [x] **Step 5: Run lifecycle/CLI tests to confirm failure, then implement run_guest_probe and CLI dispatch.** Check owner.json exists before constructing Pairing, refuse unavailable or malformed pairing without creating state or constructing Bot. Catch file/Unicode/JSON/shape failures locally and validate owner_id as a positive int excluding bool; print exactly `guest_probe: owner pairing unavailable`. GetMe reports username/capability; register only the guest router; log resolved types. If capability is not True, report BotFather Guest Mode action and return with session closed. Wrap all API/polling lifecycle in finally to close Bot.session. Poll with close_bot_session=False. Keep Ctrl+C behavior. Add README commands and evidence template in this same change.

- [x] **Step 6: Verify focused then full regression suite.**

Run: `& $py -m pytest tests/test_guest_probe.py tests/test_cli.py -q`, then `& $py -m pytest -q`, then `git diff --check`.

Expected: all tests pass (existing baseline: 66), no whitespace errors; no Engine/DM source diff.

- [x] **Step 7: Execute live gate 1 without a second poller.** Stop normal bot gracefully. Run `& $py -u -m capri.cli --data $data --guest-probe answer`. Require fresh capability=True and resolved types=['guest_message']. Ask owner to send `Тест @Capriompbot` after sending the message normally in a human DM/group where Capri is absent. Record authorization and answer ACK plus owner's confirmation of exactly one visible Guest OK. Do not manufacture an update or send a message as the user.

If sender is anonymous/service, record BLOCKED at authorization with safe metadata. If no update arrives, record BLOCKED at receipt. If API fails, record its safe category, not a delivery pass. Do not proceed to Task 2 or OMP until a genuine owner-authorized live answer is confirmed. Always stop probe and restore normal launcher after the test window, including a blocked outcome.

### Task 2: Edit the same guest message and second live gate

**Prerequisite:** Task 1 live gate PASS, not only unit tests.

**Files:** Modify `src/capri/guest_probe.py`, `src/capri/cli.py`, `tests/test_guest_probe.py`, `tests/test_cli.py`, `README.md`, `docs/verification/guest-transport.md`.

**Interfaces:**
- Consumes Task 1's handler, ownership guard, dedupe and polling lifecycle.
- Extends `GuestProbe(bot: Bot, owner_id: int, *, phase: Literal['answer', 'edit']='answer', sleep: Callable[[float], Awaitable[None]]=asyncio.sleep)`.
- Extends `async run_guest_probe(token: str, data: Path, *, phase: Literal['answer', 'edit']='answer') -> None` and CLI choices to answer/edit. Default invocation still starts owner DM.

- [x] **Step 1: Add failing edit tests using injected sleep.** Exact expected calls:

```python
# test_edit_phase: AnswerGuestQuery once with message_text='Думаю…';
# sleep called once with 2.0 after its ACK; EditMessageText once with
# inline_message_id='guest-inline', text='Guest OK final', parse_mode=None;
# no chat_id/message_id addressing, no SendMessage/SendMessageDraft.
# test_answer_phase_unchanged: Guest OK once; zero sleeps/edits.
# test_answer_failure_prevents_edit: zero sleeps/edits after failed ACK.
# test_missing_inline_id: fake malformed response -> fixed diagnostic, no edit.
# test_edit_failure: bad request/network failure -> one answer, one edit attempt,
# no retry, no fallback and no raw exception details.
# test_cancel_delay: block injected sleep, cancel handler; CancelledError propagates;
# no edit, no leftover tasks; run_guest_probe closes HTTP session in finally.
# test_cli_edit: dispatch passes phase='edit'; never starts Engine.
```

- [x] **Step 2: Run focused tests and verify failure on unsupported phase/edit behavior.**

Run: `& $py -m pytest tests/test_guest_probe.py tests/test_cli.py -q`.

- [x] **Step 3: Implement the narrow phase branch.** For edit phase answer the placeholder first, validate nonempty returned inline_message_id, await injected sleep(2.0), then bot.edit_message_text using that ID only. Retain Task 1's single attempt policy and dedupe. Await all work directly in the handler; no detached workers, periodic timers or model integration. Handle API failures safely and preserve cancellation. Extend CLI and README.

- [x] **Step 4: Run focused tests, full suite and git diff --check.** Same commands as Task 1. Expected: all pass, Engine/DM behavior unchanged.

- [ ] **Step 5: Execute live gate 2 and restore normal bot.** Stop normal poller, launch `& $py -u -m capri.cli --data $data --guest-probe edit`. Have owner submit one guest mention. Require one visible Думаю… message changing to Guest OK final, two API acknowledgments, and no extra bubble. Repeat by replying to text and by replying to the probe's own message where Telegram delivers a guest update; probe still returns fixed text, makes no claim of having processed context. Log unsupported/non-delivered variants separately. Stop probe, launch existing DM command with --data $data --omp "$data/omp.exe", confirm startup and ask owner to verify DM.

## Handoff after the two gates

Record each gate's evidence and outstanding blockers in docs/verification/guest-transport.md. Do not infer that Saved Messages or another bot's DM works from a human-chat pass. Do not change BotFather settings automatically.

Only after both live gates pass, propose a separate Luna plan: preserve owner-only guards; one isolated web_search-only query; temporary sessions with confirmed cleanup; no owner transcript/resume; serialize authenticated root use if required; strip invocation, tag reply text as untrusted data; clean bubble controls; cap text; throttle edits and handle rate limits; one active guest query; safe final errors. None of this is implementation work authorized by the present transport plan.

Self-review: source proposal stages 1–2 covered; stage 3 explicitly deferred. All five Review Focus cases have owning test steps. Interfaces evolve only in Task 2. No product changes, live acceptance or new capability observation have been made while writing this plan.
