# Capri Guest Live Progress Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, with TDD.

**Goal:** Replace the fixed Guest placeholder with public model progress, a dot suffix, and a clean final replacement.
**Architecture:** GuestEngine emits narrow typed public/lifecycle events. ProgressView keeps interim/current/final separate. GuestService owns one paced answer/edit path and a timer that works even while OMP is silent. Completed prompt_result, not an individual tool-bearing turn_end, seals the final.
**Tech Stack:** Existing Python, official omp_rpc, aiogram.
**Spec:** User's Capri Guest live progress message, 2026-10-25.

## Global Constraints
Guest only; DM delivery unchanged. No reasoning/tool arguments/results exposed. One answerGuestQuery attempt, same inline id for all edits, no normal send/fallback. Existing isolation, owner auth and concurrency remain. No commits/push.

## Review Focus
Silent startup; multiple model/tool steps; final immediately after progress; failed answer acknowledgement; cancellation during silent wait. Tests cover each.

### Task 1: Native guest lifecycle
- [x] Add failing tests for public text, message snapshots, tool boundaries, final completion, no thinking/args.
- [x] Emit GuestEvent(kind,text) from SDK callbacks; final only after completed prompt result, never a tool-bearing assistant tail.
- [x] Run focused engine tests.

### Task 2: Progress view and paced delivery
- [x] Add failing tests for accumulated interim, final replacement, silent dot animation, first text before fallback, rate pacing, errors/cancel cleanup.
- [x] Add guest_progress.py for bounded cleaned public text and dot frames.
- [x] Start stream before answer; after 1.2s without public text answer with dot; serialize answer and edits with 0.9s pacing, including final. Timer never cancels pending SDK read.
- [x] Always attempt final replacement; never infer final delivery from progress. Stop timer/read on failure/cancel.
- [x] Run focused and full suites, inspect DM diff.

### Task 3: Review and deployment verification
- [x] Fresh review, fix important findings with RED/GREEN.
- [x] Record evidence and limitations, restart existing bot, verify capability/poller startup. Human guest UX acceptance remains explicit and pending after restart.
