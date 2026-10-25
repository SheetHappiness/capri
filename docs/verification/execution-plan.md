# First working milestone: execution plan

Scope: only Phase 0 feasibility and Phase 1 owner DM. Earlier v0.1 drafts are historical, not authorization for additional features.

1. Phase 0 sequential: download pinned OMP 18.12.6 into `.runtime/`, verify SHA-256; obtain official SDK at release commit 45c35e40c46166dc726ccc52f5d27f40f2449f99; use Python 3.14 local virtual environment. Exploratory scripts under `.runtime/`; record commands/results and exact blockers in `docs/verification/spikes.md`.
2. Prove RPC startup/state, streamed events, host-tool roundtrip, clean shutdown. Use official SDK only.
3. Use OMP supported isolated configuration; enumerate effective tools/discovery. Authenticate with real OMP flow, select gpt-6-luna explicitly, prove streamed answer and actual OMP search with URLs/provider evidence. Stop at any unmet requirement; Phase 1 remains untouched.
4. Only after Phase 0 passes: add `pyproject.toml`, `src/capri/{__init__,app,cli,config,engine,telegram}.py`, `tests/test_engine.py`, `tests/test_telegram.py`, and a short launch README. Dependencies: matching official omp-rpc, aiogram 3.31.0, pytest. No custom protocol/provider/search implementation.
5. Tests before production code: public-text filtering, model selection without fallback, session persistence, child death/shutdown; explicit nonce owner pairing, reject outsiders, throttled accumulated drafts before completion, one final message, visible errors. Use deterministic fake SDK/Telegram edges; run full suite.
6. Live acceptance: owner pairs through local nonce; fresh-information DM invokes OMP search, yields visible draft updates before completion and one final persisted response; restart preserves OMP session; child death gives visible error. Record observed evidence separately from synthetic tests.

No BubbleComposer, guest, memory, scheduler, media, npm packaging or future-only abstractions. Keep OMP canonical conversation state; module boundaries permit later planned features.
