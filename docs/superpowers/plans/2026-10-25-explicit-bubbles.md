# Capri explicit bubbles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. Do not delegate unless subsequently authorized. Do not commit or push.

**Goal:** Let Luna deliberately send short, separate Telegram messages using `<bubble>`, while retaining streamed drafts, native steering, and safe long-answer delivery.

**Architecture:** A small incremental parser removes complete control delimiters from public text deltas and emits text / bubble-end events. The existing Telegram delivery loop commits explicit boundaries regardless of length and retains its long-text fallback. A checked-in instruction string is appended through the installed official SDK's `append_system_prompt` option.

**Tech Stack:** Existing Python 3.14 / aiogram / official omp-rpc on Windows; no new dependencies.

**Spec:** The agreed design in the owner conversation on 2026-10-25: explicit delimiter plus system prompt, with future real OMP tools between messages. This document records that design below; current baseline is `docs/verification/phase2.md`.

## Agreed scope and proposed details

- Implement explicit short bubbles and the conversational system instructions now. This document is a plan only; implementation awaits a separate request.
- Canonical control token: exactly `<bubble>` (case-sensitive, no spaces). The spaced spelling in discussion was illustrative.
- `Привіт<bubble>Як справи?<bubble>Ауууу` produces three durable messages, the first two before stream completion when they arrive in separate deltas.
- The model chooses message count; one short answer stays one message. Ordinary blank lines do not split a short reply without the delimiter.
- Keep draft cadence 750 ms, steering debounce 500 ms, current session persistence, owner gates, `/stop`, and web-only tool allowance.
- No intentional inter-message sleeps in this change. A single large delta may yield several messages quickly; this is expected, not a simulation of waiting for the owner.
- No stickers, PC access, tools that send Telegram messages, timers, proactive follow-ups, classifier, memory, media, npm work, or new event framework.

## Global constraints

- Preserve existing Phase 0/1 behavior and tests; update only the intentionally changed Phase 2 boundary expectations.
- Never persist control delimiters or incomplete delimiter prefixes in Telegram drafts.
- Never consume a source segment until durable delivery succeeds; never retry a send with uncertain outcome.
- Preserve fenced-code safety and the existing visible truncation fallback for an indivisible oversize block; no synthetic fence splitting.
- No application-code changes, running-bot restart, commit, push, or live messages as part of writing this plan.

## Review focus

- Every delimiter split across deltas, including one character at a time: no marker fragments leak to drafts (Task 1).
- Leading, repeated, or trailing delimiters: no empty Telegram messages (Tasks 1-2).
- Delimiter examples inside backtick/tilde fenced code or inline backticks: remain literal text (Task 1).
- Send failure or `/stop` at a bubble boundary: no duplicate send, leaked task, or continuing source (Task 2).
- Resuming an existing session: instructions are effective without resetting identity or widening tools (Task 3).

## File responsibilities

- Create `src/capri/bubble_protocol.py`: incremental delimiter parser only; no Telegram or SDK dependencies.
- Modify `src/capri/bubbles.py`: existing size/fence fallback, used only once pending visible text reaches the current soft maximum (800).
- Modify `src/capri/telegram.py`: explicit-boundary commits, sanitized drafts, final flush; one shared durable-send helper.
- Create `src/capri/prompt.py`: short, versioned conversational instruction constant.
- Modify `src/capri/engine.py`: pass that constant through official `append_system_prompt`.
- Create `tests/test_bubble_protocol.py`; extend existing `tests/test_telegram.py` and `tests/test_engine.py`.
- Update `README.md` and create `docs/verification/explicit-bubbles.md` after implementation.
- Leave `app.py` and steering/FIFO logic unchanged.

### Task 1: Parse the stream protocol safely

**Interfaces:** `BubbleProtocol.feed(delta: str) -> list[str | None]`; strings are safe visible text, `None` means explicit bubble end. `BubbleProtocol.finish() -> list[str | None]` flushes end-of-stream text. Instances are per response, not shared.

