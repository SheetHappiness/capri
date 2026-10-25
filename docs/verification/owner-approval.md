# Owner native OMP approval → Telegram

## Implemented scope

- Private paired Owner only: separate plain-text command/cwd message with
  `Дозволити один раз` / `Відхилити` buttons.
- Current tools, `approvalMode: write`, and exact inspection allowlist unchanged.
- Native OMP remains the policy/execution authority. Only the exact one-call
  native select label is returned; session/remember choices are never offered.
- Request tokens are random, memory-only, message/chat/Owner-bound and single-use.
  There is no permission persistence across restart.
- Deadline is at most 60 seconds and bounded by the remaining 180-second turn.
  Missing/uncertain delivery, timeout, /stop, native cancellation, ended turns,
  client replacement and shutdown revoke approvals. Expired buttons cannot act even
  when keyboard removal fails. Keyboard cleanup is best effort, bounded to 3 seconds.
- SDK listener schedules onto asyncio rather than blocking on Telegram. Callback
  handlers do not acquire the prompt/runtime locks.
- Guest retains `no_ui=True` and exactly `web_search`.
- No shutdown/reboot/game launch, computer-use or additional automatic allowances
  were performed or introduced by this change.

## Native protocol characterization

Real pinned OMP 18.12.6 + exact official Python SDK, isolated runtime/work/session:

- `toolcall_end.toolCall` contains completed bash arguments; optional cwd may be null.
- UI request method: `select`.
- Native title for the probe: `Allow tool: bash\nCommand: printf CAPRI_APPROVAL_PROBE`.
- Observed choices: `Approve`, `Approve bash for this session`, `Deny`.
- Listener ran on a non-main SDK thread.
- `cancel_ui_request` denied the probe; `send_ui_value(id, 'Approve')` allowed it.
- Both turns completed and child stop returned True.

The private authentication DB was copied via SQLite backup to an ignored isolated
runtime so neither owner sessions nor the active bot's storage were reused. The
snapshot/work/session directory was removed after native verification and confirmed
child teardown. Sanitized results remain in ignored `.runtime` files; no credentials
or raw traces are tracked.

Pinned native bash approval prompts truncate commands after 2000 UTF-16 code units
and omit cwd. The Engine adapter therefore matches the exact displayed command to
one unique completed bash call and derives cwd from its arguments plus Capri work
root. Missing/ambiguous calls, longer commands, virtual cwd, drive-relative cwd,
alternate streams, unsupported dialogs and unreadable/overlong Telegram content
are refused rather than guessed. A rejected/unverifiable call can produce a short
private explanatory notice, without buttons. Relative filesystem cwd and absolute
Windows cwd (including forward slashes) are supported.

## Automated evidence

Baseline before approval work: **218 passed**.

RED observed before implementation for Engine adapter, Telegram bridge and app
callback routing. Self-review regressions were also observed RED before fixes:
uncertain SDK writes, Windows cwd handling, concurrent child stop, repeated stream
cancellation and repeated app shutdown cancellation.

Final full suite: `.venv/Scripts/python -m pytest -q` → **267 passed**.
`git diff --check` → no whitespace errors (existing line-ending conversion notices).

Tests cover native one-call/deny/cancel mapping, unknown/ambiguous/truncated inputs,
request deadlines, multiple requests, listener responsiveness, duplicate requests,
late answers (even callbacks suppressing cancellation), private callback identity,
message binding, races, uncertain sends, timeout, cancellation/close, failed ack or
keyboard edits, current pairing, oversized/control-character display, app polling
subscription to callback_query, /stop→Guest→Owner handoff, Guest no-UI isolation,
and teardown joining under repeated cancellation. Failed callback acknowledgements
are cosmetic after a valid decision; they cannot repeat the consumed permission.

A real Engine adapter probe additionally executed two harmless shell marker calls:

- Deny: `approval-denied.txt` **did not exist** after the turn.
- Allow once: `approval-allowed.txt` **existed** after the turn.
- Both approval requests presented the expected work directory; confirmed safe stop.

This marker evidence is based on filesystem side effects, not model claims.
Native probe used a programmatic approval callback, not a Telegram button click.

## Follow-up: denial scope and PC-action behavior

Owner live report confirmed automatic git status, one-time approval, explicit denial
and 60-second expiry. The report also exposed an incorrect model refusal: it treated
previous bash denials as disabling shell for the entire conversation, and refused
an unrelated new PC-action request without invoking any tool. Native bash results
for the denied calls were simply `Tool call denied by user: bash` (including the
expired dialog); no persistent tool ban was configured.

The Owner conversation prompt now states that denial/timeout/cancellation applies
only to the specific call, that a fresh explicit Owner request may produce a new
approval, and that PC actions are possible subject to native policy. It forbids
automatic retries, alternate-tool bypasses and claiming success before a tool
result. Disruptive consequences must be explained; force-closing apps/losing
unsaved work requires explicit instruction. Guest prompt/policy are unchanged.

Regression boundary test was observed RED before this prompt change. Follow-up
full suite: **268 passed**. An isolated real-OMP behavioral probe denied one harmless
Python print call, then made a fresh Windows process-list request: both produced
separate approval requests. Both were denied; no process-list command or shutdown
was executed. Confirmed stop True and copied auth/runtime removed. This proves the
fresh-request path in that controlled conversation, not deterministic model behavior
for every historical transcript or permission to perform disruptive acceptance.
The bot was then restarted with the clarified instructions and existing history;
startup confirmed Owner ready, Guest supported, no traceback or isolation failure.

## Deployment and live acceptance pending

After implementation the Owner explicitly authorized restart and interruption of
current work. The previous Capri launcher, worker and its OMP child were stopped;
their termination was verified before launching the updated bot. Startup confirmed
Owner ready, Guest supported, and no traceback or isolation failure. Actual Telegram
callbacks, timeout and /stop still await Owner live acceptance. No simultaneous
second poller was started.

Use only harmless commands for the first pass:

1. `git status` via bash: no dialog.
2. `python -c "print('CAPRI_APPROVAL_OK')"`: check displayed command/cwd, click Allow
   once, verify actual tool output. This command is not in the automatic allowlist.
3. Repeat: a fresh dialog must appear; choose Deny.
4. Request another non-allowlisted command and leave it unanswered: denial after
   at most 60 seconds; old buttons must no longer work.
5. Open a dialog and send `/stop`: no execution, no usable old buttons.
6. Repeat through Guest: no filesystem/shell access and no approval dialog.

To establish denial independently, request a harmless marker-file shell command
and inspect the file afterwards; do not let the model substitute write/edit tools
or retry after denial. Do not use shutdown/reboot as an acceptance test.

PowerShell 7 (`pwsh`) remains absent from this host's PATH; Windows PowerShell
(`powershell.exe`) is present. No installation was performed.

Review was author self-review (no subagent tool), not independent review. The
implementation remained uncommitted until the Owner explicitly authorized committing
and pushing the full change set. This bridge is not a filesystem sandbox and does not protect against
an Owner intentionally rewriting local OMP config, scripts or executables.
