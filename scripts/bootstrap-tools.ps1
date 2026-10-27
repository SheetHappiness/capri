# Private tools only. Dot-sourcing defines helpers; it performs no installation.
function Assert-CapriTool([string]$Executable, [string]$Expected, [string]$Argument = '--version') {
    if (-not [IO.File]::Exists($Executable)) { throw "Missing private tool: $Executable" }
    $output = & $Executable $Argument 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -or $output -notmatch ('(?<![\w.])' + [regex]::Escape($Expected) + '(?![\w.])')) {
        throw "Wrong private tool version (expected $Expected): $Executable"
    }
}

function Get-CapriDownload([hashtable]$Record, [string]$Destination) {
    if ($Record.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or $Record.url -notmatch '^https://') {
        throw 'Tool downloads require an HTTPS URL and a pinned SHA-256.'
    }
    # Never resume an incomplete transfer. Invoke-WebRequest replaces this file.
    Invoke-WebRequest -Uri $Record.url -OutFile $Destination
    if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -ine $Record.sha256) {
        throw "SHA-256 mismatch for tool download: $Destination"
    }
}

function Install-CapriArchive([string]$Name, [hashtable]$Record, [string]$ToolsRoot) {
    $final = Join-Path $ToolsRoot $Name
    $executable = Join-Path $final $Record.executable
    if ([IO.Directory]::Exists($final)) {
        Assert-CapriTool $executable $Record.version
        if ($Record.revision) { Assert-CapriTool $executable $Record.revision '--revision' }
        return $executable
    }
    [void][IO.Directory]::CreateDirectory($ToolsRoot)
    $download = Join-Path $ToolsRoot "$Name.download.tmp"
    $staging = Join-Path $ToolsRoot "$Name.$([Guid]::NewGuid().ToString('N')).tmp"
    Get-CapriDownload $Record $download
    # ZipFile accepts a .tmp extension; Expand-Archive requires .zip.
    [IO.Compression.ZipFile]::ExtractToDirectory($download, $staging)
    $candidate = Join-Path $staging $Record.executable
    Assert-CapriTool $candidate $Record.version
    if ($Record.revision) { Assert-CapriTool $candidate $Record.revision '--revision' }
    [IO.Directory]::Move($staging, $final)
    [IO.File]::Delete($download)
    return $executable
}

function Initialize-CapriTools([string]$Data, [hashtable]$Toolchain) {
    $tools = Join-Path $Data 'tools'
    $saved = @{}
    foreach ($key in @('RUSTUP_HOME', 'CARGO_HOME', 'RUSTUP_TOOLCHAIN', 'RUSTUP_AUTO_INSTALL')) {
        $saved[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
    }
    try {
        $result = @{}
        foreach ($name in @('bun', 'cmake', 'ninja')) {
            $result[$name] = Install-CapriArchive $name $Toolchain.downloads[$name] $tools
        }
        $rust = Join-Path $tools 'rust'
        $fresh = -not [IO.Directory]::Exists($rust)
        $working = if ($fresh) { Join-Path $tools "rust.$([Guid]::NewGuid().ToString('N')).tmp" } else { $rust }
        $env:RUSTUP_HOME = Join-Path $working 'rustup'
        $env:CARGO_HOME = Join-Path $working 'cargo'
        $env:RUSTUP_TOOLCHAIN = $Toolchain.rust_toolchain
        $env:RUSTUP_AUTO_INSTALL = '0'
        if ($fresh) {
            $download = Join-Path $tools 'rustup.download.tmp'
            Get-CapriDownload $Toolchain.downloads.rustup $download
            [void][IO.Directory]::CreateDirectory($working)
            $installer = Join-Path $working 'rustup-init.exe'
            [IO.File]::Move($download, $installer)
            & $installer -y --no-modify-path --profile minimal --default-host x86_64-pc-windows-msvc --default-toolchain $Toolchain.rust_toolchain
            if ($LASTEXITCODE -ne 0) { throw 'Private Rust toolchain installation failed.' }
        }
        foreach ($name in @('rustc', 'cargo')) {
            Assert-CapriTool (Join-Path $working "cargo/bin/$name.exe") $Toolchain[$name]
        }
        Assert-CapriTool (Join-Path $working 'cargo/bin/rustup.exe') $Toolchain.downloads.rustup.version
        if ($fresh) { [IO.Directory]::Move($working, $rust) }
        foreach ($name in @('Rustup', 'Rustc', 'Cargo')) { $result[$name] = Join-Path $rust "cargo/bin/$($name.ToLowerInvariant()).exe" }
        $result.RustupHome = Join-Path $rust 'rustup'
        $result.CargoHome = Join-Path $rust 'cargo'
        return $result
    } finally {
        foreach ($key in $saved.Keys) {
            if ($null -eq $saved[$key]) { Remove-Item -LiteralPath ('Env:' + $key) -ErrorAction SilentlyContinue }
            else { [Environment]::SetEnvironmentVariable($key, $saved[$key], 'Process') }
        }
    }
}
