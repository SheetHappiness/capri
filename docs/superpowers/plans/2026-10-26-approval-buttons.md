# Native OMP approval buttons

Implement inline with TDD and independent review. This continues the authorized
permission iteration: owner-only Telegram cards with one row `[Once] [Session] [Deny]`.

Native pinned contract: OMP's RPC extension UI emits `select` with a title beginning
`Allow tool: ` and exact option strings. `send_ui_value(id, option)` sends the native
choice. Enable owner RPC UI (retain disabled external extensions); Guest stays headless.
Map only choices actually supplied by OMP. For cached file grants, Session selects
the exact target grant when available, otherwise the native directory grant, with
the native scope shown. Never offer persistent Always or manufacture a grant.

- [x] RED: SDK UI subscription/response, one-shot pending request IDs, abort cleanup.
- [x] Enable owner UI; forward supported native requests through the existing stream.
- [x] RED: card row, native choice mapping, owner/chat/message binding, duplicate/stale
  clicks, failed delivery, unsupported dialogs, oversized prompts, turn cleanup.
- [x] Add a bounded Telegram approval view; route cards separately from activity and
  bubbles; callbacks bypass the active runtime lock and use the SDK concurrent reply.
- [x] Preserve cancellation/shutdown joins; update /permission text and docs.
- [x] Full suite, native acceptance probe if feasible, independent review, restart bot.

No policy evaluator, command allowlist, Hermes logic, or custom grant persistence.
Default/saved mode stays unchanged. Failed/uncertain card delivery declines once;
no automatic retry sends a duplicate approval card. Source cleanup invalidates buttons
before abort. Provider safety prompts and explicit per-call prompts expose Once/Deny
only. If the full native prompt exceeds Telegram's limit, decline rather than approve
an additional truncated representation.

## Results

- 239 tests passed; git diff --check passed.
- Real authenticated native OMP acceptance passed through a fake Telegram transport: Once writes, Deny does not write, Session writes and suppresses the next same-tool prompt; child stop confirmed True.
- Review cleanup finding reproduced RED then GREEN: card invalidation runs even when source close/abort raises.
- UI choices stay native; Session scope is displayed; no persistent Always grant exposed. Telegram client layout/delivery still requires owner acceptance.
