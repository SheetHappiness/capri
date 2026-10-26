"""Exact upstream direct lifecycle recognizer; excludes cron and referenced-script scanning."""
from __future__ import annotations
import logging
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Optional, Iterator

_GATEWAY_LIFECYCLE_PATTERN = re.compile(
    r"(?i)"
    # Branch A: destructive `hermes gateway` ops. `start` is excluded: starting from inside a
    # gateway is benign and a job may legitimately start a sibling profile. The lookbehind keeps
    # `hermes` from being a path component or word tail (`/docs/hermes gateway restart-notes.md`)
    # while every real command position (text start, whitespace, `;`/`&`/`|`, `$(`, backtick,
    # U+FFFD) still matches.
    # See #77173.
    # Windows spells the CLI with a launcher suffix (`hermes.exe`, npm-style `hermes.cmd`/`.ps1`);
    # same command, so the suffix is optional here.
    r"(?:(?<![/\w.\-])hermes(?:\.(?:exe|cmd|bat|com|ps1))?\s+gateway\s+(?:restart|stop|uninstall)\b)"
    # Branch B: launchctl ops anchored on a hermes-gateway label so unrelated hermes services stay
    # unblocked. `submit`/`bootstrap` register a NEW keepalive job wrapping an arbitrary helper (a
    # laundered restart); neutral-label submissions are caught by
    # `contains_launchctl_submit_command`. `bootout`/`remove`/`disable` are the
    # modern/legacy/durable forms of `unload`.
    # `submit` and `bootstrap` are included alongside the direct verbs (kickstart/etc.): `launchctl submit
    # -l ai.hermes.gateway-<suffix> -- <helper-script>` (or `launchctl bootstrap gui/<uid> <plist>`) creates
    # a NEW keepalive job wrapping an arbitrary helper, which is how a blocked direct restart/kill gets
    # laundered into a persistent restart loop instead (#62891) — same foot-gun, indirect shape.
    # Neutral-label submissions that dodge this text anchor are caught separately by
    # `contains_launchctl_submit_command` (execution-aware, label-independent). `bootout`/`remove`/`disable`
    # sit alongside `unload`: Apple deprecated load/unload in favour of bootstrap/bootout, so `bootout` is
    # the modern spelling of an already-listed verb, `remove` is its legacy sibling, and `disable` is what
    # makes an unload durable across boots. Omitting them left the bypassable approval layer
    # (tools/approval.py, skipped on force=True) as the only cover, while this hard block — documented as
    # "force=True cannot help here" — let them through (#80260).
    r"|(?:launchctl\s+(?:kickstart|unload|load|stop|restart|submit|bootstrap|bootout|remove|disable)\b[^\n]*\bhermes[.\-]?gateway)"
    # Branch C: systemctl ops on a hermes-gateway unit.
    r"|(?:systemctl\s+(?:-\S+\s+)*(?:restart|stop|start)\b[^\n]*\bhermes[.\-]?gateway)"
    # Branch D: pkill/kill of the gateway process, both token orders. Leading \b keeps "skill" from
    # matching as "kill".
    # `taskkill` / `Stop-Process` are the Windows spellings of the same operation; `\bp?kill\b`
    # cannot reach inside `taskkill`, so they are named outright. Service-control forms (`net stop`,
    # `sc stop`) presuppose a service install this guard has no evidence of and stay uncovered.
    r"|(?:\b(?:p?kill|taskkill|stop-process)\b[^\n]*\bhermes\b[^\n]*\bgateway)"
    r"|(?:\b(?:p?kill|taskkill|stop-process)\b[^\n]*\bgateway\b[^\n]*\bhermes)"
)

_INTERPRETER_IMAGE_RE = re.compile(r"^pythonw?(?:\d+(?:\.\d+)*)?(?:\.exe)?$")

_HOST_INTERPRETER_NAME = Path(sys.executable).name.lower() if sys.executable else ""

