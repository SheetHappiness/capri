#Requires -Version 7.0
[CmdletBinding()]
param([string]$Data)

# A child scriptblock keeps helper functions/preferences local even when callers
# dot-source this entry point. No exit: callers retain their own process.
& {
    param([string]$RequestedData, [string]$Checkout)
    $ErrorActionPreference = 'Stop'
    $callerLocation = Get-Location
    $savedEnvironment = @{}
    Get-ChildItem Env: | ForEach-Object { $savedEnvironment[$_.Name] = $_.Value }
    $stage = 'preflight'
    $runRoot = $null
    $utf8 = [Text.UTF8Encoding]::new($false)

    function Assert-NoReparsePoint([string]$Path) {
        $current = [IO.Path]::GetFullPath($Path)
        while ($current) {
            if ([IO.File]::Exists($current) -or [IO.Directory]::Exists($current)) {
                if ([IO.File]::GetAttributes($current) -band [IO.FileAttributes]::ReparsePoint) {
                    throw "Reparse point is not permitted in build paths: $current"
                }
            }
            $current = [IO.Path]::GetDirectoryName($current)
        }
    }

    function Hash([string]$Path) {
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }

    function Tool([string]$Name) {
        $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { throw "Missing tool '$Name'. Prepare runtime-toolchain.json prerequisites on PATH." }
        $command.Source
    }

    function Quote-PowerShell([string]$Value) { "'" + $Value.Replace("'", "''") + "'" }

    function Invoke-Captured {
        param([string]$File, [string[]]$Arguments, [string]$Label,
              [int]$TimeoutSeconds = 120, [int[]]$AllowedCodes = @(0), [switch]$OmitOutputLog)
        $info = [Diagnostics.ProcessStartInfo]::new()
        $info.FileName = $File
        if ([IO.Path]::GetFileName($File) -ieq 'cmd.exe') {
            # cmd /c has its own quoting rules. ArgumentList would C-escape
            # embedded quotes as backslash-quote, which cmd treats literally.
            $info.Arguments = '/d /s /c "' + $Arguments[-1] + '"'
        } elseif ([IO.Path]::GetExtension($File) -in @('.cmd', '.bat')) {
            # ArgumentList is safe for native EXEs. CMD entry points instead go
            # through an encoded PowerShell command, with literal PS strings.
            $info.FileName = [Environment]::ProcessPath
            $command = '& ' + (Quote-PowerShell $File) + ' @(' +
                (($Arguments | ForEach-Object { Quote-PowerShell $_ }) -join ',') + '); exit $LASTEXITCODE'
            foreach ($arg in @('-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                               [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command)))) {
                $info.ArgumentList.Add($arg)
            }
        } else {
            foreach ($arg in $Arguments) { $info.ArgumentList.Add($arg) }
        }
        $info.WorkingDirectory = (Get-Location).Path
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $info
        $log = Join-Path $runRoot "$Label.log"
        try {
            if (-not $process.Start()) { throw "Cannot start $Label" }
            $stdout = $process.StandardOutput.ReadToEndAsync()
            $stderr = $process.StandardError.ReadToEndAsync()
            if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
                $process.Kill($true)
                if (-not $process.WaitForExit(10000)) { throw "Cannot confirm teardown after $Label timeout" }
                $timedOutOutput = $stdout.GetAwaiter().GetResult() + $stderr.GetAwaiter().GetResult()
                [IO.File]::WriteAllText($log, $(if ($OmitOutputLog) { 'Environment output omitted.' } else { $timedOutOutput }), $utf8)
                throw "$Label timed out after ${TimeoutSeconds}s; log: $log"
            }
            $output = $stdout.GetAwaiter().GetResult() + $stderr.GetAwaiter().GetResult()
            [IO.File]::WriteAllText($log, $(if ($OmitOutputLog) { 'Environment output omitted.' } else { $output }), $utf8)
            if ($process.ExitCode -notin $AllowedCodes) {
                throw "$Label exited $($process.ExitCode); log: $log"
            }
            $output.Trim()
        } finally {
            $process.Dispose()
        }
    }

    function Require-Version([string]$Actual, [string]$Expected, [string]$Name) {
        if ($Actual -notmatch ('(?<![\w.])' + [regex]::Escape($Expected) + '(?![\w.])')) {
            throw "Wrong $Name version: expected '$Expected'; see $runRoot"
        }
    }

    try {
        if (-not $IsWindows -or [Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -ne 'X64') {
            throw 'Runtime builds require Windows x64 and PowerShell 7 x64.'
        }
        $dataRoot = if ($RequestedData) {
            [IO.Path]::GetFullPath($RequestedData, $callerLocation.Path)
        } else { Join-Path $Checkout '.runtime' }
        $sourceRoot = Join-Path $Checkout 'vendor/omp'
        if ($dataRoot.TrimEnd('\', '/') -eq $sourceRoot -or
            $dataRoot.StartsWith($sourceRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Build Data must be outside vendor/omp.'
        }
        Assert-NoReparsePoint $dataRoot
        $runId = [Guid]::NewGuid().ToString('N').Substring(0, 12)
        $runRoot = Join-Path $dataRoot "build/$runId"
        [void][IO.Directory]::CreateDirectory($runRoot)
        $lockStream = $null
        try {
            # Protect shared Cargo target/cache as well as staging for this Data.
            $lockStream = [IO.File]::Open((Join-Path $dataRoot 'build/candidate.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
            $manifestPath = Join-Path $Checkout 'vendor/omp-source-manifest.json'
            $toolchainPath = Join-Path $Checkout 'runtime-toolchain.json'
            $toolchain = Get-Content -LiteralPath $toolchainPath -Raw | ConvertFrom-Json -AsHashtable
            $python = Join-Path $Checkout '.venv/Scripts/python.exe'
            if (-not [IO.File]::Exists($python)) { throw 'Missing checkout .venv; install requirements-test.txt first (bootstrap is a later step).' }

            $overrides = @{
                CARGO_HOME = 'cache/cargo'; CARGO_TARGET_DIR = 'build/target'
                BUN_INSTALL_CACHE_DIR = 'cache/bun'; BUN_RUNTIME_TRANSPILER_CACHE_PATH = 'cache/transpiler'
                BUN_TMPDIR = 'tmp'; TEMP = 'tmp'; TMP = 'tmp'
            }
            foreach ($key in $overrides.Keys) {
                $value = Join-Path $dataRoot $overrides[$key]
                Assert-NoReparsePoint $value
                [void][IO.Directory]::CreateDirectory($value)
                [Environment]::SetEnvironmentVariable($key, $value, 'Process')
            }
            Get-ChildItem Env: | Where-Object {
                $_.Name -in @('CARGO_ENCODED_RUSTFLAGS', 'RUSTC', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER',
                    'CARGO_BUILD_RUSTC', 'CARGO_BUILD_RUSTC_WRAPPER', 'CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER') -or
                $_.Name -match '^CARGO_TARGET_.*_RUSTFLAGS$'
            } | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
            $env:RUSTFLAGS = $toolchain.rustflags -join ' '
            $env:RUSTUP_TOOLCHAIN = $toolchain.rust_toolchain
            $env:RUSTUP_AUTO_INSTALL = '0'
            $env:CARGO_BUILD_JOBS = [string]$toolchain.cargo_jobs
            $env:CARGO_BUILD_TARGET = 'x86_64-pc-windows-msvc'
            $env:OMP_NATIVE_CARGO_PROFILE = $toolchain.profile
            $env:OMP_NATIVE_BUILD_BACKEND = 'cargo'
            $env:PI_NATIVE_VARIANT = 'baseline'
            $env:OMP_NATIVE_FEATURES = ''

            Set-Location -LiteralPath $Checkout
            $null = Invoke-Captured $python @('scripts/verify-vendor.py', '--root', $Checkout) 'verify-source'
            $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json -AsHashtable
            $manifestHash = Hash $manifestPath
            $toolchainHash = Hash $toolchainPath
            if ($manifest.upstream.commit -ne $toolchain.source_commit -or
                $manifest.upstream.archive_sha256 -ne $toolchain.source_archive_sha256) {
                throw 'Source/toolchain provenance mismatch.'
            }
            $pythonProbe = 'import importlib.metadata as m,json,sys; from pathlib import Path; assert sys.version_info[:2]==(3,14); d=m.distribution("omp-rpc"); assert d.version=="0.1.0"; o=json.loads(d.read_text("direct_url.json")); assert o["url"]==Path(sys.argv[1]).resolve().as_uri() and "dir_info" in o; print(sys.version.split()[0])'
            $pythonVersion = Invoke-Captured $python @('-c', $pythonProbe, (Join-Path $sourceRoot 'sdk/python/omp-rpc')) 'python-sdk'
            $bun = Tool 'bun'
            $bunVersion = Invoke-Captured $bun @('--version') 'bun-version'
            Require-Version $bunVersion $toolchain.bun 'Bun'
            $bunRevision = Invoke-Captured $bun @('--revision') 'bun-revision'
            if (-not $bunRevision.Contains($toolchain.bun_revision)) { throw 'Wrong Bun revision.' }
            $rustup = Tool 'rustup'
            $installed = Invoke-Captured $rustup @('toolchain', 'list') 'rust-toolchains'
            if (-not $installed.Contains($toolchain.rust_toolchain + '-x86_64-pc-windows-msvc')) { throw 'Pinned Rust toolchain is not installed; no automatic install is performed.' }
            $rustc = Tool 'rustc'
            $cargo = Tool 'cargo'
            $rustVersion = Invoke-Captured $rustc @('--version') 'rustc-version'
            $cargoVersion = Invoke-Captured $cargo @('--version') 'cargo-version'
            Require-Version $rustVersion $toolchain.rustc 'rustc'
            Require-Version $cargoVersion $toolchain.cargo 'Cargo'

            # Reuse a prepared Developer shell, otherwise initialize the pinned
            # installed MSVC/SDK. Never install or modify the system toolchain.
            if (-not (Get-Command cl -CommandType Application -ErrorAction SilentlyContinue)) {
                $vswhereCommand = Get-Command vswhere -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
                $vswhere = if ($vswhereCommand) { $vswhereCommand.Source } else {
                    Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
                }
                $vs = Invoke-Captured $vswhere @('-latest', '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath') 'vs-location'
                $devcmd = Join-Path $vs 'Common7/Tools/VsDevCmd.bat'
                if (-not [IO.File]::Exists($devcmd)) { throw 'VS C++ Build Tools Developer environment is unavailable.' }
                $setup = 'call "' + $devcmd + '" -no_logo -arch=x64 -host_arch=x64 -vcvars_ver=' + $toolchain.msvc_toolset_directory + ' -winsdk=' + $toolchain.windows_sdk + ' >nul && set'
                $devEnvironment = Invoke-Captured $env:ComSpec @('/d', '/s', '/c', $setup) 'vs-environment' -OmitOutputLog
                foreach ($line in $devEnvironment -split "`r?`n") {
                    if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process') }
                }
                $cmakeTools = Join-Path $vs 'Common7/IDE/CommonExtensions/Microsoft/CMake'
                foreach ($directory in @((Join-Path $cmakeTools 'CMake/bin'), (Join-Path $cmakeTools 'Ninja'))) {
                    if ([IO.Directory]::Exists($directory)) { $env:PATH += [IO.Path]::PathSeparator + $directory }
                }
            }
            if ($env:VCToolsVersion.TrimEnd('\') -ne $toolchain.msvc_toolset_directory -or
                $env:WindowsSDKVersion.TrimEnd('\') -ne $toolchain.windows_sdk -or $env:VSCMD_ARG_TGT_ARCH -ne 'x64') {
                throw 'Wrong MSVC toolset/Windows SDK/target architecture.'
            }
            $compilerVersion = Invoke-Captured (Tool 'cl') @() 'msvc-version' -AllowedCodes @(0, 2)
            Require-Version $compilerVersion $toolchain.msvc_compiler 'MSVC compiler'
            $cmake = Tool 'cmake'
            $ninja = Tool 'ninja'
            $cmakeVersion = Invoke-Captured $cmake @('--version') 'cmake-version'
            $ninjaVersion = Invoke-Captured $ninja @('--version') 'ninja-version'
            Require-Version $cmakeVersion $toolchain.cmake 'CMake'
            Require-Version $ninjaVersion $toolchain.ninja 'Ninja'

            $stage = 'snapshot'
            $scratch = Join-Path $runRoot 'src'
            [void][IO.Directory]::CreateDirectory($scratch)
            $expected = @{}
            foreach ($entry in $manifest.files.GetEnumerator()) { $expected[$entry.Key] = $entry.Value }
            foreach ($entry in $manifest.patches.GetEnumerator()) { $expected[$entry.Key] = $entry.Value.current_sha256 }
            foreach ($entry in $manifest.additions.GetEnumerator()) { $expected[$entry.Key] = $entry.Value }
            foreach ($name in $expected.Keys) {
                $source = Join-Path $sourceRoot $name
                Assert-NoReparsePoint $source
                $destination = Join-Path $scratch $name
                [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination))
                [IO.File]::Copy($source, $destination, $false)
                if ((Hash $destination) -ne $expected[$name]) { throw "Snapshot hash mismatch: $name" }
            }
            foreach ($name in @('bun.lock', 'Cargo.lock')) {
                if ((Hash (Join-Path $scratch $name)) -ne $toolchain.source_lock_sha256[$name]) { throw "Wrong pinned lockfile: $name" }
            }

            Set-Location -LiteralPath $scratch
            $stage = 'install'
            $null = Invoke-Captured $bun @('install', '--frozen-lockfile', '--ignore-scripts') 'install' -TimeoutSeconds 1800
            $addon = Join-Path $scratch 'packages/natives/native/pi_natives.win32-x64-baseline.node'
            $binary = Join-Path $scratch 'packages/coding-agent/binaries/omp-windows-x64.exe'
            if ([IO.File]::Exists($addon) -or [IO.File]::Exists($binary)) { throw 'Install produced an untrusted prebuilt leaf artifact.' }
            $stage = 'native'
            $null = Invoke-Captured $bun @('run', 'build:native') 'native' -TimeoutSeconds 3600
            if (-not [IO.File]::Exists($addon) -or (Get-Item -LiteralPath $addon).Length -eq 0) { throw 'Native build emitted no fresh baseline addon.' }
            $nativeHash = Hash $addon
            if ([IO.File]::Exists($binary)) { throw 'Binary output exists before binary build.' }
            $stage = 'binary'
            $null = Invoke-Captured $bun @('scripts/ci-release-build-binaries.ts', '--targets', 'win32-x64') 'binary' -TimeoutSeconds 1800
            if (-not [IO.File]::Exists($binary) -or (Get-Item -LiteralPath $binary).Length -eq 0) { throw 'Binary build emitted no fresh executable.' }
            if ((Hash $addon) -ne $nativeHash) { throw 'Native addon changed during binary build.' }
            foreach ($name in @('bun.lock', 'Cargo.lock')) {
                if ((Hash (Join-Path $scratch $name)) -ne $toolchain.source_lock_sha256[$name]) { throw "Build changed lockfile: $name" }
            }
            Set-Location -LiteralPath $Checkout
            $null = Invoke-Captured $python @('scripts/verify-vendor.py', '--root', $Checkout) 'verify-source-after'
            if ((Hash $manifestPath) -ne $manifestHash -or (Hash $toolchainPath) -ne $toolchainHash) { throw 'Build inputs changed during this run.' }

            $stage = 'staging'
            $bin = Join-Path $dataRoot 'bin'
            Assert-NoReparsePoint $bin
            [void][IO.Directory]::CreateDirectory($bin)
            $candidate = Join-Path $bin "omp.$runId.candidate.exe"
            $exeHash = Hash $binary
            [IO.File]::Copy($binary, $candidate, $false)
            if ((Hash $candidate) -ne $exeHash) { throw 'Staged candidate hash mismatch.' }
            $result = [ordered]@{
                schema_version = 1; status = 'candidate-only'; run_id = $runId
                candidate_path = $candidate; executable_sha256 = $exeHash
                size_bytes = (Get-Item -LiteralPath $candidate).Length; native_sha256 = $nativeHash
                source_commit = $manifest.upstream.commit; source_archive_sha256 = $manifest.upstream.archive_sha256
                source_manifest_sha256 = $manifestHash; toolchain_manifest_sha256 = $toolchainHash
                patch_hashes = $manifest.records; lock_hashes = $toolchain.source_lock_sha256
                platform = 'win32'; arch = 'x64'; target = $toolchain.bun_target; profile = $toolchain.profile
                isa = 'baseline'; rustflags = $toolchain.rustflags
                tools = @{ python = $pythonVersion; bun = $bunVersion; bun_revision = $bunRevision
                    rustc = $rustVersion; cargo = $cargoVersion; msvc = $toolchain.msvc_compiler
                    windows_sdk = $toolchain.windows_sdk; cmake = $toolchain.cmake; ninja = $toolchain.ninja }
                finished_utc = [DateTimeOffset]::UtcNow.ToString('o'); smoke_passed = $false; promoted = $false
            }
            [IO.File]::WriteAllText((Join-Path $runRoot 'candidate-result.json'), ($result | ConvertTo-Json -Depth 8), $utf8)
            Write-Host "Candidate only (not smoke-tested or promoted): $candidate"
            Write-Host "Build record: $(Join-Path $runRoot 'candidate-result.json')"
            $global:LASTEXITCODE = 0
        } finally {
            if ($lockStream) { $lockStream.Dispose() }
        }
    } catch {
        throw "Runtime candidate build failed at ${stage}: $($_.Exception.Message)"
    } finally {
        Set-Location -LiteralPath $callerLocation.Path
        Get-ChildItem Env: | Where-Object { -not $savedEnvironment.ContainsKey($_.Name) } |
            ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
        foreach ($key in $savedEnvironment.Keys) { Set-Item -LiteralPath ('Env:' + $key) -Value $savedEnvironment[$key] }
    }
} $Data (Split-Path -Parent $PSScriptRoot)
