# Hermes Port 01 provenance

Repository: https://github.com/NousResearch/hermes-agent
Commit: ff294849385e433dd40a993b4f07673abb95c6f5

This library is dormant. Capri does not import it. No tools, adapters or runtime callbacks are registered.

## Complete upstream copies

Original SHA-256 values below hash the original archive bytes, before relocation.
`provenance.json` enumerates every changed line, original/local line ranges, and
IMPORT_REWRITE / COMPAT_REDIRECT classifications. Tests reverse every change and
verify the original hash and canonical-module AST equivalence.

| Upstream | Local | Original SHA-256 |
|---|---|---|
| tools/approval.py | tools/approval.py | 6f19d962993e563e527a6310f481c38d131ad34ab422e540db5c3f949ffa742d |
| tools/approval_context.py | tools/approval_context.py | 9bcac985edbcd610392ac40c84c47ca38f169976f42b7e4acade5eb82709dd97 |
| tools/approval_detection.py | tools/approval_detection.py | cba0adbbd592661729f7d3865f8c834d57a8b5e6fb5763539695190820a094a3 |
| tools/approval_floors.py | tools/approval_floors.py | 87296263fbd2ab1eef181cb162399a238e7f123381b5835315b9c71fd16e418c |
| tools/approval_prompt.py | tools/approval_prompt.py | f2b47d44ab8165af1c6d03341aecc742a0360161f8dfab75959b4b34c95f1452 |
| tools/approval_gateway_wait.py | tools/approval_gateway_wait.py | 2d4cf33858fb520a6b9329ab0c6dedfc63986a0d0a58a1c53f501236de481d4b |
| tools/approval_human_wait.py | tools/approval_human_wait.py | 6ef36b719dca187b94ac02f293f5c415c3191ef3a84f2c3d3472342d88a14a28 |
| tools/approval_smart.py | tools/approval_smart.py | 46a30d5cd8bd930c30faaa3ca53cf52ac4369639d0fa92d7f0995fc2c1dc9190 |
| tools/clarify_gateway.py | tools/clarify_gateway.py | 7052ea9832fc93e40146fb1226753fd1bd5618943cf437d822a2821840fba26c |
| tools/interrupt.py | tools/interrupt.py | 3127f53b4ca1431df828015a3eb06d29ffd43ea9b6a51954d3a45bc69483917b |
| tools/ansi_strip.py | compat/ansi_strip.py | 71f339d1be720c24f407565b4a90cb55164dead2e860cf438258104fd96c1922 |
| agent/runtime_self_protection.py | compat/runtime_self_protection.py | 1ac5fb0847b4065a1e3dc52d6908e266993127939f2f2ac7b9c0c0c94b4186ed |
| tools/human_input_hooks.py | compat/human_input.py | cb683ab73dc60f03d4ae98894287fa34c9769fda528d8fa05fbe8f2f111d58a5 |
| agent/auxiliary_task_config.py | compat/auxiliary_task_config.py | a1a566b8c55bd183808b2dee5443f42999b2a23db5c509ad29adf334f9a62e28 |
| tools/shell_heredoc.py | compat/shell_heredoc.py | 12f9b8e2218cc4feda13b06d1ffe1fd5cdb3b6c227380a3a02965d13b7de1c8a |
| LICENSE | LICENSE | 821556e6336796450ab852d375117b48a4887e71d255794fd6318d99982a5ab6 |

## Exact excerpts used by compat

Every excerpt keeps its upstream body. Symbols, original line ranges and whole-source hashes are in provenance.json.

- utils.py: sha256:9c4751dc9fbcbfe7e16d9e0cc5fb25566517c4927d2dc84061d4cac993a98445; symbols: TRUTHY_STRINGS, env_var_enabled, is_truthy_value.
- agent/deadline.py: sha256:b691038025c542ef0f189e13feecce59bc07fb71a5fc8f97bd48b159e7a26734; symbols: MAX_SAFE_TIMEOUT_S, _WINDOWS_MAX_WAIT_S.
- tools/clarify_tool.py: sha256:33428a858bda8066898fd4f62c2103099e41432a26897624dbf4fbf1ec4f3f52; symbols: RECOMMENDED_LABEL, strip_recommended.
- hermes_cli/config.py: sha256:9ca94a1e1096046103fd62352fb418c90fc9cc0d0efafefc7267ae48de6d37e2; symbols: cfg_get.
- cron/lifecycle_guard.py: sha256:c4d95d42ee6824ec94a7cbb5210ea187f3644b3f0e0998854472e027125ac217; symbols: _ARGV_LIST_PUNCTUATION, _CONTROL_CHARS, _ENV_ASSIGNMENT, _ERE_TAIL, _ERE_WILDCARD_ONLY, _GATEWAY_CMDLINE_TOKEN_RE, _GATEWAY_LIFECYCLE_PATTERN, _HERMES_GATEWAY_LABEL_RE, _HOST_INTERPRETER_NAME, _INTERPRETER_IMAGE_RE, _KILLER_VALUE_OPTIONS, _KILL_VERB_RE, _LAUNCHCTL_LIFECYCLE_VERBS_RE, _MAX_PREFIX_PEELS, _NAME_ENUMERATORS, _NAME_KILLERS, _PROFILE_FLAG_LIFECYCLE_PATTERN, _SHELL_LINE_CONTINUATION, _TRANSPARENT_COMMAND_PREFIXES, _TRANSPARENT_PREFIX_OPERANDS, _TRANSPARENT_PREFIX_VALUE_OPTIONS, _command_token_index, _contains_launchctl_gateway_lifecycle, _current_profile_name, _executable_name, _executed_command_index, _is_interpreter_image, _iter_command_segments, _killer_targets_host_interpreter, _named_profile_is_current, _pattern_reaches_host_interpreter, _peel_transparent_prefixes, _segment_names_host_interpreter, _shlex_tokens, _split_logical_lines, _split_segments, contains_gateway_lifecycle_command, contains_host_interpreter_kill.
- agent/redact.py: sha256:1cd473ce27a643d456765413e9c894a9bf1e2a31dd4741e790134845424f4084; symbols: SECRET_HEADER_NAME_LIST, _AUTH_HEADER_RE, _DB_CONNSTR_RE, _DISPLAY_CONTROL_RE, _JWT_RE, _PREFIX_PATTERNS, _PREFIX_RE, _PRIVATE_KEY_RE, _SECRET_HEADER_NAMES, _SECRET_HEADER_RE, _TELEGRAM_RE, _compile_prefix_matcher, _mask_token, mask_secret.
- locales/en.yaml: sha256:d5550f6566b368c32bcaad616ac95759497c27371d1a854ff23bd7ec982543aa; symbols: approval.*.