_KILLER_VALUE_OPTIONS = {
    # procps pkill/pgrep options that consume the next token, so the value is never the pattern.
    "pkill": frozenset({
        "-g", "--pgroup", "-G", "--group", "-P", "--parent", "-s", "--session", "-t", "--terminal",
        "-u", "--euid", "-U", "--uid", "-F", "--pidfile", "--ns", "--nslist", "-d", "--delimiter",
        "--signal", "-O", "--older", "-r", "--runstates", "--cgroup", "-A", "--ignore-ancestors",
    }),
    "killall": frozenset({"-s", "--signal", "-u", "--user", "-o", "--older-than", "-y", "--younger-than",
                          "-n", "--ns", "-Z", "--context"}),
}

_KILLER_VALUE_OPTIONS["pgrep"] = _KILLER_VALUE_OPTIONS["pkill"]

_KILLER_VALUE_OPTIONS["pidof"] = frozenset({"-o", "--omit-pid", "-S", "--separator"})

_ERE_TAIL = re.compile(r"[.*+?\\\[\](){}|].*$")

_ERE_WILDCARD_ONLY = re.compile(r"^[.*+?$\s]*$")

_NAME_KILLERS = frozenset({"pkill", "killall", "taskkill", "stop-process"})

_NAME_ENUMERATORS = frozenset({"pgrep", "pidof", "get-process"})

_KILL_VERB_RE = re.compile(r"(?i)\b(?:kill|taskkill|stop-process)\b")

_GATEWAY_CMDLINE_TOKEN_RE = re.compile(r"(?i)hermes_cli|\bhermes\b[^\n]*\bgateway\b|\bgateway\b[^\n]*\bhermes\b")

def _is_interpreter_image(value: str, *, substring: bool = False) -> bool:
    """True when *value* (a process/image name, `*`-wildcard allowed) denotes the Python interpreter
    that hosts the gateway. *substring*: pkill/pgrep match an ERE anywhere in the name, so `py`
    reaches `python3` too."""
    name = value.strip().strip("\"'").lower().removesuffix(".exe")
    if not name:
        return False
    if name.endswith("*"):
        prefix = name.rstrip("*")
        return "python".startswith(prefix) or _HOST_INTERPRETER_NAME.startswith(prefix)
    if _INTERPRETER_IMAGE_RE.match(name) or name == _HOST_INTERPRETER_NAME.removesuffix(".exe"):
        return True
    return substring and len(name) >= 2 and "python".startswith(name)

def _pattern_reaches_host_interpreter(pattern: str, *, full_cmdline: bool, exact: bool) -> bool:
    """pkill/pgrep/killall operand semantics: an ERE against the process NAME (or, with `-f`, the full
    command line). `python -m hermes_cli.main …` is the gateway's own cmdline, so a `-f` pattern
    that names the interpreter and then only wildcards or a `hermes` token reaches it, while
    `python mt_add.py` (a specific script) does not."""
    core = pattern.strip().strip("\"'").lstrip("^")
    core = core.removesuffix("$")
    head, _, rest = core.partition(" ") if full_cmdline else (core, "", "")
    # A literal interpreter name first (`python3.12`: the dot is a version separator, not an ERE
    # wildcard); only then read the head as an ERE with a metacharacter tail (`python3?`, `python.*`).
    match = None if _is_interpreter_image(head, substring=not exact) else _ERE_TAIL.search(head)
    if match:
        rest = head[match.start():] + " " + rest
        head = head[: match.start()]
    if not _is_interpreter_image(head, substring=not exact):
        return full_cmdline and bool(_GATEWAY_CMDLINE_TOKEN_RE.search(core))
    return not rest.strip() or bool(_ERE_WILDCARD_ONLY.match(rest)) or "hermes" in rest.lower()

