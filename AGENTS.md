# Repository Guidelines

## Project Structure & Module Organization
Capri is a Windows x64, Python 3.14 Telegram bot using aiogram long polling and the official OMP Python RPC SDK. The current milestone supports one paired owner and private text conversations.

- `src/capri/`: `cli.py` launches the bot; `app.py` handles messages; `engine.py` manages OMP; `config.py` handles pairing and configuration; `telegram.py` handles delivery.
- `tests/`: pytest tests organized by module (`test_app.py`, `test_engine.py`, `test_config.py`, `test_telegram.py`).
- `docs/verification/`: execution scope and recorded acceptance evidence.
- `docs/superpowers/`: historical design and planning drafts; consult the README for current implementation scope.
- `.runtime/` and `.venv/`: ignored local runtime data and dependencies. There is no separate asset directory.

## Build, Test, and Development Commands
Run commands from the repository root in PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-test.txt
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m pytest tests/test_engine.py -q
.venv/Scripts/python -m capri.cli
```

These create the environment, install Capri with its vendored SDK, run all or focused tests, and launch the bot. Run installation from the checkout root; requirements explicitly select `vendor/omp/sdk/python/omp-rpc`. Use `python scripts/verify-vendor.py --root .` to check source provenance. The SDK version alone does not establish provenance, and `pip install -e .` alone is not the supported install command. Follow README instructions for the existing hash-verified OMP executable; the source import has not switched that runtime yet. Packaging uses setuptools; no npm build is required for Python tests.

## Coding Style & Naming Conventions
Use four-space indentation, `snake_case` functions and variables, `PascalCase` classes, and uppercase constants. Follow surrounding Python style and add type annotations where useful. Keep asynchronous Telegram handling separate from OMP lifecycle and configuration logic. No formatter or linter is currently configured.

## Testing Guidelines
Use pytest, `tmp_path` for isolated storage, and mocks or injected SDK fakes for external services. Name tests `test_<behavior>`. Add regression tests for fixes, especially pairing, privacy, session persistence, failure cleanup, and delivery limits. No numerical coverage threshold is configured. Distinguish automated tests from live Telegram/OMP acceptance evidence.

## Commit & Pull Request Guidelines
There is no commit history yet. Use concise imperative subjects, such as `Fix owner pairing validation`. Keep changes focused. PR descriptions should explain behavior, relevant issues, verification results, and limitations; include screenshots when visible behavior changes.

## Security & Agent Instructions
Keep tokens, credentials, sessions, and raw traces out of Git. Store the bot token in `.runtime/bot-token`; never pass it as a CLI argument. Preserve owner-only access and OMP capability isolation. Do not use GPT-6 Astra for subagents.
