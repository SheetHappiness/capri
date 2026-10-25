# Capri Guest live progress — verification (2026-10-25)

Subsequent ACK, teardown, dedupe, mention and metadata hardening is recorded in
[post-merge hardening](post-merge-hardening.md). Earlier evidence below is historical;
it does not imply deployment or live acceptance of those later changes.

Implemented locally, no commit/push. Production Capri restarted at17:58:53 Europe/Warsaw with supports_guest_queries=True; one combined DM/Guest poller is running.

## Behavior

- Fixed “Думаю…” removed from production Guest Luna path. The separate historical Telegram transport probe is unchanged.
- First public assistant text answers the Guest query; if none arrives within1.2s, answer with `·`.
- One inline message shows accumulated model-authored commentary and dot suffix (`·`, `··`, `···`, `··`, `·`). No thinking deltas, tool arguments/results, or synthetic tool status lines.
- Native assistant message snapshots and tool boundaries distinguish current/interim text. Individual OMP turn_end can be a tool-bearing step; the prompt's own completed result supplies an independent final.
- Final replaces all progress, including when final text differs from the streamed preview. Completed length-limited assistant text is preserved; toolUse/error/aborted tails are excluded.
- Answer and edits use one0.9s pacing path, including final. Progress FloodWait respects backoff; final retries an explicit429 once on the same inline id. Unknown answer acknowledgement is never retried.
- After hardening, final success requires ACK. Generic network/server/unknown edit
  outcomes are uncertain and never retried blindly; failed progress can still reach final.
- Final is published before process teardown; shared runtime lock remains held until cleanup, and unconfirmed child teardown still blocks future OMP children.
- UTF-16 budget includes the spinner and visible truncation. No ordinary sendMessage or DM fallback.
- DM engine, bubble flow, steering and delivery are unchanged by this refinement.

## Files in this refinement

- src/capri/guest_engine.py — typed public/lifecycle GuestEvent, final snapshot from completed PromptTurn.
- src/capri/guest_progress.py — new bounded current/interim/final view, BubbleProtocol cleaning and animated suffix.
- src/capri/guest.py — delayed first answer, paced timer, independent final path, cancellation/read cleanup, explicit edit backoff.
- src/capri/prompt.py — Guest-only encouragement of brief useful public pretool commentary; no artificial pauses.
- tests/test_guest_engine.py — lifecycle, privacy and completed final cases; existing isolation tests adapted to typed events.
- tests/test_guest_progress.py — new progress/final, animation/pacing, failures, truncation and review regressions.
- tests/test_guest.py — guest fake adapted to new event contract and deferred first-answer behavior.
- README.md — current Guest progress behavior.
- docs/superpowers/plans/2026-10-25-guest-live-progress.md — implementation plan.
- docs/verification/guest-live-progress.md — this report.

Earlier Guest thread/probe implementation remains uncommitted separately in the same checkout.

## Automated verification

- RED confirmed for native lifecycle, missing progress/final semantics and long suffix budget.
- Final review reproduced three final-loss cases before fixes: length stop reason, final behind slow/erroring teardown, final429 discarded. Regression tests passed after fixes.
- Focused:48 passed in3.05s (guest_progress, guest, guest_engine, guest_app).
- Full suite:158 passed in4.11s.
- git diff --check clean.
- git diff --exit-code -- src/capri/telegram.py src/capri/engine.py clean.
- Independent read-only reviewer found two Important issues; both fixed. Reviewer's own test attempt hit restricted pytest temporary-directory setup errors, so verified counts above come from the successful primary runs.

## Actual OMP integration (not a synthetic Telegram acceptance pass)

Ran the real official OMP child with authenticated gpt-6-luna, effective tools verified exactly web_search, and a recording Telegram transport. Repeated after review fixes.

Observed lifecycle:
start → message → tool_start → tool_end → start → message → final

Both runs:1 answer attempt,8 edits; delivered terminal text exactly matched cleaned final model snapshot. Owner session pointer and pointed transcript SHA-256 and nanosecond modification times unchanged. Child stop confirmed. Diagnostic OMP session directories were cleaned after stop. No Telegram message was sent by this diagnostic.

## Telegram live status

Startup observed:
```
Guest Mode supports_guest_queries=True
Capri @Capriompbot ready for owner5169573014
2026-10-25 17:58:53 Start polling
```

Earlier Guest receipt/edit and persistent thread continuity were owner-confirmed. New progress UX acceptance is PENDING: owner has been asked to summon Capri in a human chat, observe real commentary/dots, then confirm all progress is replaced by final. No new Telegram UX pass is invented.

## Implementation decisions and limits

