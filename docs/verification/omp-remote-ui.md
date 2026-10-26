# Owner OMP Remote UI

Implemented on main on 2026-10-26. Scope is the paired owner's private DM;
Guest threads keep their existing web-only tools and public-text-only delivery.

## Contracts inspected before implementation

Official OMP/SDK source pinned at `45c35e40c46166dc726ccc52f5d27f40f2449f99`:

- `sdk/python/omp-rpc/src/omp_rpc/client.py`: `tools=None` omits the CLI tool
  override. `on_message_update` and typed tool event subscriptions share the SDK
  reader and dispatch path. Capri omits the owner `tools` argument entirely.
- `sdk/python/omp-rpc/src/omp_rpc/_wire.py`: typed `MessageUpdateEvent` uses
  `assistant_message_event`; tool start/update/end use `tool_call_id`, `tool_name`,
  `args`, `partial_result`, `result` and `is_error`. `ToolStreamUpdateEvent.update`
  carries native streamed previews.
- `packages/coding-agent/src/modes/rpc/wire/events.ts` and
  `rpc-wire.generated.ts`: provider thinking start/delta/end and native tool
  lifecycle are actual RPC events. No reasoning is synthesized from tool names.
- `packages/coding-agent/src/cursor.ts`: tool execution updates carry full text
  snapshots; replacement avoids repeated prefixes in command output.
- `packages/coding-agent/src/session/stream-guards.ts`: native edit stream previews
  expose file paths and error diagnostics under `update.files`.

The existing async owner queue now carries strings and native SDK activity objects.
`OmpRuntime` forwards that stream unchanged. `TurnActivity` is a bounded view model,
not a second agent/event runtime. Telegram delivery routes strings to the existing
bubble parser and activity to one paced send/edit task. It never executes tools.

## Automated verification

Baseline before code changes: 208 tests passed. Focused tests were observed failing
before the native-tool restriction, view model and activity delivery were implemented.
The expanded suite passes 220 tests, covering:

- Native tool sets accepted, no tool override, wrong model still rejected,
  actual typed SDK events and text emitted in order, and late callbacks discarded.
- Interleaved tool IDs, thinking accumulation, replacement text snapshots,
  errors, bounded recent history, omitted binary/details and UTF-16 length.
- One activity message with paced edits, 100-event burst coalescing, separate
  conversational bubbles/drafts, initial/edit 429 delays and uncertain-send handling.
- Large write content cannot hide the path; a long activity flood wait cannot hold
  a completed answer beyond the two-second activity finalization grace.
- Stream failure uses safe errors; cancellation during an activity send or throttle
  closes the source, joins requests, and leaves no sender tasks.
- Existing steering, abort/reuse, Guest isolation and confirmed teardown tests pass.

Command: `.venv/Scripts/python -m pytest -q --basetemp=.runtime/remote-ui-final`.
`git diff --check` also passed. An independent code review identified the long
activity flood-wait delay; its regression was observed RED then GREEN with the
bounded finalization fix. No other actionable findings were reported.
Tests ran outside the execution sandbox: Windows asyncio's socketpair setup hangs
inside that sandbox before the test body. No application event-loop workaround was
introduced. No token, raw trace, owner transcript or session was added to Git.

## Remaining live acceptance

No authenticated OMP prompt or real Telegram delivery was performed for this change.
A running Capri process must load this checkout after restart. From the paired
owner's private DM, ask for a harmless native read or command. Verify that OMP chooses
and executes the tool, available thinking and tool activity update one message,
and normal Capri bubbles remain separate. Also check `/stop` during a running tool.
The automated tests establish event/UI behavior, not authenticated live acceptance.

## Presentation follow-up

At the owner's request, removed the fixed activity heading and thinking icon.
The existing rendering regression now checks the unadorned reasoning text; delivery
tests identify their fixture text without depending on a production UI heading.
Both owner and Guest prompts request plain-text prose without Markdown styling,
including exposed reasoning summaries, while preserving literal code and file data.
