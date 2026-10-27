"""Execute the real PowerShell tool/bootstrap boundaries with local downloads."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows bootstrap')


def ps(value):
    return "'" + str(value).replace("'", "''") + "'"


def shell(code, cwd=None, env=None):
    return subprocess.run([shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-Command', code],
                          cwd=cwd, env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)


def archive_case(tmp_path, expected_hash=None):
    archive = tmp_path / 'fixture.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('tool/tool.cmd', '@echo 1.2.3\r\n')
    record = {'url': 'https://example.invalid/tool.zip',
              'sha256': expected_hash or hashlib.sha256(archive.read_bytes()).hexdigest(),
              'executable': 'tool/tool.cmd', 'version': '1.2.3'}
    manifest = tmp_path / 'record.json'
    manifest.write_text(json.dumps(record), encoding='utf-8')
    tools = tmp_path / 'tools з пробілами'
    code = f"""
$ErrorActionPreference = 'Stop'
. {ps(ROOT / 'scripts/bootstrap-tools.ps1')}
function Invoke-WebRequest {{ param($Uri, $OutFile) Copy-Item -LiteralPath {ps(archive)} -Destination $OutFile; Add-Content {ps(tmp_path / 'downloads')} 'download' }}
$record = Get-Content -Raw {ps(manifest)} | ConvertFrom-Json -AsHashtable
$before = @{{ env = @{{}}; cwd = (Get-Location).Path }}
Get-ChildItem Env: | ForEach-Object {{ $before.env[$_.Name] = $_.Value }}
$tool = Install-CapriArchive -Name fixture -Record $record -ToolsRoot {ps(tools)}
& $tool --version
if ($LASTEXITCODE) {{ throw 'tool failed' }}
$after = @{{ env = @{{}}; cwd = (Get-Location).Path }}
Get-ChildItem Env: | ForEach-Object {{ $after.env[$_.Name] = $_.Value }}
if (($before | ConvertTo-Json -Depth 5 -Compress) -ne ($after | ConvertTo-Json -Depth 5 -Compress)) {{
    # Hashtable ordering is not stable: compare keys and values instead.
    if ($before.cwd -ne $after.cwd -or $before.env.Count -ne $after.env.Count) {{ throw 'caller changed' }}
    foreach ($key in $before.env.Keys) {{ if ($before.env[$key] -ne $after.env[$key]) {{ throw "leaked $key" }} }}
}}
"""
    return tools, code


def test_download_hash_mismatch_is_not_executed(tmp_path):
    tools, code = archive_case(tmp_path, '0' * 64)
    result = shell(code)
    assert result.returncode != 0
    assert 'SHA-256' in result.stderr
    assert not (tools / 'fixture').exists()


def test_incomplete_tmp_download_is_downloaded_again(tmp_path):
    tools, code = archive_case(tmp_path)
    tools.mkdir()
    (tools / 'fixture.download.tmp').write_bytes(b'incomplete')
    result = shell(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '1.2.3' in result.stdout
    assert (tmp_path / 'downloads').read_text().splitlines() == ['download']
    assert not (tools / 'fixture.download.tmp').exists()


def test_tools_ignore_global_versions_and_reuse_verified_install(tmp_path):
    tools, code = archive_case(tmp_path)
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    (foreign / 'tool.cmd').write_text('@echo 0.0.0\n', encoding='utf-8')
    env = dict(os.environ, PATH=str(foreign) + os.pathsep + os.environ['PATH'])
    for _ in range(2):
        result = shell(code, env=env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert '1.2.3' in result.stdout and '0.0.0' not in result.stdout
    assert (tmp_path / 'downloads').read_text().splitlines() == ['download']


def test_tool_setup_preserves_caller_environment(tmp_path):
    _, code = archive_case(tmp_path)
    result = shell(code, cwd=tmp_path, env=dict(os.environ, RUSTUP_HOME='foreign-rust-root'))
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_wrong_tool_directory_is_not_removed(tmp_path):
    tools, code = archive_case(tmp_path)
    sentinel = tools / 'fixture/do-not-remove'
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'user file')
    result = shell(code)
    assert result.returncode != 0
    assert sentinel.read_bytes() == b'user file'
    assert not (tmp_path / 'downloads').exists()


def bootstrap_case(tmp_path):
    """Real entry point; double system discovery, pip, and expensive build."""
    checkout = tmp_path / 'Capri копія'
    scripts = checkout / 'scripts'
    scripts.mkdir(parents=True)
    source = ROOT / 'scripts/bootstrap.ps1'
    assert source.exists(), 'bootstrap entry point is missing'
    shutil.copy2(source, scripts / source.name)
    (checkout / 'runtime-toolchain.json').write_text('{}', encoding='utf-8')
    shutil.copy2(ROOT / 'requirements-test.txt', checkout / 'requirements-test.txt')
    # A real venv Python; pip subprocess is doubled, not the bootstrap.
    import venv
    venv.EnvBuilder(with_pip=False).create(checkout / '.venv')
    site = checkout / '.venv/Lib/site-packages'
    (site / 'pip.py').write_text("import pathlib; pathlib.Path('pip-called').write_text(' '.join(__import__('sys').argv), encoding='utf-8')\n", encoding='utf-8')
    sdk = checkout / 'vendor/omp/sdk/python/omp-rpc'
    sdk.mkdir(parents=True)
    dist = site / 'omp_rpc-0.1.0.dist-info'
    dist.mkdir()
    (dist / 'METADATA').write_text('Metadata-Version: 2.1\nName: omp-rpc\nVersion: 0.1.0\n')
    (dist / 'direct_url.json').write_text(json.dumps({'url': sdk.as_uri(), 'dir_info': {}}))
    (scripts / 'windows-toolchain.ps1').write_text("function Initialize-CapriWindowsToolchain { if ($env:CAPRI_TEST_MISSING) { throw 'Missing Visual Studio 2022 C++ Build Tools x64 / Windows SDK' }; return @{} }\n")
    (scripts / 'bootstrap-tools.ps1').write_text("function Initialize-CapriTools { param($Data,$Toolchain) New-Item -ItemType Directory -Force (Join-Path $Data 'tools') | Out-Null; return @{ Bun='C:/private/bun.exe'; CMake='C:/private/cmake.exe'; Ninja='C:/private/ninja.exe'; Cargo='C:/private/cargo.exe'; RustupHome='C:/private/rustup'; CargoHome='C:/private/cargo' } }\n")
    (scripts / 'verify-vendor.py').write_text("print('verified')\n")
    (scripts / 'build-runtime.ps1').write_text("param($Data) New-Item -ItemType Directory -Force (Join-Path $Data 'bin') | Out-Null; [IO.File]::WriteAllText((Join-Path $Data 'bin/omp.exe'), 'verified runtime'); $global:LASTEXITCODE=0\n")
    data = tmp_path / 'дані з пробілами'
    data.mkdir()
    command = f"""