1. Completed prompt result is terminal authority because turn_end can accompany tools. Cost: wait for prompt completion before final classification.
2. Final also observes0.9s pacing. Cost: up to one interval of added final latency.
3. Guest prompt encourages useful public commentary. Luna may choose silence; dots cover it without invented logs.
4. Deliver valid completed final before teardown, retain lock through cleanup. Unsafe cleanup requires restart before another OMP turn.
5. Retry a final edit once after explicit429. Repeated Telegram rejection can still prevent final display; no extra messages/fallback are sent.

## References inspected

Hermes is a UX reference only; its gateway architecture was not copied. Read the five user-pinned sources at d05095663342556788cf2a198bfa7844cc7968ab:

- [run_turn.py](https://github.com/NousResearch/hermes-agent/blob/d05095663342556788cf2a198bfa7844cc7968ab/gateway/run_turn.py): independent interim/final delivery, accumulation and cleanup.
- [stream_consumer.py](https://github.com/NousResearch/hermes-agent/blob/d05095663342556788cf2a198bfa7844cc7968ab/gateway/stream_consumer.py): streamed/final reconciliation.
- [display_config.py](https://github.com/NousResearch/hermes-agent/blob/d05095663342556788cf2a198bfa7844cc7968ab/gateway/display_config.py): progress settings.
- [messaging guide](https://github.com/NousResearch/hermes-agent/blob/d05095663342556788cf2a198bfa7844cc7968ab/website/docs/user-guide/messaging/index.md): real interim commentary separate from tool progress.
- [Telegram pacing tests](https://github.com/NousResearch/hermes-agent/blob/d05095663342556788cf2a198bfa7844cc7968ab/tests/gateway/test_telegram_shared_outbound_budget.py): shared outbound pacing.

Pinned installed omp_rpc client/_wire/protocol source was inspected for message lifecycle, StopReason and PromptTurn final snapshot semantics.

## Follow-up: restore incremental Guest text (2026-10-25)

Owner confirmed the progress UX works, but reported Guest text no longer appeared incrementally. DM was explicitly confirmed unaffected.

Root causes reproduced RED:
- Guest consumed model events in the same coroutine that awaited Telegram answer/edit calls. Slow transport held token consumption, unlike the independent DM draft reader.
- Long accumulated commentary occupied the entire preview budget and could hide new answer tokens.

Fix: independent continuous model reader updates the view while the single paced transport coroutine sends current snapshots. Existing 0.9s budget, one answer attempt, final replacement, privacy and cleanup remain. When previews overflow, older commentary yields space to current text.

Files changed in this follow-up: src/capri/guest.py, src/capri/guest_progress.py, tests/test_guest_progress.py, tests/test_guest.py. DM engine/delivery unchanged. No commit/push.

Regression tests assert new tokens are consumed while answer transport is blocked, growing text is visible BEFORE model completion, and old commentary cannot hide current text. The previous test fixture's 1ms startup delay was replaced by1s to avoid Windows scheduling races; explicit short-delay animation tests remain. Full suite:160 passed in4.05s; git diff --check clean.

Real authenticated Luna, recording transport with250ms response delay:
-1043 public text deltas.
-One answer attempt,9 edits.
-Seven growing previews before completion, visible lengths271,647,1090,1511,1940,2377,2765.
-Terminal text matched cleaned model final snapshot.
-Owner pointer/transcript bytes and nanosecond mtimes unchanged; child stop confirmed.

This proves real model incremental delivery through the Guest service with recording transport. User confirmation in the real Telegram client after this follow-up remains pending.

## Telegram native animation diagnosis (2026-10-25, after owner reported Guest still differs from DM)

Owner reports DM works, Guest still does not show expected token streaming. Production logs confirm Guest answer/edit ACKs; ACKs alone do not prove the Telegram client's visual behavior.

Inspected only assistant metadata, not prompt/reply contents, for the latest production Guest run: terminal assistant220 public characters, total duration1591.94ms, first text964.74ms; the remaining generation window was approximately627ms. With0.9s edit pacing, this short answer can complete between preview ticks and appear as one final replacement.

Official Bot API and installed aiogram distinguish transports:
- sendMessageDraft uses private chat_id and draft_id; updates to the same draft are explicitly animated.
- answerGuestQuery returns a guest/inline message; editMessageText edits via inline_message_id and has no draft_id/native animation option.
- Guest chat ids cannot safely be reused for ordinary bot-chat draft/send calls.

Sources: https://core.telegram.org/bots/api#sendmessagedraft and https://core.telegram.org/bots/api#editmessagetext . Consequently, recording-transport incremental previews establish backend chunk updates, not DM-style native animated typing in the Telegram client. Previous completion language overstated that equivalence. No further speculative code changes were made for this diagnosis. Awaiting owner's distinction between no intermediate text at all and chunk replacements without smooth typing. Bot remains running.