def _killer_targets_host_interpreter(name: str, args: list[str]) -> bool:
    """Whether killer/enumerator *name* with argv *args* would select the host interpreter."""
    if name in ("pkill", "pgrep", "killall", "pidof"):
        # pkill/pgrep: ERE anywhere in the name unless -x; killall: exact name unless -r; pidof: exact.
        exact = name == "pidof" or (name == "killall") != any(t in ("-r", "--regexp", "-x", "--exact") for t in args)
        full_cmdline = name in ("pkill", "pgrep") and any(t in ("-f", "--full") for t in args)
        operands: list[str] = []
        position = 0
        while position < len(args):
            token = args[position]
            if token == "--":
                operands += args[position + 1:]
                break
            if token in _KILLER_VALUE_OPTIONS[name]:
                position += 2
                continue
            if not token.startswith("-"):
                operands.append(token)
            position += 1
        return any(_pattern_reaches_host_interpreter(op, full_cmdline=full_cmdline, exact=exact) for op in operands)
    if name == "taskkill":
        for position, token in enumerate(args[:-1]):
            option = token.lower().lstrip("/-")
            value = args[position + 1]
            if option == "im" and _is_interpreter_image(value):
                return True
            if option == "fi":
                filter_match = re.match(r"(?i)\s*['\"]?imagename\s+eq\s+(\S+)", value)
                if filter_match and _is_interpreter_image(filter_match.group(1)):
                    return True
        return False
    # Stop-Process / Get-Process: `-Name`/`-ProcessName` (also `-Name:value`), comma lists, positional
    # names for Get-Process.
    values: list[str] = []
    for position, token in enumerate(args):
        option, _, inline_value = token.partition(":")
        if option.lower() in ("-name", "-processname", "-n"):
            values.append(inline_value if inline_value else (args[position + 1] if position + 1 < len(args) else ""))
        elif name == "get-process" and not token.startswith("-") and (position == 0 or not args[position - 1].startswith("-")):
            values.append(token)
    return any(_is_interpreter_image(part) for value in values for part in value.split(","))

def _segment_names_host_interpreter(tokens: list[str], killers: frozenset[str]) -> bool:
    """Whether a tokenized segment runs one of *killers* against the host interpreter. The
    executable is read at the wrapper-peeled position first, then at the first killer token anywhere
    in the segment (`xargs kill`, Python argv lists)."""
    index = _executed_command_index(tokens)
    candidates = [index] if index is not None else []
    candidates += [i for i, token in enumerate(tokens) if _executable_name(token).lower().removesuffix(".exe") in killers]
    for position in candidates:
        name = _executable_name(tokens[position]).lower().removesuffix(".exe")
        if name in killers and _killer_targets_host_interpreter(name, tokens[position + 1:]):
            return True
    return False

def contains_host_interpreter_kill(text: str) -> bool:
    """Branch E entrypoint: a process killer aimed at the interpreter image hosting the gateway, or a
    name-derived PID feed into one (`pgrep python | xargs kill`, `kill $(pidof python3)`,
    `Get-Process python | Stop-Process`). Segment-tokenized, so quoted/spliced spellings and Python
    argv lists resolve the same way the shell resolves them."""
    normalized = _SHELL_LINE_CONTINUATION.sub(" ", text)
    kill_verb_present = bool(_KILL_VERB_RE.search(normalized))
    for segment in _iter_command_segments(normalized):
        joined = " ".join(segment)
        stripped = _ARGV_LIST_PUNCTUATION.sub(" ", joined)
        # Python argv lists (`subprocess.run(["taskkill", "/IM", "python.exe"])`) re-split only when
        # list punctuation was present, so a quoted `-f 'python my_script.py'` stays one operand.
        for tokens in ([segment, stripped.split()] if stripped != joined else [segment]):
            if _segment_names_host_interpreter(tokens, _NAME_KILLERS):
                return True
            if kill_verb_present and _segment_names_host_interpreter(tokens, _NAME_ENUMERATORS):
                return True
    return False

_SHELL_LINE_CONTINUATION = re.compile(r"\\\r?\n[ \t]*")

_ARGV_LIST_PUNCTUATION = re.compile(r"[\[\],]+")

