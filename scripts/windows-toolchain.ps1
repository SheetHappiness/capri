function Initialize-CapriWindowsToolchain {
    if (-not $IsWindows -or [Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -ne 'X64') {
        throw 'Required: Windows x64 and PowerShell 7 x64.'
    }
    $PSNativeCommandUseErrorActionPreference = $false
    if (-not (Get-Command cl -CommandType Application -ErrorAction SilentlyContinue)) {
        $command = Get-Command vswhere -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        $vswhere = if ($command) { $command.Source } else {
            Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
        }
        if (-not [IO.File]::Exists($vswhere)) { throw 'Missing prerequisite: Visual Studio 2022 C++ Build Tools x64 and Windows SDK.' }
        $vs = & $vswhere -latest -version '[17.0,18.0)' -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($LASTEXITCODE -ne 0 -or -not $vs) { throw 'Missing prerequisite: Visual Studio 2022 C++ Build Tools x64.' }
        $devcmd = Join-Path ($vs | Select-Object -First 1) 'Common7/Tools/VsDevCmd.bat'
        if (-not [IO.File]::Exists($devcmd)) { throw 'Missing VS 2022 C++ Developer environment.' }
        $info = [Diagnostics.ProcessStartInfo]::new($env:ComSpec)
        $info.Arguments = '/d /s /c "call "' + $devcmd + '" -no_logo -arch=x64 -host_arch=x64 >nul && set"'
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $info
        try {
            [void]$process.Start()
            $stdout = $process.StandardOutput.ReadToEndAsync()
            $stderr = $process.StandardError.ReadToEndAsync()
            if (-not $process.WaitForExit(60000)) { $process.Kill($true); $process.WaitForExit(); throw 'VS environment setup timed out.' }
            if ($process.ExitCode -ne 0) { throw 'Cannot initialize VS 2022 C++ Build Tools x64 / Windows SDK.' }
            # The full environment may contain secrets: never log it.
            foreach ($line in $stdout.GetAwaiter().GetResult() -split "`r?`n") {
                if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process') }
            }
            $null = $stderr.GetAwaiter().GetResult()
        } finally { $process.Dispose() }
    }
    if ($env:VSCMD_VER -notmatch '^17\.' -or $env:VSCMD_ARG_TGT_ARCH -ne 'x64' -or -not $env:VCToolsVersion) {
        throw 'Required: Visual Studio 2022 C++ Build Tools targeting x64.'
    }
    foreach ($name in @('cl', 'link')) {
        if (-not (Get-Command $name -CommandType Application -ErrorAction SilentlyContinue)) { throw "Missing VS C++ tool: $name" }
    }
    if (-not $env:WindowsSDKVersion) { throw 'Missing prerequisite: compatible Windows SDK.' }
    $sdk = $env:WindowsSDKVersion.TrimEnd('\')
    if (-not $sdk -or -not $env:WindowsSdkDir) { throw 'Missing prerequisite: compatible Windows SDK.' }
    foreach ($relative in @("Include/$sdk/um/Windows.h", "Include/$sdk/ucrt/corecrt.h", "Lib/$sdk/um/x64/kernel32.lib", "Lib/$sdk/ucrt/x64/ucrt.lib", "bin/$sdk/x64/rc.exe")) {
        if (-not [IO.File]::Exists((Join-Path $env:WindowsSdkDir $relative))) {
            throw "Missing Windows SDK component: $relative. Install compatible Windows SDK and rerun ./scripts/bootstrap.ps1."
        }
    }
    $env:VSLANG = '1033'
    $compiler = & cl 2>&1 | Out-String
    if ($LASTEXITCODE -notin @(0, 2) -or $compiler -notmatch 'Version (\d+\.\d+\.\d+).*x64') { throw 'Cannot run the MSVC x64 compiler.' }
    return @{ msvc = $Matches[1]; msvc_toolset_directory = $env:VCToolsVersion.TrimEnd('\'); windows_sdk = $sdk }
}
