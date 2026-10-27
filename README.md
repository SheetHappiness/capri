# Capri: first working milestone

Windows x64 / Python 3.14, official OMP Python RPC SDK, aiogram long polling.
One explicitly paired owner, private text, throttled live drafts and streamed durable bubbles.
Owner DMs use OMP's native tools and a separate live activity message.
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
Final delivery succeeds only after an acknowledged answer/edit. An explicit final
429 permits one retry after its delay on the same inline message. Generic network,
server and unknown errors are uncertain: log the outcome and do not retry blindly.
Failed progress edits can still be followed by the eventual final answer.
Query IDs are reserved before network work, including failed/uncertain attempts;
dedupe retains the most recent 2048 IDs. Older IDs can be processed again after eviction.

Only the first Telegram `mention` entity matching the bot username (ignoring case)
is removed, using its UTF-16 range. Other occurrences are preserved. Without a
matching entity, only one leading invocation is removed; mentions within content
or quoted examples stay intact.

Each chat has its own persistent threads under `.runtime/guest/sessions/<chat>/<thread>`.
There is no automatic expiry. Commands after the mention are local, without Luna:
`/newthread [title]` (alias `/new`), `/threads`, `/resume [ID/prefix/title]`,
`/title <name>`, `/status`. Resume without an argument lists threads. Ambiguous
selectors are rejected. While a guest turn is active, only listing/status is allowed.
New/renamed titles are normalized to one line, trimmed and capped at 100 Unicode
code points. An empty new title is unnamed; an empty rename is rejected. Listings
show at most 20 entries, current first and others most recently active first, and
pass through the shared 4096-unit UTF-16 limit even for emoji titles. Older entries
and sessions remain available through `/resume`; legacy titles are bounded for display.
Reply text/caption is passed as quoted, untrusted reference data; no broader history
or owner transcript is read. Tools are exactly web_search; model is gpt-6-luna.

Only one guest turn runs at a time; a second receives a brief busy answer.
OMP children sharing the existing auth/config root are serialized: a guest waits
for an active owner turn, stops the idle owner child, and runs its own child.
The next DM lazily resumes the unchanged owner pointer. This adds startup latency;
DM messages wait while guest work runs. Unconfirmed child teardown blocks further
OMP work until restart rather than risking simultaneous children.

Current Guest delivery behavior and its live evidence are recorded in
[Guest live progress](docs/verification/guest-live-progress.md). The earlier
[Guest threads report](docs/verification/guest-luna-threads.md) retains historical
thread/isolation evidence. Hardening and remaining acceptance are recorded in
[post-merge hardening](docs/verification/post-merge-hardening.md).

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

## Clean-machine bootstrap (Windows x64)

Install these system prerequisites manually:

- Git and PowerShell 7 x64.
- Python 3.14 x64, available as `python` on PATH.
- Visual Studio 2022 C++ Build Tools with the x64 compiler/linker and a compatible
  Windows SDK (headers, x64 libraries and resource compiler).

Then, from PowerShell 7 in a fresh checkout:

```powershell
git clone <your-Capri-repository-url> CapriCorn
cd CapriCorn
./scripts/bootstrap.ps1
.venv/Scripts/python -m capri.cli
```

Before starting Capri for the first time, create `.runtime/bot-token` locally and
complete the private OMP login described below. Bootstrap does not log in, run a
model prompt or start/restart the bot. Missing prerequisites produce a diagnostic;
bootstrap does not install Visual Studio, Python or other system components.

Bootstrap creates or checks the checkout's `.venv`, installs
`requirements-test.txt` including `vendor/omp/sdk/python/omp-rpc`, verifies SDK
origin and source provenance, and installs these exact private tools from
`runtime-toolchain.json`: Bun 1.4.4 baseline, Rust nightly-2026-10-06 via rustup
1.29.2, CMake 4.4.4 and Ninja 1.12.1. They live under `.runtime/tools`; user PATH
and user Rust roots are unchanged. Network access to official tool releases and
Python/Bun/Cargo dependency registries is required.

MSVC 14.44.35207 / compiler 19.44.35229 and SDK 10.0.26100.0 are the **recorded
build proof**, not required patch versions. The build checks VS2022 x64 and SDK
components, records the actual versions, and verifies native build and smoke.
The procedure and inputs are pinned; executable hashes may differ between builds.

The build uses a fresh manifest-only source copy, frozen Bun lockfile and locked
Cargo build. Before publication it checks `--version`, `--help`, worker smoke,
private configuration, auth-free SDK `get_state()`, embedded baseline native
extraction and confirmed `stop()`. Only then does one same-volume replacement
install `.runtime/bin/omp.exe`. A build/smoke failure preserves the previous final
executable and existing owner/Guest/auth/config state. If final is in use, stop
the bot manually and rerun; bootstrap never kills it. No mandatory metadata
sidecar is needed to launch Capri.