$ErrorActionPreference='Stop'
$before=@{{}}; Get-ChildItem Env: | ForEach-Object {{ $before[$_.Name]=$_.Value }}
$cwd=(Get-Location).Path
try {{ . {ps(scripts / 'bootstrap.ps1')} -Data {ps(data)} }} finally {{
    if ((Get-Location).Path -ne $cwd) {{ throw 'cwd leaked' }}
    foreach ($key in $before.Keys) {{ if ([Environment]::GetEnvironmentVariable($key) -ne $before[$key]) {{ throw "environment leaked: $key" }} }}
    if (@(Get-ChildItem Env:).Count -ne $before.Count) {{ throw 'environment keys leaked' }}
}}
"""
    return checkout, data, command


def test_missing_system_prerequisites_stop_before_download(tmp_path):
    checkout, data, command = bootstrap_case(tmp_path)
    result = shell(command, cwd=tmp_path, env=dict(os.environ, CAPRI_TEST_MISSING='1'))
    assert result.returncode != 0
    assert 'Visual Studio 2022' in result.stderr and 'Windows SDK' in result.stderr
    assert not (data / 'tools').exists()
    assert not (checkout / 'pip-called').exists()


def test_bootstrap_installs_vendored_sdk_and_preserves_state_and_environment(tmp_path):
    checkout, data, command = bootstrap_case(tmp_path)
    sentinels = ['agent/auth.db', 'agent/config.yml', 'owner.json', 'session.json', 'guest/threads.json']
    for name in sentinels:
        p = data / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'private sentinel')
    for _ in range(2):
        result = shell(command, cwd=tmp_path, env=dict(os.environ, RUSTUP_HOME='foreign', CARGO_HOME='foreign'))
        assert result.returncode == 0, result.stdout + result.stderr
        assert (data / 'bin/omp.exe').read_text() == 'verified runtime'
        assert '-r requirements-test.txt' in (checkout / 'pip-called').read_text(encoding='utf-8')
        for name in sentinels:
            assert (data / name).read_bytes() == b'private sentinel'


def test_bootstrap_rejects_foreign_sdk_origin(tmp_path):
    checkout, data, command = bootstrap_case(tmp_path)
    origin = checkout / '.venv/Lib/site-packages/omp_rpc-0.1.0.dist-info/direct_url.json'
    origin.write_text(json.dumps({'url': 'https://example.invalid/omp-rpc.whl'}))
    result = shell(command, cwd=tmp_path)
    assert result.returncode != 0
    assert not (data / 'bin/omp.exe').exists()


def test_bootstrap_rejects_data_under_vendor_before_writes(tmp_path):
    checkout, data, command = bootstrap_case(tmp_path)
    vendor_data = checkout / 'vendor/omp'
    result = shell(command.replace(ps(data), ps(vendor_data)), cwd=tmp_path)
    assert result.returncode != 0
    assert 'outside vendor' in result.stderr
    assert not (vendor_data / 'bootstrap').exists()
    assert not (checkout / 'pip-called').exists()


def test_rust_private_environment_restored_on_version_failure(tmp_path):
    data = tmp_path / 'data'
    (data / 'tools/rust').mkdir(parents=True)
    manifest = tmp_path / 'toolchain.json'
    manifest.write_text(json.dumps({'rust_toolchain': 'nightly-pinned', 'rustc': 'pinned-rustc',
                                   'cargo': 'pinned-cargo', 'downloads': {}}))
    code = f"""