_PROFILE_FLAG_LIFECYCLE_PATTERN = re.compile(
    r"(?i)"
    r"hermes\s+"
    # Each flag has one parse: '-' plus its remainder, never two ways to split
    # '--'. A following flag cannot also be an optional value (#129281).
    # Possessive token/space runs avoid repartitioning whitespace on failure;
    # whole flag groups can still backtrack to expose the profile selector.
    # Do not cap the number of flags: that would silently allow long self-stops.
    r"(?:-\S++(?:\s++(?!-\S)\S++)?\s++)*"
    # The selector: exactly the shapes the CLI's `_apply_profile_override` accepts.
    r"(?:--profile=([^\s]+)|(?:-p|--profile)\s+([^\s]+))"
    # Any global flags between the selector and the subcommand.
    r"(?:\s++-\S++(?:\s++(?!-\S)\S++)?)*"
    r"\s+gateway\s+(?:restart|stop)"
)

_LAUNCHCTL_LIFECYCLE_VERBS_RE = re.compile(
    r"(?i)\blaunchctl\s+(?:kickstart|unload|load|stop|restart|bootout|kill|disable|remove)\b"
)

_HERMES_GATEWAY_LABEL_RE = re.compile(r"(?i)\bhermes[.\-]?gateway\b")

_CONTROL_CHARS = frozenset(";&|()")

_TRANSPARENT_COMMAND_PREFIXES = frozenset({
    "sudo", "doas", "env", "nohup", "setsid", "nice", "ionice", "stdbuf",
    "timeout", "exec", "command", "builtin", "eatmydata",
    # Privilege and namespace wrappers: options, then the command they run.
    "pkexec", "su", "runuser", "setpriv", "systemd-run", "nsenter", "unshare",
})

