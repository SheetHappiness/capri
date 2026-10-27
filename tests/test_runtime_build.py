"""Windows contracts for source build, auth-free smoke and final publication.

Only external build tools and smoke are doubled. The build script itself must
be copied from the repository and executed, never replaced with a passing fake.
Failures must preserve the previous executable and private Capri state.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows x64 PowerShell build contract")

ROOT = Path(__file__).resolve().parents[1]
STAGES = ["install", "native", "binary", "smoke"]
ADDON = "packages/natives/native/pi_natives.win32-x64-baseline.node"
BINARY = "packages/coding-agent/binaries/omp-windows-x64.exe"
ENV_KEYS = [
    "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS",
    "CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS", "RUSTUP_TOOLCHAIN",
    "OMP_NATIVE_FEATURES", "OMP_NATIVE_CARGO_PROFILE", "OMP_NATIVE_BUILD_BACKEND",
    "PI_NATIVE_VARIANT", "CARGO_BUILD_JOBS", "CARGO_HOME", "CARGO_TARGET_DIR",
    "RUSTC", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "CARGO_BUILD_RUSTC",
    "CARGO_BUILD_RUSTC_WRAPPER", "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER", "CARGO_BUILD_TARGET",
    "BUN_INSTALL_CACHE_DIR", "BUN_RUNTIME_TRANSPILER_CACHE_PATH", "BUN_TMPDIR",
    "TEMP", "TMP", "HOME", "USERPROFILE", "PATH", "LIB", "INCLUDE",
]

# Test-only tool boundary: emits artifacts only for successful build commands.
# Each call records argv/cwd and selected non-secret environment values.
TOOL_DRIVER = r'''
import hashlib
import json
import os
from pathlib import Path
import sys
import time

tool, args = sys.argv[1], sys.argv[2:]
stage = None
if tool == "smoke":
    stage = "smoke"
elif tool == "bun" and args and args[0] == "install":
    stage = "install"
elif tool == "bun" and ("build:native" in args or
        ("build" in args and any("packages/natives" in a for a in args))):
    stage = "native"
elif tool == "bun" and any("ci-release-build-binaries.ts" in a for a in args):
    stage = "binary"
event = {"tool": tool, "argv": args, "cwd": os.getcwd(), "stage": stage,
         "env": {key: os.environ.get(key) for key in json.loads(os.environ["CAPRI_TEST_ENV_KEYS"])}}
with open(os.environ["CAPRI_TEST_CALLS"], "a", encoding="utf-8") as output:
    output.write(json.dumps(event, ensure_ascii=False) + "\n")
scenario = os.environ.get("CAPRI_TEST_SCENARIO", "success")
if scenario == "wrong_" + tool:
    print("0.0.0")
    raise SystemExit(0)
if stage and scenario == "fail_" + stage:
    print("injected failure: " + stage, file=sys.stderr)
    raise SystemExit(19)
if stage == "smoke" and scenario == "smoke_timeout":
    # Interruptible; the test's outer timeout is a harness watchdog, not PASS.
    time.sleep(300)
if stage == "native" and scenario != "missing_native":
    output = Path("packages/natives/native/pi_natives.win32-x64-baseline.node")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"fresh-baseline-addon")
if stage == "binary":
    if scenario == "lock_drift":
        Path("Cargo.lock").write_bytes(b"unexpected lockfile rewrite")
    if scenario == "source_drift":
        (Path(os.environ["CAPRI_TEST_CHECKOUT"]) / "vendor/omp/source.ts").write_bytes(b"changed")
    if scenario not in ("missing_binary", "stale_binary"):
        output = Path("packages/coding-agent/binaries/omp-windows-x64.exe")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fresh-candidate-exe")
if stage == "smoke":
    exe = Path(args[args.index("--omp") + 1])
    data = Path(args[args.index("--data") + 1])
    assert exe.is_absolute() and data.is_absolute()
    assert not data.exists() or not any(data.iterdir()), "smoke must receive fresh scratch"
    data.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "passed": True,
              "executable_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
              "native_sha256": hashlib.sha256(b"fresh-baseline-addon").hexdigest(),
              **{key: True for key in ("cli", "worker", "config", "rpc", "native_extraction", "teardown")}}
    if scenario == 'false_smoke':
        report['teardown'] = False
    (data / "smoke-result.json").write_text(json.dumps(report), encoding="utf-8")
    if scenario == 'changed_candidate':
        exe.write_bytes(b'changed after smoke')
versions = json.loads(os.environ["CAPRI_TEST_VERSIONS"])
if not stage:
    if tool == "bun":
        print(versions["bun_revision"] if "--revision" in args else versions["bun"])
    elif tool in ("cargo", "rustc"):
        print(versions[tool])
    elif tool == "rustup":
        print(versions["rust_toolchain"] + "-x86_64-pc-windows-msvc (default)")
    elif tool == "cmake":
        print("cmake version " + versions["cmake"])
    elif tool == "ninja":
        print(versions["ninja"])
    elif tool == "cl":
        print("Microsoft (R) C/C++ Optimizing Compiler Version " + versions["msvc_compiler"] + " for x64")
    elif tool == "vswhere":
        print(os.environ["CAPRI_TEST_VS"])
'''


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ps_string(value):
    return "'" + str(value).replace("'", "''") + "'"


class BuildCase:
    def __init__(self, root):
        self.root = root
        self.checkout = root / "Capri копія з пробілами"
        self.data = self.checkout / ".runtime"
        self.tools = root / "stub tools"
        self.calls_path = root / "calls.jsonl"
        self.caller = root / "інший cwd"
        self.caller.mkdir(parents=True)
        self.versions = json.loads((ROOT / "runtime-toolchain.json").read_text(encoding="utf-8"))
        _write(self.checkout / "runtime-toolchain.json", json.dumps(self.versions))
        _write(self.checkout / "scripts/verify-vendor.py",
               (ROOT / "scripts/verify-vendor.py").read_text(encoding="utf-8"))
        # This is an external smoke double in the temporary checkout, not the
        # production smoke script and not an implementation of build-runtime.
        _write(self.tools / "driver.py", TOOL_DRIVER)
        _write(self.checkout / "scripts/smoke-runtime.py",
               "import runpy, sys\nsys.argv.insert(1, 'smoke')\n"
               f"runpy.run_path({str(self.tools / 'driver.py')!r}, run_name='__main__')\n")
        source = {
            "source.ts": "export const fixture = true;\n",
            "bun.lock": "frozen-bun-lock\n", "Cargo.lock": "frozen-cargo-lock\n",
            "package.json": '{"name":"omp","version":"18.12.6","private":true}',
            "LICENSE": "fixture license\n", "THIRD-PARTY-NOTICES.txt": "fixture notices\n",
        }
        for name, content in source.items():
            _write(self.checkout / "vendor/omp" / name, content)
        manifest = {
            "schema_version": 1,
            "upstream": {"commit": "45c35e40c46166dc726ccc52f5d27f40f2449f99",
                         "archive_sha256": "a8bbb85ede151ed58c100e84e6d239ca835937e04a51cd287049a9ff737fd4e2"},
            "files": {name: _hash(self.checkout / "vendor/omp" / name) for name in source},
            "patches": {}, "additions": {}, "records": {},
        }
        _write(self.checkout / "vendor/omp-source-manifest.json", json.dumps(manifest))
        self.versions["source_lock_sha256"] = {
            name: manifest["files"][name] for name in ("bun.lock", "Cargo.lock")}
        _write(self.checkout / "runtime-toolchain.json", json.dumps(self.versions))
        # Install no packages and do not contact registries. Give preflight a
        # real Python interpreter plus local SDK-origin distribution metadata.
        venv.EnvBuilder(with_pip=False).create(self.checkout / ".venv")
        site = self.checkout / ".venv/Lib/site-packages"
        sdk = self.checkout / "vendor/omp/sdk/python/omp-rpc"
        sdk.mkdir(parents=True)
        _write(site / "omp_rpc-0.1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: omp-rpc\nVersion: 0.1.0\n")
        _write(site / "omp_rpc-0.1.0.dist-info/direct_url.json",
               json.dumps({"url": sdk.as_uri(), "dir_info": {}}))
        for tool in ("bun", "rustc", "cargo", "rustup", "cmake", "ninja", "cl", "link", "vswhere"):
            _write(self.tools / (tool + ".cmd"),
                   f'@"{sys.executable}" "%~dp0driver.py" {tool} %*\n')
        self.env = dict(os.environ)
        self.env.update({
            "PATH": os.pathsep.join([str(self.tools), str(Path(shutil.which("pwsh")).parent),
                                      str(Path(os.environ["SystemRoot"]) / "System32")]),
            "CAPRI_TEST_CALLS": str(self.calls_path), "CAPRI_TEST_ENV_KEYS": json.dumps(ENV_KEYS),
            "CAPRI_TEST_VERSIONS": json.dumps(self.versions), "CAPRI_TEST_CHECKOUT": str(self.checkout),
            "CAPRI_TEST_VS": str(self.tools / "VS"), "PYTHONUTF8": "1",
            "VCToolsVersion": self.versions["msvc_toolset_directory"],
            "WindowsSDKVersion": self.versions["windows_sdk"] + "\\",
            "VSCMD_ARG_TGT_ARCH": "x64", "VSCMD_VER": "17.14.0",
            "LIB": "test-msvc-lib", "INCLUDE": "test-msvc-include",
        })
        sdk_root = self.tools / 'SDK'
        self.env['WindowsSdkDir'] = str(sdk_root)
        for name in ('Include/{v}/um/Windows.h', 'Include/{v}/ucrt/corecrt.h', 'Lib/{v}/um/x64/kernel32.lib', 'Lib/{v}/ucrt/x64/ucrt.lib', 'bin/{v}/x64/rc.exe'):
            _write(sdk_root / name.format(v=self.versions['windows_sdk']), '')
        self.private = {}
        for name, value in {
            "bin/omp.exe": b"old-good-exe", "bin/runtime-build.json": b'{"old":true}\n',
            "agent/auth.db": b"synthetic auth, no credentials", "agent/config.yml": b"permission: ask\n",
            "agent/sessions/owner.jsonl": b"synthetic transcript\n", "session.json": b'{"session":"old"}',
            "owner.json": b'{"owner_id":123}', "guest/threads.json": b'{"threads":[]}',
            "guest/sessions/123/456/session.jsonl": b"synthetic guest\n",
            "capri-isolation.yml": b"synthetic config\n",
        }.items():
            path = self.data / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
            self.private[path] = value

    def events(self):
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text(encoding="utf-8").splitlines()]

    def stages(self):
        return [event["stage"] for event in self.events() if event["stage"]]

    def assert_preserved(self, *, artifact=True):
        for path, content in self.private.items():
            if artifact or path.parent != self.data / "bin":
                assert path.read_bytes() == content, f"build changed private sentinel: {path}"

    def run(self, scenario="success", *, data_arg=None, dot_source=False):
        script = ROOT / "scripts/build-runtime.ps1"
        assert script.is_file(), "RED: scripts/build-runtime.ps1 is not implemented (Task 4 Step 1)"
        shutil.copy2(script, self.checkout / "scripts/build-runtime.ps1")
        helper = ROOT / 'scripts/windows-toolchain.ps1'
        if helper.exists():
            shutil.copy2(helper, self.checkout / 'scripts/windows-toolchain.ps1')
        self.env["CAPRI_TEST_SCENARIO"] = scenario
        shell = shutil.which("pwsh")
        assert shell, "PowerShell 7 is required for the Windows build contract tests"
        snapshot = self.root / "caller-state.json"
        invocation = "." if dot_source else "&"
        command = f"""