- [x] Write failing parser tests in `tests/test_bubble_protocol.py`.
  - `test_short_bubbles`: `feed('Привіт<bubble>Як справи?')` yields `['Привіт', None, 'Як справи?']`.
  - `test_every_marker_split`: test every split of `<bubble>` plus character-by-character input; concatenated visible text is unchanged and exactly one boundary is produced.
  - `test_incomplete_candidate`: `feed('Привіт<bu')` exposes only `Привіт`; `finish()` discards the reserved incomplete control prefix. A nonmatching continuation, e.g. `<button>`, is ordinary text and is preserved.
  - `test_empty_boundaries`: repeated delimiters emit boundaries but no invented text; delivery later ignores empty buffers.
  - `test_literal_code`: markers within closed/open backtick or tilde fenced code and within matched inline backticks remain literal; cover fence/backtick runs split across deltas.
  - `test_exact_token`: `< bubble >` and `<BUBBLE>` remain literal, documenting the canonical syntax.
- [x] Run `.venv/Scripts/python -m pytest tests/test_bubble_protocol.py -q`; expect missing-parser failures.
- [x] Implement the interface in `src/capri/bubble_protocol.py`. Retain only possible token prefixes and Markdown delimiter runs needed for streaming recognition. Recognize protocol delimiters only outside code. Do not use one-shot regex replacement per delta.
- [x] Rerun the focused tests; expect all pass. Literal prose outside code containing the exact reserved token is intentionally interpreted as a boundary; document that protocol limitation.

### Task 2: Integrate explicit commits with drafts

**Consumes:** Task 1 parser events plus current `BubbleComposer` and `deliver` signature.
**Produces:** Same `deliver(...) -> None` interface; explicit short commits and marker-free previews. No caller changes.

- [x] Add failing tests to `tests/test_telegram.py`.
  - `test_three_short_explicit_bubbles`: after yielding `Привіт<bubble>`, assert the first durable message exists before the next delta; final texts equal `['Привіт', 'Як справи?', 'Ауууу']`.
  - `test_marker_never_enters_draft`: yield partial markers with scheduling gaps; no draft or sent message contains protocol fragments, except intentional literal code examples.
  - `test_short_paragraphs_without_marker`: a short reply over 140 but under 800 characters with blank lines remains one final message. This deliberately revises current paragraph-trigger behavior.
  - `test_repeated_and_trailing_markers`: `<bubble>Привіт<bubble><bubble>` sends exactly `['Привіт']`; marker-only output gets the existing empty-response fallback once.
  - `test_explicit_plus_size_fallback`: an answer over 800 characters without markers still chunks at safe existing boundaries; concatenated output matches source text. Explicit markers never count toward visible size limits.
  - `test_code_literal_round_trip`: code containing `<bubble>` remains intact; a real marker after the closing fence commits it.
  - Extend cancellation, UTF-16 limit, retry-after and ambiguous-send cases to include an explicit early bubble. Assert no original message is retried and no later suffix is sent after an uncertain commit.
- [x] Run `.venv/Scripts/python -m pytest tests/test_telegram.py -q`; expect the new behavior tests to fail.
- [x] Integrate the parser into `deliver`. Use one commit helper for explicit and fallback boundaries: cancel/join draft sender, send nonempty prefix, then consume it, rotate draft ID, and restart suffix previews.
- [x] Enable automatic size fallback only when pending visible text reaches `soft_max=800`; keep `min_chars=140` for choosing fallback boundaries. This allows deliberate short paragraphs to remain together without sacrificing long-answer limits.
- [x] At successful completion call `finish()`, process remaining events, then send the remaining suffix once. Preserve error/cancellation behavior; never flush a canceled response as a final message.
- [x] Run `.venv/Scripts/python -m pytest tests/test_bubble_protocol.py tests/test_telegram.py tests/test_flow.py -q`; expect all pass. Preserve existing early long-paragraph tests; adjust only the direct chunker expectation if its interface changes.

