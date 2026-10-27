#Requires -Version 7.0
# Opt-in integration check after tool installation; no downloads or installs.
param([Parameter(Mandatory)][string]$Data)
& {
    param($DataRoot, $Checkout)
    $ErrorActionPreference = 'Stop'
    $saved = @{}
    Get-ChildItem Env: | ForEach-Object { $saved[$_.Name] = $_.Value }
    try {
        . (Join-Path $Checkout 'scripts/bootstrap-tools.ps1')
        $toolchain = Get-Content (Join-Path $Checkout 'runtime-toolchain.json') -Raw | ConvertFrom-Json -AsHashtable
        foreach ($name in @('bun', 'cmake', 'ninja', 'rust')) {
            if (-not (Test-Path -LiteralPath (Join-Path $DataRoot "tools/$name"))) { throw "Install private $name before this check." }
        }
        $tools = Initialize-CapriTools -Data $DataRoot -Toolchain $toolchain
        foreach ($key in $saved.Keys) {
            if ([Environment]::GetEnvironmentVariable($key) -ne $saved[$key]) { throw "Helper leaked environment: $key" }
        }
        if (@(Get-ChildItem Env:).Count -ne $saved.Count) { throw 'Helper added environment keys.' }
        $env:RUSTUP_HOME = $tools.RustupHome
        $env:RUSTUP_TOOLCHAIN = $toolchain.rust_toolchain
        $env:CARGO_HOME = Join-Path $DataRoot 'cache/cargo'
        Assert-CapriTool $tools.Rustc $toolchain.rustc
        Assert-CapriTool $tools.Cargo $toolchain.cargo
        $source = Join-Path $DataRoot 'proxy-test.rs'
        [IO.File]::WriteAllText($source, 'pub fn capri_proxy_test() -> u8 { 1 }')
        & $tools.Rustc --crate-type=lib --emit=metadata --crate-name capri_proxy_test $source -o (Join-Path $DataRoot 'proxy-test.rmeta')
        if ($LASTEXITCODE -ne 0) { throw 'Private Rust proxy failed with build CARGO_HOME.' }
        Write-Host 'PASS: private Rust compiler/Cargo with build CARGO_HOME; helper environment restored.'
    } finally {
        Get-ChildItem Env: | Where-Object { -not $saved.ContainsKey($_.Name) } | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
        foreach ($key in $saved.Keys) { [Environment]::SetEnvironmentVariable($key, $saved[$key], 'Process') }
    }
} ([IO.Path]::GetFullPath($Data)) (Split-Path -Parent $PSScriptRoot)
