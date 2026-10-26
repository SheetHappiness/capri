# Native approval buttons

Owner-only approval cards expose `[Once] [Session] [Deny]` on one row. Session is
shown only for a grant the native request actually offers. OMP remains the policy
and grant authority; no custom command classifier or approval persistence is added.

## Contracts

Pinned OMP/SDK: `45c35e40c46166dc726ccc52f5d27f40f2449f99`.
`tools/approval.ts` supplies a native select title/options; `modes/rpc/rpc-mode.ts`
forwards it as `extension_ui_request`. The official SDK's `on_ui_request` and
`send_ui_value(id, exact_option)` carry the request/reply. Owner `no_ui=False`
enables the runner's RPC UI; external extensions remain disabled. Guest stays headless.

Cards are separate from bubbles and activity. Random callback tokens bind the
paired owner, original chat/message, native request and offered choice. Each request
can be answered once. SDK pending IDs and card tokens are invalidated on abort/end.
Source cleanup aborts/joins OMP before joining bounded keyboard cleanup. Unknown UI
dialogs are cancelled; oversized or failed/uncertain card delivery declines.

## Native acceptance

The bot poller was temporarily stopped to avoid two children sharing the auth root.
An isolated session/work directory and a native always-ask launch override were used;
the owner conversation pointer and saved policy were unchanged. A fake Telegram
transport exercised the actual card callbacks against authenticated native OMP.

- Once: native write to once.txt prompted with Once/Session/Deny; approved file content
  matched the requested marker.
- Deny: native write to denied.txt prompted; no file was created.
- Session: native write to session-one.txt prompted and succeeded.
- Same child, subsequent write to session-two.txt: succeeded with no second prompt.
- Official child `stop()` returned True.

Only harmless private probe files were used. No raw transcript, credentials or traces
were added to Git. This establishes native OMP execution and callback semantics,
not real Telegram client layout/delivery.

## Automated checks

Regressions cover native one-shot responses, abort invalidation, offered choices,
owner/chat/message authorization, duplicate/stale callbacks, uncertain/oversized
delivery, full flow through the active runtime lock, separate bubbles, and `/stop`.
Independent review found that failed source teardown could skip card cleanup.
A regression reproduced it before the fix; card cleanup now runs in a finally
block even when abort/stream close raises. Native IDs were already invalidated.
One unrelated Guest test encountered WinError 5 replacing a temporary file during
a full run; both title-listing variants passed an isolated recheck without code changes.

## Telegram acceptance

Send `/permission always-ask`, then ask Capri to create a harmless test file. Verify
one row of buttons, click Once, and check that execution continues. Repeat with a
new file and Deny; then try Session and another write. `/stop` must make old cards
unusable. Use `/permission yolo` to restore ordinary no-prompt behavior if desired.