$ErrorActionPreference = 'Stop'
$before = @{{cwd=(Get-Location).Path; env=@{{}}}}
Get-ChildItem Env: | ForEach-Object {{ $before.env[$_.Name] = $_.Value }}
$code = 0
try {{
    {invocation} {_ps_string(self.checkout / 'scripts/build-runtime.ps1')} -Data {_ps_string(data_arg if data_arg is not None else self.data)} -SmokeTimeoutSeconds 2
    if ($LASTEXITCODE) {{ $code = $LASTEXITCODE }}
}} catch {{
    [Console]::Error.WriteLine($_.ToString())
    $code = 1
}} finally {{
    $after = @{{cwd=(Get-Location).Path; env=@{{}}}}
    Get-ChildItem Env: | ForEach-Object {{ $after.env[$_.Name] = $_.Value }}
    @{{before=$before; after=$after}} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath {_ps_string(snapshot)} -Encoding utf8
}}
exit $code
"""
        process = subprocess.Popen([shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
                                   cwd=self.caller, env=self.env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            stdout, stderr = process.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            # A broken timeout implementation must not leave the sleep double
            # (or any build child) running after pytest exits.
            subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"),
                            "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
            process.communicate(timeout=10)
            pytest.fail("build exceeded 45s harness watchdog; child-tree cleanup requested")
        result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        assert snapshot.is_file(), "build terminated its caller before state could be inspected"
        caller = json.loads(snapshot.read_text(encoding="utf-8-sig"))
        assert caller["before"] == caller["after"], "build leaked environment/cwd changes into caller"
        return result


@pytest.fixture
def build_case(tmp_path):
    assert shutil.which("pwsh"), "PowerShell 7 is required"
    return BuildCase(tmp_path)


@pytest.mark.parametrize("scenario,expected_stages", [
    ("source_verification", []),
    ("fail_install", ["install"]), ("fail_native", ["install", "native"]),
    ("fail_binary", ["install", "native", "binary"]),
    ("fail_smoke", STAGES), ("smoke_timeout", STAGES),
    ("missing_native", ["install", "native"]),
    ("missing_binary", ["install", "native", "binary"]),
])
def test_failed_stage_preserves_runtime_and_state(build_case, scenario, expected_stages):
    case = build_case
    if scenario == "source_verification":
        (case.checkout / "vendor/omp/source.ts").write_bytes(b"unrecorded source change")
    result = case.run(scenario)
    assert result.returncode != 0, result.stdout + result.stderr
    assert case.stages() == expected_stages, result.stdout + result.stderr
    case.assert_preserved()


@pytest.mark.parametrize("tool", ["bun", "rustc", "cargo", "cmake", "ninja"])
@pytest.mark.parametrize("problem", ["missing", "wrong"])
def test_toolchain_preflight_rejects_missing_or_wrong_tools(build_case, tool, problem):
    case = build_case
    if problem == "missing":
        (case.tools / (tool + ".cmd")).unlink()
    result = case.run(problem + "_" + tool)
    assert result.returncode != 0, result.stdout + result.stderr
    assert case.stages() == [], "preflight failure must prevent every build/smoke stage"
    case.assert_preserved()


def test_build_overrides_inherited_flags_and_caches(build_case):
    case = build_case
    poisoned = ["RUSTFLAGS", "RUSTUP_TOOLCHAIN", "CARGO_ENCODED_RUSTFLAGS", "CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS",
                "OMP_NATIVE_FEATURES", "OMP_NATIVE_CARGO_PROFILE", "OMP_NATIVE_BUILD_BACKEND",
                "PI_NATIVE_VARIANT", "CARGO_BUILD_JOBS", "CARGO_HOME", "CARGO_TARGET_DIR",
                "BUN_INSTALL_CACHE_DIR", "BUN_RUNTIME_TRANSPILER_CACHE_PATH", "BUN_TMPDIR", "TEMP", "TMP"]
    case.env.update({key: "foreign-state" for key in poisoned})
    case.env["RUSTFLAGS"] = "-C target-cpu=native"
    result = case.run()
    assert result.returncode == 0, result.stdout + result.stderr
    # Keep checking the Step 2 environment even while the full pipeline still
    # lacks Step 3 smoke. The final assertion remains the future RED contract.
    for event in case.events():
        if event["stage"] not in ("install", "native", "binary"):
            continue
        env = event["env"]
        for key, suffix in {
            "CARGO_HOME": "cache/cargo", "CARGO_TARGET_DIR": "build/target",
            "BUN_INSTALL_CACHE_DIR": "cache/bun", "BUN_RUNTIME_TRANSPILER_CACHE_PATH": "cache/transpiler",
            "TEMP": "tmp", "TMP": "tmp", "BUN_TMPDIR": "tmp",
        }.items():
            assert Path(env[key]) == case.data / suffix, (event["stage"], key, env[key])
        assert env["HOME"] == case.env.get("HOME")
        assert env["USERPROFILE"] == case.env.get("USERPROFILE")
        assert env["LIB"] == "test-msvc-lib" and env["INCLUDE"] == "test-msvc-include"
    native = next(e for e in case.events() if e["stage"] == "native")["env"]
    assert native["RUSTFLAGS"] == "-C target-feature=+crt-static -C target-cpu=x86-64-v2"
    assert native["CARGO_ENCODED_RUSTFLAGS"] in (None, "")
    assert native["CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS"] in (None, "")
    assert native["OMP_NATIVE_FEATURES"] in (None, "")
    assert native["PI_NATIVE_VARIANT"] == "baseline"
    assert native["OMP_NATIVE_CARGO_PROFILE"] == "ci"
    assert native["OMP_NATIVE_BUILD_BACKEND"] == "cargo"
    assert native["RUSTUP_TOOLCHAIN"] == "nightly-2026-10-06"
    assert native["CARGO_BUILD_JOBS"] == "8"
    case.assert_preserved(artifact=False)
    assert case.stages() == STAGES


@pytest.mark.parametrize("scenario", ["success", "fail_native"])
@pytest.mark.parametrize("dot_source", [False, True], ids=["invoke", "dot-source"])
def test_paths_and_caller_state(build_case, scenario, dot_source):
    case = build_case
    case.env.pop("CARGO_ENCODED_RUSTFLAGS", None)
    case.env["OMP_NATIVE_FEATURES"] = ""
    relative_data = os.path.relpath(case.data, case.caller)
    result = case.run(scenario, data_arg=relative_data, dot_source=dot_source)
    assert (result.returncode == 0) == (scenario == "success"), result.stdout + result.stderr
    expected = STAGES if scenario == "success" else ["install", "native"]
    assert case.stages() == expected
    for event in case.events():
        if event["stage"] in ("install", "native", "binary"):
            cwd = Path(event["cwd"])
            assert cwd.is_absolute() and cwd.is_relative_to(case.data / "build"), event
    if scenario == "success":
        smoke = next(e for e in case.events() if e["stage"] == "smoke")
        exe = Path(smoke["argv"][smoke["argv"].index("--omp") + 1])
        scratch = Path(smoke["argv"][smoke["argv"].index("--data") + 1])
        assert exe.is_absolute() and exe.parent == case.data / "bin"
        assert scratch.is_absolute() and scratch.is_relative_to(case.data / "s")
        assert scratch != case.data and exe != case.data / "bin/omp.exe"
    case.assert_preserved(artifact=scenario != "success")


@pytest.mark.parametrize("scenario", ["stale_binary", "lock_drift", "source_drift"])
def test_no_stale_artifact_promotion(build_case, scenario):
    case = build_case
    for name in (ADDON, BINARY):
        path = case.checkout / "vendor/omp" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stale artifact from a previous build")
    result = case.run(scenario)
    assert result.returncode != 0, result.stdout + result.stderr
    assert case.stages()[:3] == ["install", "native", "binary"]
    assert "smoke" not in case.stages(), "invalid candidate reached smoke/promotion"
    case.assert_preserved()


def test_build_command_contract(build_case):
    case = build_case
    result = case.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert case.stages() == STAGES
    install = next(e for e in case.events() if e["stage"] == "install")
    assert "--frozen-lockfile" in install["argv"] and "--ignore-scripts" in install["argv"]
    binary = next(e for e in case.events() if e["stage"] == "binary")
    args = binary["argv"]
    assert ("--targets" in args and args[args.index("--targets") + 1] == "win32-x64"
            or "--targets=win32-x64" in args)
    for event in case.events():
        assert not any(arg in ("setup", "link", "publish") for arg in event["argv"])
    assert (case.data / "bin/omp.exe").read_bytes() == b"fresh-candidate-exe"
    case.assert_preserved(artifact=False)


def test_fixture_source_passes_real_verifier(build_case):
    """Harness control: later RED failures must not come from an invalid fixture."""
    case = build_case
    result = subprocess.run([sys.executable, str(case.checkout / "scripts/verify-vendor.py"),
                             "--root", str(case.checkout)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_stub_failure_records_call_without_emitting_artifact(build_case):
    """Harness control: the native failure double must actually stop artifact creation."""
    case = build_case
    env = dict(case.env, CAPRI_TEST_SCENARIO="fail_native")
    result = subprocess.run([sys.executable, str(case.tools / "driver.py"), "bun", "run", "build:native"],
                            cwd=case.checkout / "vendor/omp", env=env, capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == 19
    assert case.stages() == ["native"]
    assert not (case.checkout / "vendor/omp" / ADDON).exists()


def test_stub_tools_are_invocable_from_powershell(build_case):
    """Harness control: exercise CMD argv transport, Unicode paths and real venv Python."""
    case = build_case
    source = case.checkout / "vendor/omp"
    python = case.checkout / ".venv/Scripts/python.exe"
    scratch = case.data / "s/control"
    commands = [
        f"& {_ps_string(case.tools / 'bun.cmd')} install --frozen-lockfile --ignore-scripts",
        f"& {_ps_string(case.tools / 'bun.cmd')} run build:native",
        f"& {_ps_string(case.tools / 'bun.cmd')} scripts/ci-release-build-binaries.ts --targets win32-x64",
        f"& {_ps_string(python)} {_ps_string(case.checkout / 'scripts/smoke-runtime.py')} "
        f"--omp {_ps_string(source / BINARY)} --data {_ps_string(scratch)}",
    ]
    command = "\n".join(line + "\nif ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }" for line in commands)
    result = subprocess.run([shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-NonInteractive",
                             "-Command", command], cwd=source, env=case.env,
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert case.stages() == STAGES
    report = json.loads((scratch / "smoke-result.json").read_text(encoding="utf-8"))
    assert report["executable_sha256"] == _hash(source / BINARY)
    assert next(e for e in case.events() if e["stage"] == "smoke")["argv"] == [
        "--omp", str(source / BINARY), "--data", str(scratch)]


def _candidate(case):
    reports = list((case.data / "build").glob("*/candidate-result.json"))
    assert reports, "successful candidate build must record its staging path and hash"
    report = json.loads(reports[-1].read_text(encoding="utf-8-sig"))
    candidate = Path(report.get("executable_path", report["candidate_path"]))
    assert candidate.is_absolute() and candidate.parent == case.data / "bin"
    assert candidate.name == "omp.exe"
    assert candidate.read_bytes() == b"fresh-candidate-exe"
    assert report["executable_sha256"] == _hash(candidate)
    assert report["native_sha256"] == hashlib.sha256(b"fresh-baseline-addon").hexdigest()
    assert report["status"] == "published"
    assert report["smoke_passed"] is True and report["promoted"] is True
    return candidate


def test_pipeline_builds_fresh_candidate_then_smokes_and_publishes(build_case):
    case = build_case
    # A previously generated addon/binary must not enter the verified snapshot.
    for name in (ADDON, BINARY):
        path = case.checkout / "vendor/omp" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stale build output")
    result = case.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert case.stages() == STAGES
    first = _candidate(case)
    case.assert_preserved(artifact=False)
    result = case.run()
    assert result.returncode == 0, result.stdout + result.stderr
    reports = list((case.data / "build").glob("*/candidate-result.json"))
    assert len(reports) == 2
    candidates = {Path(json.loads(p.read_text(encoding="utf-8-sig"))["candidate_path"]) for p in reports}
    assert len(candidates) == 2
    assert first == case.data / 'bin/omp.exe'
    assert case.stages() == STAGES * 2
    case.assert_preserved(artifact=False)


def test_step2_environment_is_restored_after_candidate_build(build_case):
    case = build_case
    case.env.update({key: "foreign-state" for key in ENV_KEYS
                     if key not in ("HOME", "USERPROFILE", "PATH", "LIB", "INCLUDE")})
    result = case.run(data_arg=os.path.relpath(case.data, case.caller), dot_source=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert case.stages() == STAGES
    for event in case.events():
        if event["stage"] not in ("install", "native", "binary"):
            continue
        env = event["env"]
        for key, suffix in {"CARGO_HOME": "cache/cargo", "CARGO_TARGET_DIR": "build/target",
                            "BUN_INSTALL_CACHE_DIR": "cache/bun", "BUN_RUNTIME_TRANSPILER_CACHE_PATH": "cache/transpiler",
                            "TEMP": "tmp", "TMP": "tmp", "BUN_TMPDIR": "tmp"}.items():
            assert Path(env[key]) == case.data / suffix
        assert env["RUSTFLAGS"] == "-C target-feature=+crt-static -C target-cpu=x86-64-v2"
        assert not env["CARGO_ENCODED_RUSTFLAGS"]
        assert not env["CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS"]
        assert env["PI_NATIVE_VARIANT"] == "baseline"
        assert env["OMP_NATIVE_CARGO_PROFILE"] == "ci"
        assert env["OMP_NATIVE_BUILD_BACKEND"] == "cargo"
        assert not env["OMP_NATIVE_FEATURES"]
        assert env["RUSTUP_TOOLCHAIN"] == "nightly-2026-10-06"
        assert env["CARGO_BUILD_JOBS"] == "8"
        assert env["CARGO_BUILD_TARGET"] == "x86_64-pc-windows-msvc"
        for key in ("RUSTC", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "CARGO_BUILD_RUSTC",
                    "CARGO_BUILD_RUSTC_WRAPPER", "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER"):
            assert not env[key], f"inherited {key} can bypass the verified compiler"
        assert env["HOME"] == case.env.get("HOME") and env["USERPROFILE"] == case.env.get("USERPROFILE")
        assert env["LIB"] == case.env["LIB"] and env["INCLUDE"] == case.env["INCLUDE"]
        assert Path(event["cwd"]).is_relative_to(case.data / "build")
    install = next(e for e in case.events() if e["stage"] == "install")
    assert install["argv"] == ["install", "--frozen-lockfile", "--ignore-scripts"]
    binary = next(e for e in case.events() if e["stage"] == "binary")
    assert binary["argv"] == ["scripts/ci-release-build-binaries.ts", "--targets", "win32-x64"]
    _candidate(case)
    case.assert_preserved(artifact=False)


def test_step2_initializes_vs_environment_from_a_path_with_spaces(build_case):
    case = build_case
    case.env["CAPRI_TEST_PRIVATE_VALUE"] = "private-environment-value-must-not-be-logged"
    compiler = case.tools / "VS/compiler"
    compiler.mkdir(parents=True)
    shutil.move(case.tools / "cl.cmd", compiler / "cl.cmd")
    _write(compiler / "driver.py", TOOL_DRIVER)
    _write(case.tools / "VS/Common7/Tools/VsDevCmd.bat",
           f'@set "PATH=%PATH%;{compiler}"\n')
    result = case.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert case.stages() == STAGES
    logs = list((case.data / "build").glob("*/vs-environment.log"))
    assert all(case.env["CAPRI_TEST_PRIVATE_VALUE"] not in p.read_text(encoding="utf-8") for p in logs)
    _candidate(case)
    case.assert_preserved(artifact=False)


def test_build_accepts_newer_system_toolchain_and_records_actual_versions(build_case):
    case = build_case
    actual = dict(case.versions, msvc_compiler='19.45.99999')
    case.env['CAPRI_TEST_VERSIONS'] = json.dumps(actual)
    case.env['VCToolsVersion'] = '14.45.99999'
    case.env['WindowsSDKVersion'] = '10.0.99999.0\\'
    for name in ('Include/{v}/um/Windows.h', 'Include/{v}/ucrt/corecrt.h', 'Lib/{v}/um/x64/kernel32.lib', 'Lib/{v}/ucrt/x64/ucrt.lib', 'bin/{v}/x64/rc.exe'):
        _write(Path(case.env['WindowsSdkDir']) / name.format(v='10.0.99999.0'), '')
    result = case.run()
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(next((case.data / 'build').glob('*/candidate-result.json')).read_text(encoding='utf-8'))
    assert '19.45.99999' in report['tools']['msvc']
    assert report['tools']['msvc_toolset_directory'] == '14.45.99999'
    assert report['tools']['windows_sdk'] == '10.0.99999.0'


@pytest.mark.parametrize('key,value', [('VSCMD_ARG_TGT_ARCH', 'x86'), ('WindowsSDKVersion', 'missing'), ('VSCMD_VER', '16.0')])
def test_build_rejects_missing_sdk_or_wrong_architecture(build_case, key, value):
    case = build_case
    case.env[key] = value
    result = case.run()
    assert result.returncode != 0
    assert case.stages() == []
    case.assert_preserved()


@pytest.mark.parametrize('scenario', ['changed_candidate', 'false_smoke'])
def test_invalid_smoke_evidence_preserves_final(build_case, scenario):
    case = build_case
    result = case.run(scenario)
    assert result.returncode != 0
    assert case.stages() == STAGES
    case.assert_preserved()


def test_locked_destination_preserves_runtime_without_killing_bot(build_case):
    case = build_case
    with (case.data / 'bin/omp.exe').open('rb'):
        result = case.run()
    assert result.returncode != 0
    assert case.stages() == STAGES
    case.assert_preserved()


def test_missing_sdk_version_has_actionable_diagnostic(build_case):
    case = build_case
    case.env.pop('WindowsSDKVersion', None)
    result = case.run()
    assert result.returncode != 0
    assert 'Windows SDK' in result.stderr
    assert case.stages() == []
    case.assert_preserved()
