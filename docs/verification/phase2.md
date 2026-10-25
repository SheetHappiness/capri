# Phase 2 conversational-flow spike

Date: 2026-10-25. Scope: streamed public-text durable bubbles and native OMP steering only.
Existing Phase 0/1 evidence remains in spikes.md. No commit or push was performed.

## Research before implementation

- OpenClaw: https://docs.openclaw.ai/concepts/streaming and
  https://github.com/openclaw/openclaw/blob/main/src/agents/embedded-agent-block-chunker.ts
  (read on this date). Its append/drain buffer distinguishes source consumption from delivery;
  paragraph/sentence boundaries and fenced-code safety inform this smaller implementation.
  This is an independent small Python implementation, not a port of the full Markdown parser.
- OMP: local official SDK source at release commit
  `45c35e40c46166dc726ccc52f5d27f40f2449f99`, `sdk/python/omp-rpc/src/omp_rpc/{client,_wire}.py`:
  `steer(message)` submits a concurrent ordinary command; it does not take the
  `prompt_and_wait` lifecycle collector lock. The current upstream RPC docs were also checked:
  https://github.com/can1357/oh-my-pi/blob/main/docs/rpc.md .
- Exact-release agent source (`packages/agent/src/{agent,agent-loop}.ts`) confirms live steering
  and tool-boundary delivery. Capri delegates those semantics to OMP; no classifier or synthetic restart.
- Telegram draft lifecycle: https://core.telegram.org/api/bots/ai describes clearing the temporary
  preview when a normal message arrives. The sender is canceled and joined before durable send,
  then a fresh draft ID is used for the remaining suffix.

## Implementation and local evidence

- `bubbles.py`: append-only suffix, configurable min=140 / soft_max=800; paragraph then sentence
  then whitespace boundaries, excluding backtick and tilde fences. No idle-commit heuristic yet.
- `telegram.py`: acknowledged early sends consume only their source prefix. Final sends only the
  remaining suffix, with no empty extra message when everything was already committed.
  Preview throttling/retry behavior, safe errors, and the Phase 1 truncation fallback remain.
  An indivisible oversize span (including a code block) is visibly truncated at final delivery;
  this spike does not implement synthetic close/reopen fences or hard token splits.
- `app.py`: one response consumer, FIFO pending deque, 500 ms trailing debounce; each burst is joined
  with blank lines in arrival order for one steer. Slow ACKs serialize before subsequent bursts or
  fallback prompts. Definitely unavailable steer queues intact; an uncertain ACK produces a safe
  notice and is never silently retried (avoiding duplicate user input).
- `engine.py`: SDK steer is independent of the prompt lock. Explicit abort keeps the session usable;
  actual turn/process failures still require restart as in Phase 1. No new OMP session is created.
- Baseline before changes: 16 passed. New early-commit and steering tests failed before implementation.
  Slow-ACK duplication, abort poisoning, and source cleanup regressions were reproduced failing and fixed.
  Final local suite: 28 passed, including all 16 original tests, using `.venv/Scripts/python -m pytest -q`.
  External services are replaced only at the SDK/Telegram edges. Model/tool scenarios here are
  synthetic adapter checks, not evidence of live provider steering during web execution.

## Live Telegram acceptance: PENDING OWNER TEST

Computer Use was stopped by the owner with Escape; the owner then chose to test manually.
No Phase 2 Telegram response or consumed steer is claimed as observed yet.
The ignored `.runtime/phase2-live.py` runner records API ACKs, public delta lengths, prompt results,
steer ACKs and user-message event roles, session identity and shutdown survivors, without message text.

Suggested manual checks in @Capriompbot:

1. Ask for a long answer in several substantial paragraphs. Observe a durable first message while
   the next draft is still growing. The log must show its `sendMessage` ACK before `prompt_result`
   and further public deltas afterward. A short reply should persist exactly once.
2. During generation, send a clarification (for example: `Уточнення: лише для Windows`). It should
   be acknowledged via steer and reflected in the answer without a new prompt/session.
3. During a real web search, send a restriction such as `Лише офіційні джерела`. Check consumption
   at OMP's supported boundary. Multiple rapid messages must retain their order.
4. `/stop`, then a new question: session remains usable. Already committed bubbles remain visible.

Thresholds are proposed defaults, not validated UX measurements: 140/800 characters, 750 ms draft
cadence, 500 ms input debounce. Record actual timings and owner UX feedback after the manual trial.