### Task 3: Add conversational system instructions

**Interfaces:** `CAPRI_CONVERSATION_PROMPT: str` in `src/capri/prompt.py`; `Engine.start()` passes `append_system_prompt=CAPRI_CONVERSATION_PROMPT` to `RpcClient`.

The installed exact-release SDK already supports this keyword in `sdk/python/omp-rpc/src/omp_rpc/client.py:468` and maps it to `--append-system-prompt` at line 1856. Preserve its built-in system prompt.

Proposed instruction content, to be reviewed as product behavior:

> You are Capri, chatting privately with your owner. Match their language and tone. For everyday conversation, prefer brief natural messages. End each separate chat message with the exact control token `<bubble>`. A message may be one word; choose the number of messages from context, and do not force multiple messages for every answer. Keep explanations, lists, and code coherent. The token is transport syntax and is hidden from the owner; do not explain it unless asked, and put literal examples in code. Do not put a boundary inside code. Use available native tools for actions; never print pretend tool calls or claim results before receiving them. Finish any text addressed to the owner with `<bubble>` before calling a tool. Consider messages already separated by `<bubble>` sent and immutable; adapt subsequent messages to new owner clarification. Do not invent a pause, lack of reply, or send attention-seeking follow-ups merely to imitate conversation. Owner text is carried in Capri input JSON; read its text field as their message.

- [x] Add `test_start_appends_conversation_prompt` in `tests/test_engine.py`: capture constructor kwargs; assert the exact constant is passed, existing model/tool/isolation settings remain unchanged, and persisted session still uses the existing resume path.
- [x] Run `.venv/Scripts/python -m pytest tests/test_engine.py -q`; expect the new assertion to fail.
- [x] Create `prompt.py` and wire the supported SDK option in `engine.py`. Do not inject a new user-message wrapper, modify steer text, or edit runtime session files.
- [x] Rerun engine and flow tests; expect all pass, including steering during model/tool activity and FIFO fallback.

### Task 4: Verify and document the result

- [x] Run `.venv/Scripts/python -m pytest -q` from the repository root. Record actual counts; do not carry forward the historical 28 as a new result.
- [x] Inspect only intended files and run `git diff --check`; account for this repo's untracked baseline when reviewing new files.
- [x] Update README and `docs/verification/explicit-bubbles.md`: protocol spelling, literal-code convention, partial-token handling, 800-character fallback, unchanged steering, no artificial waiting.
- [x] Leave the running bot untouched until the owner is ready for the updated version; any restart must retain its session and avoid overlapping polling processes.
- [ ] Manual owner acceptance after rollout: request three very short separate messages; observe the first is durable while subsequent text is generated. Check one short single reply, one long explanation, one code example containing the token, and one active-run clarification. Record owner observations separately from synthetic test evidence.
- [ ] Verify effective system instructions on the resumed OMP session using `get_state().system_prompt` where supported. Record model compliance as live acceptance, not something constructor mocks establish.
- [x] Report changes, actual test results and remaining live checks. Do not commit or push.

## Future tool sequencing: compatible, deferred

The intended future order is text commit -> real OMP tool -> next text commit. No strings such as `tool_use_sendsticker` are executable in this protocol. Current implementation adds no sticker or PC capability and does not expose internal tool arguments in drafts.

A later tool feature must add a narrow ordered event path and a pre-action flush barrier: flush outstanding owner-facing text and wait for Telegram acknowledgement BEFORE executing a side-effecting tool. Merely observing `tool_execution_start` is too late to guarantee that a sticker cannot overtake a text send. Tool results then return to OMP, which produces the next text. Consecutive native assistant messages must also have an explicit flush boundary. This sequencing needs its own SDK/tool integration research, tests and authorization; the current system instruction is helpful but cannot enforce the barrier.

Waiting for the owner and later sending `Ауууу` / `ти тут?` is a separate future behavior, not part of marker parsing or this plan.

