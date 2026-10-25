# OMP native tools integration

This records the initial headless integration pass. Subsequent Owner-only approval
buttons are implemented in [Owner approval verification](owner-approval.md);
that report supersedes the no-approval-UI limitation below. The owner later
reported that the initial manual file/shell tests passed; that report is not an
instrumented trace.

## Scope

Owner receives exactly `web_search`, `read`, `write`, `edit`, `glob`, `find`,
`bash`. Guest remains exactly `web_search`; its engine and prompt are unchanged.
No host tools, approval UI, eval, task/subagents or desktop capabilities were added.

OMP owns permissions: `tools.approvalMode: write`. The bash allowlist contains
only the exact commands `git status`, `git diff`, `git log`, `git show`,
`python --version`, `node --version`. Unlike wildcard-suffixed examples, these do
not allow arbitrary flags such as `git diff --output=...` or execution helpers.
Extra flags require approval too. Compound-command approval bypass is not enabled.
This policy is not a filesystem sandbox or a defense against an owner deliberately
rewriting OMP configuration or local executable/repository configuration.

The pinned OMP source confirms that all tools are approval-wrapped even with
`--no-extensions`; a required approval without interactive UI fails before tool
execution. This behavior has been source-inspected, not yet live-execution-tested
in Capri for this change.

`find.enabled: on` is necessary: in this OMP release `find` is semantic grep,
not a POSIX filename search, and its default `auto` setting requires a native judge
model. Without explicit enablement it can disappear from the requested toolset.
Filename listing should normally use `glob`. Semantic `find` execution and its
judge-model availability still need live verification.

## Automated evidence

- Baseline: `python -m pytest -q` → 208 passed.
- RED: expanded Owner SDK/tool-state and Windows prompt tests plus approval config
  test failed before production changes; missing `find` config also observed RED.
- GREEN: `python -m pytest -q` → 218 passed.
- Tests cover expanded SDK arguments on resume, exact expanded startup tool state,
  rejection/cleanup for missing tools and unexpected `eval`, persisted approval
  config, narrow allowlist, and runtime prompt instructions.
- Existing Guest tests still check web-only SDK arguments and reject extra `bash`.

## Native startup probe

An unauthenticated isolated probe used the pinned `.runtime/omp.exe` and official
SDK with Capri's generated config, no UI, extensions, rules, skills, LSP or PTY.
No owner auth, transcript or session pointer was used, and no model prompt was sent.

Observed `state.dump_tools`:

- Owner: `bash`, `edit`, `find`, `glob`, `read`, `web_search`, `write` (exact match).
- Guest: `web_search` (exact match).
- Both child processes: `stop() == True`.

Local ignored artifacts: `.runtime/native-tools-probe.py` and
`.runtime/native-tools-probe-result.json`.

## Remaining live acceptance

An existing `capri.cli` process was detected. It was not stopped, and no second
process was started against its shared authenticated runtime. Restart that process
to load this change, then perform the controlled Owner sequence:

1. List working-directory files using glob/read (semantic find where appropriate).
2. Create `test.txt` with `hello` using write.
3. Replace it with `hello Capri` using edit.
4. Run exactly `git status` through bash without approval.
5. Request `pwsh -NoProfile -Command ...` to list processes: approval must fail
   closed, not execute. Do not accept a model's refusal alone as execution evidence.
6. Verify real Guest state remains web-only and file/shell tools are unavailable.

`pwsh` was not found on this host's PATH; Windows PowerShell (`powershell.exe`)
is present. PowerShell 7 is not installed by this change. A tool approval failure
must precede shell execution regardless of whether `pwsh` is installed.

The startup probe does not establish live read/write/edit, safe bash execution,
headless denial, model routing or Telegram acceptance. Those remain pending.

Review: author self-review only (no subagent tool available); not an independent
review. No commit or push performed.