Run one bootstrap at a time. Repeated sequential runs reuse verified tools and
build caches. Downloads use `.tmp`, SHA-256 verification and staging before
rename; incomplete downloads are downloaded again. A foreign/incompatible
`.venv` or existing wrong tool directory is reported without deleting it.
Private logs and per-run build/smoke evidence remain under Data.

```powershell
# Data is relative to the launch directory, or an absolute path:
./scripts/bootstrap.ps1 -Data C:/CapriData
.venv/Scripts/python -m capri.cli --data C:/CapriData
# Manual runtime override, if needed:
.venv/Scripts/python -m capri.cli --omp C:/Somewhere/omp.exe
```

Keep checkout/Data paths short: Windows worker sockets have a strict byte limit.
Smoke rejects an overlong path with a request to shorten Data, without falling
back to global temp. Space/Unicode paths work within this limit.
The default runtime is `<data>/bin/omp.exe`; there is no global OMP fallback.
The Telegram-only `--guest-probe` still needs no OMP executable.

For Python-only development, source builds are unnecessary:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-test.txt
.venv/Scripts/python scripts/verify-vendor.py --root .
```

Install from the checkout root. `requirements-runtime.txt` is the app-only
alternative; `pip install -e .` alone does not establish SDK provenance.
Normal CLI startup rejects an SDK whose installation metadata does not identify
this checkout's `vendor/omp/sdk/python/omp-rpc` directory. After moving the
checkout or installing the wrong SDK, reinstall from the checkout root:

```powershell
.venv/Scripts/python -m pip install -r requirements-runtime.txt
```

The guard runs before reading the bot token or importing the SDK-dependent app.
`--help` and the Telegram-only `--guest-probe` do not require SDK provenance.
OMP source is pinned to `45c35e40c46166dc726ccc52f5d27f40f2449f99` (18.12.6),
archive SHA-256 `a8bbb85ede151ed58c100e84e6d239ca835937e04a51cd287049a9ff737fd4e2`.
See [vendor provenance](vendor/omp/UPSTREAM.md) and
[build/acceptance evidence](docs/verification/vendored-omp.md).

`build-runtime.ps1 -Data <path>` is also available with the pinned tools already
prepared on PATH and the local Python requirements installed. Bootstrap supplies
that environment automatically. Build logs and source snapshots are under
`<data>/build/<run-id>`; `candidate-result.json` records actual tool versions,
hashes, smoke evidence and publication. The existing per-Data build lock protects
shared build caches; the installer adds no concurrent-bootstrap protocol.

To log in with the newly built executable and the same private roots used by
Capri, use a child PowerShell so these environment values do not persist:

```powershell
pwsh -NoProfile -Command {
    $data = (Resolve-Path .runtime).Path
    $setup = .venv/Scripts/python -c 'import json; from pathlib import Path; from capri.config import omp_environment; print(json.dumps(omp_environment(Path(".runtime"))))' | ConvertFrom-Json -AsHashtable
    foreach ($key in $setup.Keys) { [Environment]::SetEnvironmentVariable($key, $setup[$key], 'Process') }
    & "$data/bin/omp.exe" login openai-codex
}
```

Use your custom Data in both places when applicable. Never put credentials on the
command line or in Git. Capri keeps sessions and saved permissions across rebuilds.

The pinned SDK's `stop() -> bool` explicitly confirms reaping, including retained
survivors, only on `True`. Capri shares this strict contract across owner, Guest,
and runtime handoff through `capri.teardown.stop_child`; exceptions and other return
values block further children. A cleared SDK process attribute alone proves nothing.
On Windows the SDK confirms the leader process; POSIX process-group guarantees do
not apply. Guest sessions retain their web-only tool restriction. Owner sessions
leave tool selection to OMP; Capri does not implement tools or an approval engine.

## Owner permission mode

Send `/permission` (or `/permissions`) in the paired owner's private DM to read OMP's current approval
mode and choose a standard mode with the menu buttons. The direct form also works:
`/permission yolo`, `/permission write`, `/permission always-ask`, or
`/permission always-ask-cached`. Commands and buttons bypass the model and steering.
Busy owner/Guest work must finish or be stopped before opening/changing this setting.

The pinned OMP version exposes no approval-setting RPC; Capri invokes its native
`config get/set tools.approvalMode --json` commands in the same private environment.
OMP validates and saves the setting in `.runtime/agent/config.yml`. Capri keeps
mandatory discovery/model isolation in `.runtime/capri-isolation.yml`, passed as
a config overlay, so startup no longer overwrites OMP's saved settings.
Before a change, the idle owner child is reaped. The next DM lazily resumes the same
session with the saved mode; a restart preserves it. Guest keeps web_search only
and its previous native yolo mode, independently of this owner setting.

Native approval requests appear as separate owner-only cards with one inline row:
`Once`, `Session`, `Deny`. Once and Deny affect this call; Session forwards OMP's
offered session choice, whose exact scope appears in the card. It is omitted when
OMP offers no session grant. Cached mode uses the exact target grant where offered,
otherwise the native directory grant. Persistent Always grants are not exposed.
OMP retains all approval decisions and session grants; Capri only returns its exact
native option. Session grants last for the current OMP child, so restart or Guest
handoff can require approval again. Saved permission mode persists independently.

Only the paired owner can press a card's buttons, in its original private message.
Duplicate/expired clicks do nothing. Buttons are invalidated when answered, cancelled,
or the turn ends. Failed/uncertain card delivery or an oversized native prompt declines
the request rather than retrying or approving an additionally truncated card.
Unsupported interactive dialogs are cancelled. Owner RPC UI is enabled only for this
approval bridge; external extensions remain disabled and Guest stays headless.
Default yolo behavior stays unchanged until the owner selects a mode.
See [permission verification](docs/verification/permission-command.md).
Native decision behavior is recorded in [approval verification](docs/verification/approval-buttons.md).

## Owner OMP activity

In an owner DM, OMP can choose its native tools, including file and command tools
available in its current configuration. Its working directory remains `.runtime/work`;
that directory is a working location, not a filesystem sandbox. Existing disabled
external discovery, extensions, skills and rules settings remain in place.

The first exposed thinking or tool event creates one plain-text activity message,
without a heading or thinking icon. Further events edit that same message at most
once per 0.75 seconds,
coalescing bursts. It shows only thinking text actually exposed by the provider,
native tool names/arguments, textual result snapshots, and edit-preview file paths
or diagnostics where supplied. Binary payloads and opaque result details are omitted.
The view keeps the latest thinking block and four recent tool calls, with bounded
excerpts and a visible ellipsis when clipped. It stays within Telegram's 4096 UTF-16
unit limit. Completion adds `✓ done`; a failed stream adds `✗ failed`.

Capri's public text still uses the existing drafts and durable `<bubble>` messages;
technical activity never enters the bubble parser. Activity delivery failures disable
that view for the turn while normal answer delivery continues. Explicit rate limits
pace retries, including at most one final retry; uncertain initial sends are never
repeated. Completion allows at most two seconds for the activity footer, then cancels
and joins its sender so a flood wait or slow API cannot hold the answer.
`/stop` and shutdown cancel and join the activity sender before closing the
source. An interrupted view may retain its last snapshot; it does not claim completion.
Text-only turns without exposed activity create no technical message.

This iteration adds no personality file, memory or proactive behavior. The existing
appended conversation prompt remains separate from the activity renderer, leaving
the future `soul.md` layer independent of runtime and UI event handling.
Both owner and Guest prompts request plain-text prose, including exposed reasoning,
without Markdown styling markers such as `**`. Actual code and file content retain
their literal syntax.
See [OMP Remote UI verification](docs/verification/omp-remote-ui.md) for contract
provenance, automated checks and the remaining live Telegram acceptance.

## Verify

```powershell
.venv/Scripts/python -m pytest -q
git diff --check
```

`requirements-test.txt` pins application/test package versions for Windows Python
3.14; the official SDK source/hash is pinned in project metadata. Build backends
retain their declared version floors. Unit/integration tests require no OMP binary,
login, bot token or Telegram connectivity.
The `Tests` workflow runs `Windows Python 3.14` on pull requests and pushes to main.
Its YAML and install/test commands have been validated locally.
[Remote run 40225164561](https://github.com/SheetHappiness/capri/actions/runs/40225164561)
succeeded at `f442c4c` on main. Whitespace checks compare the complete push range
or the PR merge-base to its head; Actions are pinned to exact Node 24 commit SHAs.
Configuring a required branch check remains a separate repository admin action;
authenticated OMP and real Telegram acceptance stay manual.

See [live feasibility and acceptance evidence](docs/verification/spikes.md) and the [bounded execution plan](docs/verification/execution-plan.md).
Phase 0/1 is the verified baseline; the narrow Phase 2 conversation-flow spike is implemented locally.
Phase 2 live acceptance is pending owner testing; see `docs/verification/phase2.md`.
Explicit bubble implementation and its remaining live checks are recorded in
`docs/verification/explicit-bubbles.md`. A running process needs a restart to load it.
Earlier Superpowers v0.1 documents remain historical drafts.
