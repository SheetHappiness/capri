# Guest transport verification

Scope: Tasks 1 and 2 transport code. Explicit Bot API call, malformed pairing refusal and simple
process-local seen set implement the user's plan review. No Engine/DM source
changes, guest model calls or OMP integration.

Automated RED/GREEN: 11 initial handler cases failed on absent module then passed;
17 additional lifecycle/CLI cases failed on absent launcher/CLI support then passed.
Focused result: 28 passed. Full suite: 94 passed in 3.00s. Baseline existing suite:
66 passed. git diff --check passed. Independent read-only reviewer found no
actionable Task 1 issues; Task 2 behaviors and live delivery were not judged.

Live gate 1: PASS following the second test window and owner confirmation.
On 2026-10-25 at 16:33:31 Europe/Warsaw, the real Bot API reported
supports_guest_queries=True for @Capriompbot. Probe logged
allowed_updates=['guest_message'] and started polling. During a one-minute owner
test window no guest update arrived; no answer attempt/ACK or visible Guest OK
was observed in that first window. It is unknown whether an owner test was actually sent during this
window; this is not evidence of a Telegram delivery defect. No synthetic update
or model call was used for live acceptance.

Second window: at 16:38:22 startup again confirmed supports_guest_queries=True
and allowed_updates=['guest_message']. At 16:38:42.120 the handler logged
authorized, at 16:38:42.295 answer_ack; Update 409541877 handled in 174 ms.
The owner subsequently confirmed `Ghuest ok`. This proves an authorized real
guest reply was visible. Chat type/membership were not independently observed;
do not claim all chat/client combinations passed.

Task 2 RED/GREEN: new tests initially failed on absent phase/edit behavior;
focused 36 passed, full suite 102 passed in 2.89s; diff check clean.
Live gate 2: PASS for the owner-confirmed edit flow. At 16:46:43.503 Europe/Warsaw
the handler logged authorized, at 16:46:43.608 answer_ack, and at 16:46:45.694
edit_ack. Update 409541878 completed in 2192 ms. The owner confirmed
`Ghuest OK final працює`. One guest result was answered, then edited by its
returned inline_message_id. No model was involved. Separate reply-to-text and
reply-to-bot variants and owner DM round-trip after restoration have not been
visually verified; do not infer their success from this test.

Independent read-only Task 2 review found no actionable findings. It did not
verify live edit delivery itself or real polling shutdown with an active handler.
The live handler had completed before the probe was stopped.

No claims of live success based on mocks. Restore the normal DM poller after each
probe window; record the observed capability, delivery stage and restoration here.
Both probe phases are now stopped; normal DM launcher was restarted after the
successful second gate. Guest functionality is still an opt-in transport probe,
not integrated with the default DM launcher or Luna.
