# Owner native OMP approval in Telegram

## Approved scope

The owner approved a first version with Telegram buttons for native OMP approvals,
keeping the existing automatic allowlist. Individual programs/games may be added to
that allowlist later only by explicit owner authorization. Work stays on main,
uncommitted, with no push. This does not authorize changing live PC state as an
acceptance test (shutdown, reboot, launching games).

## Approach

Use the pinned official SDK's UI request/response channel; OMP remains the
permission authority. Do not implement a shell permission engine or host tools.
Alternatives considered: individual PC-action tools require new capabilities;
wide shell allow patterns remove the approval boundary. Neither is selected.

Pinned OMP sends approval as a `select` UI request titled `Allow tool: bash...`,
with choices `Approve` (or `Approve Once`), optional session choices, and `Deny`.
Reply only with the exact one-call label or denial/cancellation. Never expose or
send session/remember grants. Owner must have UI enabled; Guest keeps no_ui=True.
Do not use SDK install_headless_ui: it immediately answers rather than defers.

## User-visible behavior

A separate private Owner message shows the command and effective working directory
as plain text, with `Дозволити один раз` and `Відхилити`. It does not enter the model
transcript and does not replace streamed conversational text. Current automatic
inspection commands continue without a dialog. Other commands, including shutdown
and reboot, require a fresh click per call. Show this is permission to execute the
command, not a guarantee the command is safe.

Native bash approval text truncates commands at 2000 characters and omits cwd.
Capture completed native tool-call arguments and correlate conservatively with
native UI requests; never approve a truncated, missing or ambiguous command.
Do not display misleading cwd or approve an unseen command. If correlation cannot
be made safely, deny with an explanatory Owner notice, not a guessed association.

## Security and lifecycle

Only the paired Owner may approve from their private chat and from the actual
approval message. Use random per-request callback tokens, bound to a client/run
and message. No raw command, credentials, SDK IDs or remembered grants in callback
data. First valid click consumes the request; duplicates and stale clicks do nothing.

Default deadline: 60 seconds, bounded by the enclosing 180-second turn deadline.
Timeout, failed/uncertain send, unsupported dialog, SDK cancellation, /stop,
turn completion/failure, client replacement, runtime handoff and shutdown all revoke
pending approvals and fail closed. Expire callbacks before attempting UI cleanup;
failed keyboard edits must not leave usable permissions. Reconnection does not
restore approval tokens. Do not retry uncertain approvals or RPC responses.

The SDK listener thread must never wait for Telegram: schedule onto the event loop.
Callback handling must stay responsive while a turn holds runtime/stream locks.
Never wait for the prompt lifecycle lock to answer UI. Guest has no approval bridge
and remains physically web_search-only.

## Verification / non-goals

TDD for bridge, Owner SDK integration, callback authorization and cleanup; full
pytest suite and native RPC characterization. Controlled live test uses harmless
commands and a marker file to distinguish actual denial from a model refusal.
No browser/game automation, computer-use, persistent grants, arbitrary native UI
forwarding, shell-wide allowance or new dependencies. No automatic bot restart
until tests pass; preserve active work and never force-stop active OMP.
