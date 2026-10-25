# Explicit bubbles — 2026-10-25

Implemented locally from `docs/superpowers/plans/2026-10-25-explicit-bubbles.md`.
No dependencies, tools, steering/FIFO code, owner gates or session storage changed.
No commit, push, bot restart or live Telegram messages were performed for this change.

## Behavior

- Exact case-sensitive `<bubble>` commits the pending visible text, even one word.
- Each commit waits for Telegram acknowledgement before consuming source text and rotating
  the draft ID. Only the uncommitted suffix is previewed. No duplicate final text or empty sends.
- Split marker prefixes are withheld from drafts. An incomplete reserved prefix is dropped at
  successful stream end; a nonmatching continuation is restored as literal text.
- Markers within inline backticks and backtick/tilde fences stay literal. Open code remains
  literal conservatively. The exact token in prose outside code is reserved transport syntax.
- Without a marker, automatic chunking starts at 800 pending visible characters. It uses
  paragraph -> sentence -> whitespace, candidate minimum 140, and respects the UTF-16 limit.
  Indivisible oversized spans keep the existing visible truncation fallback.
- Draft cadence remains 750 ms and steering debounce 500 ms. No inter-message sleeps.
  Several messages in a single delta can therefore arrive quickly.
- Official SDK `append_system_prompt` adds conversational instructions while preserving
  OMP's built-in prompt. Existing session resume, Luna and web-only isolation remain intact.

## Automated evidence

`.venv/Scripts/python -m pytest -q`: **62 passed in 2.81s** on the existing Windows environment.

Observed RED -> GREEN for missing parser, eight delivery behaviors, appended prompt, and
whitespace-only bubbles found during review. Parser tests cover all marker splits,
character-by-character streams, exact spelling, partial/nonmatching tokens and code runs.
Delivery tests demonstrate an acknowledged first short bubble before the next source delta,
multiple commits, sanitized suffix drafts, size fallback, literal code, UTF-16 truncation,
preview retry-after, cancellation during/after commit and uncertain-send cleanup.
The original steering model/tool fakes, debounce/FIFO and owner/isolation tests still pass.
Two prior paragraph fixtures were enlarged beyond 800 to retain early size-fallback coverage;
the cancellation-at-send fixture now explicitly commits a short bubble.

These are local synthetic adapter tests, not native model compliance or live Telegram proof.
SDK option support was also checked against the installed exact-release source
`45c35e40c46166dc726ccc52f5d27f40f2449f99` (`client.py` lines 468, 1855-1856).

## Review and decisions

Author review only; no subagents were delegated, as specified in the plan. Review found
that whitespace between repeated markers could produce an invalid empty Telegram message;
a failing regression test now covers the fix. No deferred code findings.
Work stayed in the existing unborn checkout, retaining its untracked baseline.
`git diff --check` has no tracked diff here; changed files were separately checked for
trailing whitespace. The implementation ledger remains ignored under `.runtime`.

## Remaining owner acceptance

The previously running bot was left untouched. After a coordinated restart with the same
session and only one polling process:

1. Inspect `get_state().system_prompt` for the appended instructions on the resumed session.
2. Request several very short messages and observe the first durable bubble while generation
   continues. Check a single short reply, long explanation and literal code token example.
3. Add clarification during generation; confirm native steer consumes it without session reset.
4. Record actual model boundary choices and observed UX thresholds separately from these tests.

Future sticker/PC tools and waiting to send “Ауууу” are outside this implementation.
A future side-effecting tool requires a pre-action barrier that waits for Telegram send ACK;
the prompt alone cannot enforce ordering between tools and bubbles.
