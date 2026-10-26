# Native OMP /permission control

The paired owner can read/select standard OMP approval modes with `/permission`,
its mode buttons, or `/permission <mode>`. No owner message is sent to the model
or native steering for this command. No separate Capri permission store or policy
evaluator is introduced. Approval decision buttons were subsequently connected;
see [native approval verification](approval-buttons.md).

## Pinned contracts inspected

OMP/SDK revision: `45c35e40c46166dc726ccc52f5d27f40f2449f99`.

- `modes/rpc/wire/commands.ts` has no config-setting RPC.
- `slash-commands/builtin-modes.ts` exposes `/settings` only to the TUI.
- `commands/config.ts` and `cli/config-cli.ts` provide native JSON `config get/set`
  with schema validation and persisted global settings. Set results report saved
  values and overrides; Capri rejects an unexpected/overridden result and reads back.
- `tools/settings.ts` owns the four standard mode values; default is yolo.
- `main.ts` starts config-file watching in RPC mode. Capri nevertheless stops the
  idle owner before saving, then lazily resumes its existing session, so no turn can
  begin in an old child while a policy reload is still pending.

Mandatory Capri settings moved from global-config replacement to a separate native
`--config` overlay shared by owner/Guest. Owner permission selection lives only in
OMP's global config. Guest remains web-only with an explicit native yolo override.

## Verification

Focused regressions cover persisted config preservation, native CLI args/environment,
invalid modes, malformed/overridden results, subprocess failure/timeout, runtime
busy checks and confirmed child teardown, owner-only private command/callback
authorization, cancellation during save and restart-safe application shutdown.

Independent review identified aiogram's detached update-handler shutdown race.
A failing regression demonstrated owner/bot closure before permission completion.
The fix tracks and cancels/joins owner command/callback handlers before closing
the engine or bot session. Native config saves and teardown are joined even under
repeated cancellation. No other permission-specific findings were reported.

Real pinned OMP CLI, isolated `.runtime/permission-cli-probe` storage, no credentials
or model calls: default yolo → set write → fresh Engine reads write → restore yolo.
Real pinned RPC child, isolated `.runtime/permission-rpc-probe` storage: isolation
overlay accepted, Luna selected, native tools exposed, separately saved write mode
preserved, and `stop()` returned True. No owner transcript or live config was changed.

Final automated command:
`.venv/Scripts/python -m pytest -q --basetemp=.runtime/permission-final`.
Tests require execution outside the sandbox's Windows asyncio socketpair restriction.
`git diff --check` is also required.

## Live Telegram check

After loading this checkout, send `/permission` in the paired owner's DM. Verify
the mode menu, select a mode, and reopen it to see the value supplied by OMP.
Choose always-ask to test native approval cards, or yolo for ordinary tool execution.
The automated/native probes do not establish real Telegram button delivery.
