# Native OMP permission control

> Use superpowers:executing-plans inline, with focused TDD and independent review.

**Goal:** Owner-only `/permission` reads and changes OMP's standard approval mode, persisted across restarts. Approval decision buttons are the next step, outside this change.

**Native contract:** Pinned OMP has no approval-setting RPC and its `/settings` is TUI-only. Use `omp config get/set tools.approvalMode --json` with Capri's isolated environment. No model prompt, no shadow permission database, no custom approval decisions.

**UI:** `/permission` reads OMP and shows its mode plus four standard mode buttons. `/permission <mode>` also works. Callbacks require the paired owner in a private chat. Use only the canonical `/permission` spelling. A busy turn rejects configuration changes rather than silently steering them into the model.

**Persistence/isolation:** Keep OMP's global `agent/config.yml` intact. Put Capri's mandatory model/discovery isolation settings in a maintained `--config` overlay used by owner and Guest. OMP validates and saves the approval setting itself. Before a change, reap the idle owner child under the existing runtime lock; the next owner message resumes the same session and loads the saved policy. Guest remains web-only and uses a fixed native yolo mode so owner settings cannot change its existing delivery behavior.

**Lifecycle:** Serialize CLI control with owner/Guest handoffs. Join a cancelled native config worker, including save/readback and confirmed owner teardown. Never restart after unconfirmed teardown. Native config commands have a subprocess timeout and use argument arrays, not a shell. Errors do not echo private stderr/config data.

## Tasks

- [x] Tests first: native CLI argument/env contract and persistence; reject invalid modes; readback/errors; config survives owner restart; Guest retains isolation.
- [x] Implement bounded native config operations and the shared isolation overlay.
- [x] Tests first: runtime busy/idle handoff, failed teardown and cancellation; owner-only command/callback routing with no model prompt or steering.
- [x] Implement the owner menu, mode callbacks and direct command form.
- [x] Probe the real pinned CLI in isolated storage, without auth/model calls or Telegram sends.
- [x] Full suite, whitespace check, independent review; update README/evidence and restart the already-authorized bot.

## Review focus

Persistent configuration must not be overwritten on startup; overlays must preserve owner/Guest discovery isolation; a changed mode cannot leave the old owner child serving turns; cancellation must not abandon a config save or release the runtime lock early; only the paired owner can submit an allowed mode. No native approval dialog bridge is claimed yet.

## Results

- 231 tests passed; git diff --check passed.
- Real isolated CLI/RPC probes passed without model calls or Telegram messages.
- Review finding fixed with RED-to-GREEN regression: detached permission handlers are cancelled and joined before owner/bot close.
- Implementation call: stop idle owner before saving, preventing a stale child's settings save from racing the native config write. The next DM retains lazy session resume.
- Scope: /permission first; approval-decision buttons remain the next step.