$ErrorActionPreference='Stop'
. {ps(ROOT / 'scripts/bootstrap-tools.ps1')}
function Install-CapriArchive {{ param($Name,$Record,$ToolsRoot) return (Join-Path $ToolsRoot "$Name/tool.exe") }}
function Assert-CapriTool {{
    param($Executable,$Expected,$Argument)
    if ($env:RUSTUP_HOME -ne {ps(data / 'tools/rust/rustup')} -or $env:CARGO_HOME -ne {ps(data / 'tools/rust/cargo')}) {{ throw 'wrong private roots' }}
    throw 'injected version failure'
}}
$before=@{{}}; Get-ChildItem Env: | ForEach-Object {{ $before[$_.Name]=$_.Value }}
try {{ Initialize-CapriTools -Data {ps(data)} -Toolchain (Get-Content {ps(manifest)} -Raw | ConvertFrom-Json -AsHashtable); throw 'expected failure' }}
catch {{ if ($_.ToString() -notmatch 'injected version failure') {{ throw }} }}
foreach ($key in $before.Keys) {{ if ([Environment]::GetEnvironmentVariable($key) -ne $before[$key]) {{ throw "leaked $key" }} }}
if (@(Get-ChildItem Env:).Count -ne $before.Count) {{ throw 'environment keys leaked' }}
"""
    result = shell(code, env=dict(os.environ, RUSTUP_HOME='foreign', CARGO_HOME='foreign'))
    assert result.returncode == 0, result.stdout + result.stderr