_TRANSPARENT_PREFIX_VALUE_OPTIONS = {
    "sudo": {"-u", "-g", "-U", "-C", "-p", "-r", "-t", "-T", "--user", "--group", "--prompt"},
    "doas": {"-u", "-C"},
    "env": {"-u", "--unset", "-S", "--split-string", "-C", "--chdir"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "-n", "-p", "--class", "--classdata"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "pkexec": {"--user"},
    "su": {"-s", "--shell", "-g", "--group", "-G", "--supp-group"},
    "runuser": {"-u", "--user", "-s", "--shell", "-g", "--group", "-G", "--supp-group"},
    "setpriv": {"--reuid", "--regid", "--groups", "--inh-caps", "--ambient-caps", "--bounding-set",
                "--selinux-label", "--apparmor-profile"},
    "systemd-run": {"-u", "--unit", "-p", "--property", "-E", "--setenv", "--slice",
                    "--description", "--uid", "--gid", "--on-calendar", "--service-type"},
    "nsenter": {"-t", "--target", "-S", "--setuid", "-G", "--setgid", "-r", "--root", "-w", "--wd"},
    "unshare": {"--map-user", "--map-group", "--setgroups", "-R", "--root", "-w", "--wd"},
}

_TRANSPARENT_PREFIX_OPERANDS = {"timeout": 1}

_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

_MAX_PREFIX_PEELS = 8

def _current_profile_name() -> Optional[str]:
    """Profile running the guard (``hermes_cli.profiles.current_profile_name``); ``None`` if none."""
    from capri._vendor.hermes.compat._optional.hermes_cli.profiles import current_profile_name

    return current_profile_name()

def _named_profile_is_current(named: str) -> bool:
    """True when *named* is the profile executing the guard. Without a profile identity
    self-targeting cannot be proven, so nothing is blocked (sibling restarts stay allowed)."""
    current = _current_profile_name()
    return bool(current) and named.strip().casefold() == current.strip().casefold()

def _contains_launchctl_gateway_lifecycle(normalized_text: str) -> bool:
    """Order-independent companion to Branch B — see the verbs regex comment."""
    return bool(_LAUNCHCTL_LIFECYCLE_VERBS_RE.search(normalized_text)) and bool(
        _HERMES_GATEWAY_LABEL_RE.search(normalized_text)
    )

def contains_gateway_lifecycle_command(text: str) -> bool:
    """Return True if *text* contains a gateway lifecycle command pattern.

    Passes, in order: raw-text regex (the only pass that fires on inputs shlex cannot tokenize, e.g.
    Python source); profile-flag form; the same regex on each shell-tokenized segment with quotes/
    escapes resolved (closes splice bypasses like ``kick"start"`` / ``kick\\start``);
    order-independent launchctl pass. Single choke point for every recursion level of
    ``_contains_unsafe_gateway_action``.

    That second pass exists because a real shell resolves quote-splicing (``kick"start"``) and
    backslash-escaping (``kick\\start``) into one literal word — ``kickstart`` — before the command ever
    runs. The raw text still has the quote or backslash sitting between the verb's two halves, so the first
    pass alone lets a spliced verb reach ``launchctl``/``systemctl`` untouched while still executing as the
    blocked lifecycle command (#80269, reported against #80260's bootout parity fix). Tokenizing closes that
    gap while keeping the same gateway-label anchoring (``_GATEWAY_LIFECYCLE_PATTERN`` still requires a
    ``hermes``/``gateway`` token) — this function is the single choke point
    ``_contains_unsafe_gateway_action`` calls at every recursion level, so referenced-script and ``sh -c``
    payload scanning inherit the fix automatically.
    """
    if not text:
        return False
    # Provably inert heredoc bodies (quoted delimiter, data-sink consumer like `cat > f <<'EOF'`)
    # are documentation, not commands. The stripper fails open on ANY ambiguity (unquoted delimiter,
    # shell consumer, unterminated body), so executable heredocs are still scanned.
    # Heredoc bodies that are provably inert data (quoted delimiter, data-sink consumer like `cat > file
    # <<'EOF'`) are masked before scanning (#88336): a runbook line "a human can run: hermes gateway
    # restart" inside such a body is documentation, not a command this shell will execute.
    from capri._vendor.hermes.compat.shell_heredoc import strip_inert_heredoc_bodies

    text = strip_inert_heredoc_bodies(text)
    normalized = _SHELL_LINE_CONTINUATION.sub(" ", text)
    if _GATEWAY_LIFECYCLE_PATTERN.search(normalized):
        return True
    # Profile-flag form: blocked only when the named profile IS the one running the guard.
    # Profile-flag form (#78028): `hermes -p <profile> gateway restart|stop` bypasses Branch A because the
    # selector sits between `hermes` and `gateway`. It is only the same foot-gun when the named profile IS
    # the profile running the guard — sibling-profile restarts are legitimate fleet operations and stay
    # allowed.
    profile_match = _PROFILE_FLAG_LIFECYCLE_PATTERN.search(normalized)
    if profile_match:
        named = profile_match.group(1) or profile_match.group(2)
        # Profile ids cannot contain quotes (`^[a-z0-9][a-z0-9_-]{0,63}$`), so a shell-quoted
        # `-p 'zeus'` compares equal to the bare name.
        if named and _named_profile_is_current(named.strip().strip("\"'")):
            return True
    # Token-aware pass. Tokens are also re-joined with Python argv-list punctuation stripped, since
    # `subprocess.run(["launchctl", "bootout", ...])` separates argv words with commas/brackets.
    # Token-aware second pass (#80269): re-run the pattern on shell-tokenized segments where quotes/escapes
    # are resolved, closing splice bypasses like `kick"start"`. Runs after the profile-flag check so both
    # passes apply independently.
    for segment in _iter_command_segments(normalized):
        joined = " ".join(segment)
        if joined and _GATEWAY_LIFECYCLE_PATTERN.search(joined):
            return True
        stripped = _ARGV_LIST_PUNCTUATION.sub(" ", joined)
        if stripped != joined and _GATEWAY_LIFECYCLE_PATTERN.search(stripped):
            return True
    # The label may be built in an earlier `;`-segment, so no pass above sees verb + label together.
    # Order-independent launchctl pass (#77083): a shell loop can build the gateway label from a variable
    # defined in an earlier `;`-separated segment (`label=${item%%:*}; launchctl bootout
    # "gui/$uid/$label"`), so neither the same-span regex nor same-segment tokenization sees verb and label
    # together. Check "verb anywhere AND label anywhere" instead.
    # Branch E (#113667): killers aimed at the interpreter image itself carry no hermes/gateway token.
    return _contains_launchctl_gateway_lifecycle(normalized) or contains_host_interpreter_kill(normalized)

def _split_logical_lines(text: str) -> list[str]:
    """Split on newlines outside quotes (a quoted newline is data, not a separator); honors
    escapes."""
    lines: list[str] = []
    current: list[str] = []
    in_single = in_double = escape = False
    for ch in text:
        if escape:
            escape = False
        elif ch == "\\":
            escape = True
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "\n" and not in_single and not in_double:
            lines.append("".join(current))
            current = []
            continue
        current.append(ch)
    if current:
        lines.append("".join(current))
    return lines

def _shlex_tokens(line: str) -> list[str]:
    """POSIX-tokenize one shell line, honoring quotes and `#` comments; raises ValueError."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    return list(lexer)

def _split_segments(tokens: list[str], *, keep_controls: bool = False) -> Iterator[list[str]]:
    """Yield non-empty runs of *tokens* between control-operator tokens; with *keep_controls* each
    control token is also yielded as its own segment so the line can be rebuilt in order."""
    segment: list[str] = []
    for token in tokens:
        if token and set(token) <= _CONTROL_CHARS:
            if segment:
                yield segment
                segment = []
            if keep_controls:
                yield [token]
            continue
        segment.append(token)
    if segment:
        yield segment

def _iter_command_segments(command: str) -> Iterator[list[str]]:
    """Yield shell-tokenized command segments per logical line; a line shlex rejects (unbalanced
    quotes) falls back to per-physical-line tokenization."""
    for line in _split_logical_lines(command.replace("\\\n", "")):
        try:
            tokens = _shlex_tokens(line)
        except ValueError:
            for physical_line in line.splitlines():
                try:
                    yield from _split_segments(_shlex_tokens(physical_line))
                except ValueError:
                    continue
            continue
        yield from _split_segments(tokens)

def _executable_name(token: str) -> str:
    """Command name of an executable token. ``Path(token).name`` is "" for ``.``, ``..`` and ``/``;
    the POSIX dot-source builtin is spelled ``.``, so fall back to the raw token or ``.
    ./helper.sh`` would escape the sourced-script scan."""
    return Path(token).name or token

def _peel_transparent_prefixes(segment: list[str], index: int) -> int:
    """Index of the command a wrapper chain actually executes. Unchanged if not a wrapper; may be
    ``len(segment)`` when a wrapper has no operand — callers must bounds-check."""
    for _ in range(_MAX_PREFIX_PEELS):
        if index >= len(segment):
            return index
        name = _executable_name(segment[index])
        if name not in _TRANSPARENT_COMMAND_PREFIXES:
            return index
        value_options = _TRANSPARENT_PREFIX_VALUE_OPTIONS.get(name, frozenset())
        index += 1
        while index < len(segment):
            token = segment[index]
            if token == "--":
                # POSIX end-of-options: the command starts at the next token.
                index += 1
                break
            if token in value_options:
                index += 2
                continue
            if token.startswith("-") or _ENV_ASSIGNMENT.match(token):
                index += 1
                continue
            break
        for _ in range(_TRANSPARENT_PREFIX_OPERANDS.get(name, 0)):
            if index < len(segment) and not segment[index].startswith("-"):
                index += 1
    return index

def _command_token_index(segment: list[str]) -> Optional[int]:
    """Return the executable token index after simple env assignments."""
    return next((i for i, token in enumerate(segment) if not _ENV_ASSIGNMENT.match(token)), None)

def _executed_command_index(segment: list[str]) -> Optional[int]:
    """Index of the command a segment actually executes (env assignments and wrappers peeled)."""
    index = _command_token_index(segment)
    if index is None:
        return None
    index = _peel_transparent_prefixes(segment, index)
    return index if index < len(segment) else None
