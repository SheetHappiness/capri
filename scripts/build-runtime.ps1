#Requires -Version 7.0
[CmdletBinding()]
param([string]$Data, [ValidateRange(1, 600)][int]$SmokeTimeoutSeconds = 180)

# A child scriptblock keeps helper functions/preferences local even when callers
# dot-source this entry point. No exit: callers retain their own process.
& {
    param([string]$RequestedData, [string]$Checkout, [int]$SmokeTimeout)
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
            if (-not [IO.File]::Exists($python)) { throw 'Missing checkout .venv; run ./scripts/bootstrap.ps1 first.' }

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

            . (Join-Path $PSScriptRoot 'windows-toolchain.ps1')
            $systemTools = Initialize-CapriWindowsToolchain
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
                    rustc = $rustVersion; cargo = $cargoVersion; msvc = $systemTools.msvc; msvc_toolset_directory = $systemTools.msvc_toolset_directory
                    windows_sdk = $systemTools.windows_sdk; cmake = $toolchain.cmake; ninja = $toolchain.ninja }
                finished_utc = [DateTimeOffset]::UtcNow.ToString('o'); smoke_passed = $false; promoted = $false
            }
            [IO.File]::WriteAllText((Join-Path $runRoot 'candidate-result.json'), ($result | ConvertTo-Json -Depth 8), $utf8)
            $stage = 'smoke'
            $smokeRoot = Join-Path $dataRoot "s/$($runId.Substring(0, 4))"
            $null = Invoke-Captured $python @('scripts/smoke-runtime.py', '--omp', $candidate, '--data', $smokeRoot) 'smoke' -TimeoutSeconds $SmokeTimeout
            $smoke = Get-Content -LiteralPath (Join-Path $smokeRoot 'smoke-result.json') -Raw | ConvertFrom-Json -AsHashtable
            foreach ($check in @('passed', 'cli', 'worker', 'config', 'rpc', 'native_extraction', 'teardown')) {
                if ($smoke[$check] -isnot [bool] -or $smoke[$check] -ne $true) { throw "Smoke did not confirm $check." }
            }
            if ($smoke.executable_sha256 -ne $exeHash -or $smoke.native_sha256 -ne $nativeHash -or (Hash $candidate) -ne $exeHash) {
                throw 'Smoke/candidate/native hash mismatch; previous runtime preserved.'
            }
            $stage = 'publication'
            $final = Join-Path $bin 'omp.exe'
            Assert-NoReparsePoint $final
            try {
                # Same-volume Windows rename/replace. Never delete final first.
                [IO.File]::Move($candidate, $final, $true)
            } catch { throw "Cannot replace $final (it may be in use). Stop the bot manually and rerun. $($_.Exception.Message)" }
            $result.status = 'published'
            $result.executable_path = $final
            $result.smoke_passed = $true
            $result.promoted = $true
            $result.smoke_result = Join-Path $smokeRoot 'smoke-result.json'
            $result.finished_utc = [DateTimeOffset]::UtcNow.ToString('o')
            [IO.File]::WriteAllText((Join-Path $runRoot 'candidate-result.json'), ($result | ConvertTo-Json -Depth 8), $utf8)
            Write-Host "Built, smoke-tested and published: $final"
            Write-Host "Build record: $(Join-Path $runRoot 'candidate-result.json')"
            $global:LASTEXITCODE = 0
        } finally {
            if ($lockStream) { $lockStream.Dispose() }
        }
    } catch {
        throw "Runtime build failed at ${stage}: $($_.Exception.Message)"
    } finally {
        Set-Location -LiteralPath $callerLocation.Path
        Get-ChildItem Env: | Where-Object { -not $savedEnvironment.ContainsKey($_.Name) } |
            ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
        foreach ($key in $savedEnvironment.Keys) { Set-Item -LiteralPath ('Env:' + $key) -Value $savedEnvironment[$key] }
    }
} $Data (Split-Path -Parent $PSScriptRoot) $SmokeTimeoutSeconds
