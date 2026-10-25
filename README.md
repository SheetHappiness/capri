# Capri: first working milestone

Windows x64 / Python 3.14, official OMP Python RPC SDK, aiogram long polling.
One explicitly paired owner, private text, throttled live drafts and streamed durable bubbles.
Owner-only Telegram Guest Mode uses separate persistent chat-scoped Luna threads.
OMP owns the conversation and persistent session. Its existing Codex search is pinned to Luna.

## Run this verified checkout

The local environment and pinned dependencies have been prepared under `.venv` and `.runtime`.

```powershell
.venv/Scripts/python -m capri.cli
```

The token is read from `.runtime/bot-token`. It is never a command-line argument or tracked file.
On first launch the terminal prints a one-time `/start <nonce>` command for the owner.
Other users and ordinary group messages are ignored. Authorized guest updates are handled separately.
Restarting before pairing invalidates the nonce.
Owner identity persists in `.runtime/owner.json`; OMP data persists in `.runtime/agent`.

## Telegram-only Guest transport probe

This opt-in test creates no Engine and accesses no OMP session. Stop the normal
poller first: the same token must have only one poller. Private DM is temporarily
unavailable while the probe runs. From this checkout with its prepared Python:

```powershell
python -m capri.cli --data <existing-runtime-directory> --guest-probe answer
```

An existing valid owner.json is required; missing/malformed pairing refuses before
any Telegram API call. Startup checks supports_guest_queries=True, otherwise
reports the required Guest Mode setting in @BotFather. Polling subscribes only to
the registered guest_message handler through resolve_used_update_types().

As the paired owner, send `Тест @Capriompbot` in a human DM/group where Capri is
absent. A real authorized sender receives exactly one `Guest OK` via
answerGuestQuery. Anonymous/chat/bot senders fail closed. This does not use inline
search results selected while typing. Failures never fall back to ordinary sends.
The short-lived process deduplicates query IDs in memory, including failed attempts.

The first live gate passed on 2026-10-25: an authorized owner summon produced a
visible Guest OK. For the second transport test, use `--guest-probe edit`: one
Думаю… reply changes after 2 seconds to Guest OK final using the returned inline
message ID. No extra reply or model work is involved; failed API calls are not retried.

Both transport gates passed. The probe remains a separate diagnostic utility.
See docs/verification/guest-transport.md for its evidence.

## Guest Luna threads

Normal startup handles both owner DM and guest_message in one poller. Enable Guest
Mode in @BotFather; unsupported capability warns without disabling owner DM.
In a supported human chat where Capri is absent, send `@Capriompbot <request>`.
Only the paired owner's real sender identity is accepted. Replies use one
answerGuestQuery result, then edit that same inline message. Public model commentary
accumulates during tools with an animated dot suffix. If no public text arrives
within 1.2 seconds, the first result is only `·`; there is no fixed "Думаю…".
Answer and edits share a 0.9-second pacing interval, including the final edit.
The completed model answer replaces all progress. Reasoning and tool payloads
are never displayed. No ordinary send or DM fallback.
Long replies are visibly truncated to 4096 UTF-16 units.

Each chat has its own persistent threads under `.runtime/guest/sessions/<chat>/<thread>`.
There is no automatic expiry. Commands after the mention are local, without Luna:
`/newthread [title]` (alias `/new`), `/threads`, `/resume [ID/prefix/title]`,
`/title <name>`, `/status`. Resume without an argument lists threads. Ambiguous
selectors are rejected. While a guest turn is active, only listing/status is allowed.
Reply text/caption is passed as quoted, untrusted reference data; no broader history
or owner transcript is read. Tools are exactly web_search; model is gpt-6-luna.

Only one guest turn runs at a time; a second receives a brief busy answer.
OMP children sharing the existing auth/config root are serialized: a guest waits
for an active owner turn, stops the idle owner child, and runs its own child.
The next DM lazily resumes the unchanged owner pointer. This adds startup latency;
DM messages wait while guest work runs. Unconfirmed child teardown blocks further
OMP work until restart rather than risking simultaneous children.

Automated and real OMP checks passed; production Telegram scenarios still need
owner confirmation. See docs/verification/guest-luna-threads.md.

Stop with Ctrl+C. After an OMP failure/timeout, restart Capri to resume its persisted session.
Owner messages during a reply are debounced for 500 ms and submitted via native OMP steering.
If steering is unavailable they wait FIFO for the current response to finish. `/stop` aborts it.
Luna can end a message with the exact hidden token `<bubble>`, committing even a one-word
message immediately. An incremental parser keeps token fragments out of previews and sends.
For example, `Привіт<bubble>Як справи?<bubble>Ауууу` produces three messages.
The appended conversational system instructions let the model choose message count naturally.
Without a token, short paragraphs stay together. At 800 pending visible characters, safe
paragraph, sentence and whitespace boundaries provide size fallback (minimum candidate: 140).
Each fresh draft contains only the remaining suffix.
Fenced code stays together. Indivisible spans over Telegram's limit retain the visible, Unicode-safe
truncation fallback from Phase 1. Short replies remain one durable message.
Put literal token examples inside backtick inline code or backtick/tilde fenced code.
An unfinished reserved token prefix at stream end is discarded; nonmatching text such as
`<button>` stays literal. Open code conservatively stays literal until its closing delimiter.
Whitespace-only bubbles are ignored. There are no artificial delays or later attention-seeking
messages. Future sticker/PC actions still need a separate ordered tool integration.

## Exact dependencies / reproducibility

- Python used here: 3.14.7. Python 3.14 is required.
- OMP binary: 18.12.6 Windows x64, release commit `45c35e40c46166dc726ccc52f5d27f40f2449f99`.
- SHA-256: `73d73c11dc8821cf939441a964992aefc9c5b0d5a4418e9e8985a46439b60eef`.
- Binary metadata: https://build.stencil.so/api/products/omp/versions/18.12.6/windows-x86_64
- Official SDK source: `sdk/python/omp-rpc` at that exact commit; SDK version 0.1.0 is NOT sufficient provenance by itself.
- aiogram: 3.31.0. No global OMP or Bun required.

For a new checkout, download and hash-check that binary into `.runtime/omp.exe`, obtain the exact source archive, then:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install .runtime/source/oh-my-pi-45c35e40c46166dc726ccc52f5d27f40f2449f99/sdk/python/omp-rpc
.venv/Scripts/python -m pip install -e . pytest
```

Create `.runtime/bot-token` locally, and log in with the official OMP flow using the same private agent directory:

```powershell
$env:OMP_PROFILE = ''
$env:PI_PROFILE = ''
$env:PI_CODING_AGENT_DIR = (Join-Path (Get-Location) '.runtime/agent')
.runtime/omp.exe login openai-codex
```

This milestone has no npm installer. Never install an unrelated PyPI package in place of the pinned official SDK.

## Verify

```powershell
.venv/Scripts/python -m pytest -q
```

See [live feasibility and acceptance evidence](docs/verification/spikes.md) and the [bounded execution plan](docs/verification/execution-plan.md).
Phase 0/1 is the verified baseline; the narrow Phase 2 conversation-flow spike is implemented locally.
Phase 2 live acceptance is pending owner testing; see `docs/verification/phase2.md`.
Explicit bubble implementation and its remaining live checks are recorded in
`docs/verification/explicit-bubbles.md`. A running process needs a restart to load it.
Earlier Superpowers v0.1 documents remain historical drafts.