## Boundary decisions

- Config reads return an empty snapshot; saves raise a dormant-boundary error. No host config is read or written. Tests inject snapshots at this seam.
- Auxiliary client has no model SDK/network implementation; calling it raises and the unchanged Smart core escalates. Tests inject auxiliary results. Timeout is an inert 30-second seam value.
- Terminal batching has no prepared guard, registration or publication. Activity heartbeat is inert.
- Session identity uses the upstream environment fallback; no gateway context binding, multiplex profiles, viewer admission, delegation or plugin surface exists.
- Home seam resolves only HERMES_HOME/default identity; no directory creation, profile discovery, overrides or config migration.
- ANSI stripping, shell heredoc parsing and runtime self-protection are standalone stdlib-only upstream helpers copied in full. No execution stack is imported.
- Lifecycle compat extracts only the direct-command recognizer and its lexical helpers; no cron runner, referenced-script traversal or SQLite access.
- English i18n includes only pinned approval strings; no translations, user overlay or plugin language packs.
- Redaction uses a small display-only subset of unchanged upstream prefix/header/Telegram/private-key/DB/JWT patterns and token masking. This is not full Hermes redaction parity: vault exact values, arbitrary env/config assignments, URL/form/control-split secret handling, file/terminal output and routed-profile policy are excluded. No identity/no-op redactor is used. The approval-surface tests remain enabled.

## Optional unavailable subsystems

These imports are redirected to a deliberately absent private `_optional` namespace.
Even if Hermes is installed elsewhere, it cannot be imported accidentally. Existing
upstream try/except boundaries retain their minimal-install fallback. `_optional`
has no files, loader, sys.modules aliases or import hooks. Core tests prove the
builtin/default paths; closure tests prove the excluded targets cannot load.

- `hermes_cli.lifecycle` → `capri._vendor.hermes.compat._optional.hermes_cli.lifecycle`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.
- `gateway.session_policy` → `capri._vendor.hermes.compat._optional.gateway.session_policy`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.
- `gateway.session_ingress` → `capri._vendor.hermes.compat._optional.gateway.session_ingress`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.
- `gateway.hosted_room_execution_policy` → `capri._vendor.hermes.compat._optional.gateway.hosted_room_execution_policy`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.
- `tools.terminal_tool` → `capri._vendor.hermes.compat._optional.tools.terminal_tool`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.
- `hermes_cli.plugins` → `capri._vendor.hermes.compat._optional.hermes_cli.plugins`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.
- `hermes_cli.approval_transport` → `capri._vendor.hermes.compat._optional.hermes_cli.approval_transport`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.
- `tools.computer_use.tool` → `capri._vendor.hermes.compat._optional.tools.computer_use.tool`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.
- `agent.terminal_env_registry` → `capri._vendor.hermes.compat._optional.agent.terminal_env_registry`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.
- `hermes_yaml` → `capri._vendor.hermes.compat._optional.hermes_yaml`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.
- `tools.code_kernel` → `capri._vendor.hermes.compat._optional.tools.code_kernel`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.
- `tools.code_kernel_remote` → `capri._vendor.hermes.compat._optional.tools.code_kernel_remote`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.
- `hermes_cli.profiles` → `capri._vendor.hermes.compat._optional.hermes_cli.profiles`: OPTIONAL_UNREACHABLE; no corresponding runtime is installed or registered.

`hermes_yaml` handles only legacy string allowlists: empty/default snapshots never enter this branch. Plugin transport is excluded: default transport is builtin, and selection of an unavailable transport follows the unchanged upstream deny path. Optional terminal callbacks, gateway policies and lifecycle observers are absent.

## Regression-test adaptations and exclusions

Eight named upstream test modules preserve assertions. Adaptations are relocated
imports/patch targets, local waiting helper, hermetic environment and upstream OS
gating. One whitespace-only upstream test line is normalized for Capri whitespace checks (no assertion changed). Three interrupt integration cases require run_agent/terminal execution and
are explicitly skipped. One classic CLI config-assembly integration test is skipped.
Optional prompt_toolkit CLI tests skip only if unavailable. GNU sort conformance
is skipped only when the installed binary is not GNU coreutils; Windows sort.exe
does not implement the grammar this external-binary test exercises.
Platform/symlink skips retain upstream host constraints, not weakened assertions.

## Excluded subsystems

Gateway/platform adapters, Telegram UI, plugin approval transport, terminal execution,
full auxiliary LLM runtime, cron jobs, full secret-redaction subsystem and profile
multiplex runtime are not ported. No Capri runtime file is changed.
