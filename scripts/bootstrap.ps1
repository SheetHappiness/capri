#Requires -Version 7.0
[CmdletBinding()]
param([string]$Data)

& {
    param($RequestedData, $Checkout)
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $false
    $callerLocation = Get-Location
    $saved = @{}
    Get-ChildItem Env: | ForEach-Object { $saved[$_.Name] = $_.Value }
    $stage = 'system preflight'
    $log = $null
    function Invoke-BootstrapCommand([string]$File, [string[]]$Arguments) {
        & $File @Arguments >> $log 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Command failed; see $log" }
    }
    try {
        if (-not $IsWindows -or [Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -ne 'X64') {
            throw 'Required: Windows x64 and PowerShell 7 x64.'
        }
        $dataRoot = if ($RequestedData) { [IO.Path]::GetFullPath($RequestedData, $callerLocation.Path) } else { Join-Path $Checkout '.runtime' }
        $vendor = Join-Path $Checkout 'vendor'
        if ($dataRoot.TrimEnd('\', '/') -ieq $vendor -or $dataRoot.StartsWith($vendor + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Data must be outside vendor.'
        }
        # Reject redirected data roots before installing tools or writing logs.
        for ($path = $dataRoot; $path; $path = [IO.Path]::GetDirectoryName($path)) {
            if ((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw "Data cannot contain a reparse point: $path"
            }
        }
        if (-not (Get-Command git -CommandType Application -ErrorAction SilentlyContinue)) { throw 'Missing prerequisite: Git.' }
        . (Join-Path $PSScriptRoot 'windows-toolchain.ps1')
        $null = Initialize-CapriWindowsToolchain
        $python = (Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
        if (-not $python) { throw 'Missing prerequisite: Python 3.14 x64 on PATH.' }
        $probe = 'import sys,struct; assert sys.version_info[:2]==(3,14) and struct.calcsize("P")==8, "Required: Python 3.14 x64"'
        & $python -c $probe
        if ($LASTEXITCODE -ne 0) { throw 'Required: Python 3.14 x64.' }
        [void][IO.Directory]::CreateDirectory((Join-Path $dataRoot 'bootstrap'))
        $log = Join-Path $dataRoot "bootstrap/$([Guid]::NewGuid().ToString('N')).log"
        Set-Location -LiteralPath $Checkout
        $stage = 'Python environment'
        $venv = Join-Path $Checkout '.venv'
        $venvPython = Join-Path $venv 'Scripts/python.exe'
        if (Test-Path -LiteralPath $venv) {
            if (-not [IO.File]::Exists($venvPython)) { throw 'Existing .venv is incomplete; move it aside and rerun bootstrap.' }
            Invoke-BootstrapCommand $venvPython @('-c', $probe)
        } else { Invoke-BootstrapCommand $python @('-m', 'venv', $venv) }
        $stage = 'Python dependencies and vendored SDK'
        Invoke-BootstrapCommand $venvPython @('-m', 'pip', 'install', '-r', 'requirements-test.txt')
        $sdkProbe = 'import importlib.metadata as m,json,sys; from pathlib import Path; o=json.loads(m.distribution("omp-rpc").read_text("direct_url.json")); assert o["url"]==Path(sys.argv[1]).resolve().as_uri() and "dir_info" in o, "SDK must come from vendor/omp"'
        Invoke-BootstrapCommand $venvPython @('-c', $sdkProbe, (Join-Path $Checkout 'vendor/omp/sdk/python/omp-rpc'))
        Invoke-BootstrapCommand $venvPython @('scripts/verify-vendor.py', '--root', $Checkout)
        $stage = 'private pinned tools'
        $toolchain = Get-Content -LiteralPath (Join-Path $Checkout 'runtime-toolchain.json') -Raw | ConvertFrom-Json -AsHashtable
        . (Join-Path $PSScriptRoot 'bootstrap-tools.ps1')
        $tools = Initialize-CapriTools -Data $dataRoot -Toolchain $toolchain
        $env:PATH = (@([IO.Path]::GetDirectoryName($tools.Bun), [IO.Path]::GetDirectoryName($tools.Cargo),
            [IO.Path]::GetDirectoryName($tools.CMake), [IO.Path]::GetDirectoryName($tools.Ninja), $env:PATH) -join [IO.Path]::PathSeparator)
        $env:RUSTUP_HOME = $tools.RustupHome
        $env:CARGO_HOME = $tools.CargoHome
        $stage = 'vendored runtime build / smoke / publication'
        & (Join-Path $PSScriptRoot 'build-runtime.ps1') -Data $dataRoot
        if ($LASTEXITCODE -ne 0 -or -not [IO.File]::Exists((Join-Path $dataRoot 'bin/omp.exe'))) { throw 'Runtime build did not publish omp.exe.' }
        Write-Host "Bootstrap passed: $(Join-Path $dataRoot 'bin/omp.exe')"
        Write-Host "Next: place bot-token in $dataRoot, perform private OMP login, then run .venv/Scripts/python -m capri.cli --data `"$dataRoot`"."
        Write-Host "Bootstrap log: $log"
        $global:LASTEXITCODE = 0
    } catch {
        throw "Bootstrap failed at ${stage}: $($_.Exception.Message). Install missing prerequisites and rerun ./scripts/bootstrap.ps1. Log: $log"
    } finally {
        Set-Location -LiteralPath $callerLocation.Path
        Get-ChildItem Env: | Where-Object { -not $saved.ContainsKey($_.Name) } | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
        foreach ($key in $saved.Keys) { [Environment]::SetEnvironmentVariable($key, $saved[$key], 'Process') }
    }
} $Data (Split-Path -Parent $PSScriptRoot)
