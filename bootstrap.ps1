# LiumingClassroom startup helper: detect and install required runtimes.
# Supports Windows 7 SP1 / 8 / 8.1 / 10 / 11, x86 and x64.
# Compatible with Windows PowerShell 2.0 (built into Windows 7).
# This script only checks/installs dependencies; Launch.bat starts the app.

$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($env:PROCESSOR_ARCHITEW6432) { $arch = 'x64' }
elseif ($env:PROCESSOR_ARCHITECTURE -eq 'AMD64') { $arch = 'x64' }
else { $arch = 'x86' }

$os = [Environment]::OSVersion.Version
if ($os.Major -eq 6 -and $os.Minor -eq 1) { $verName = 'Windows 7' }
elseif ($os.Major -eq 6 -and $os.Minor -eq 2) { $verName = 'Windows 8' }
elseif ($os.Major -eq 6 -and $os.Minor -eq 3) { $verName = 'Windows 8.1' }
elseif ($os.Major -eq 10 -and $os.Build -ge 22000) { $verName = 'Windows 11' }
elseif ($os.Major -eq 10) { $verName = 'Windows 10' }
else { $verName = "Windows $($os.Major).$($os.Minor)" }
Write-Host "OS: $verName (Build $($os.Build)) $arch"

if ($os.Major -lt 6) {
    Write-Host 'Unsupported Windows version: requires Windows 7 SP1 or later.'
    exit 2
}
if ($os.Major -eq 6 -and $os.Minor -eq 1 -and $os.Build -lt 7601) {
    Write-Host 'Windows 7 must be Service Pack 1 (build 7601). Please install Windows 7 SP1 first.'
    exit 3
}

function Test-Dll([string]$name) {
    $paths = @(
        (Join-Path $root $name),
        (Join-Path $root "PyQt5\Qt5\bin\$name"),
        (Join-Path $env:SystemRoot "System32\$name"),
        (Join-Path $env:SystemRoot "SysWOW64\$name")
    )
    foreach ($p in $paths) { if (Test-Path $p) { return $true } }
    return $false
}

$needVc = -not ((Test-Dll 'msvcp140.dll') -or (Test-Dll 'vcruntime140.dll'))
$needDx = -not (Test-Dll 'd3dcompiler_47.dll')

if ((-not $needVc) -and (-not $needDx)) {
    Write-Host 'Dependency check passed.'
    exit 0
}

if ($needVc) {
    if ($os.Major -eq 6 -and $os.Minor -eq 1) {
        # Windows 7: use VS2019 (14.29) redist which has looser SHA-2 requirements
        $url = "https://aka.ms/vs/16/release/vc_redist.$arch.exe"
    } else {
        $url = "https://aka.ms/vs/17/release/vc_redist.$arch.exe"
    }
    $local = Join-Path $root "vc_redist.$arch.exe"
    $out = Join-Path $env:TEMP "vc_redist.$arch.exe"
    if (Test-Path $local) {
        Write-Host 'Installing VC++ runtime from local file...'
        Start-Process -FilePath $local -ArgumentList '/install','/quiet','/norestart' -Verb RunAs -Wait
    } else {
        Write-Host "Downloading VC++ runtime: $url"
        try {
            (New-Object System.Net.WebClient).DownloadFile($url, $out)
            Write-Host 'Installing VC++ runtime (UAC may prompt)...'
            Start-Process -FilePath $out -ArgumentList '/install','/quiet','/norestart' -Verb RunAs -Wait
        } catch {
            Write-Host "Auto install failed. Please install manually: $url"
        }
    }
}

# Windows 7: ensure Universal CRT (KB2999226); without it Python/Qt cannot start
if ($os.Major -eq 6 -and $os.Minor -eq 1) {
    if (-not (Test-Dll 'ucrtbase.dll')) {
        if ($arch -eq 'x86') {
            $u = 'https://download.microsoft.com/download/9/3/F/93FCF1E7-E6A4-478B-96E7-D4B285925B00/Windows6.1-KB2999226-x86.msu'
        } else {
            $u = 'https://download.microsoft.com/download/9/3/F/93FCF1E7-E6A4-478B-96E7-D4B285925B00/Windows6.1-KB2999226-x64.msu'
        }
        $outU = Join-Path $env:TEMP 'Windows6.1-KB2999226.msu'
        Write-Host "Downloading UCRT update for Windows 7: $u"
        try {
            (New-Object System.Net.WebClient).DownloadFile($u, $outU)
            Write-Host 'Installing UCRT (KB2999226); a reboot may be required...'
            Start-Process -FilePath 'wusa.exe' -ArgumentList $outU,'/quiet','/norestart' -Verb RunAs -Wait
        } catch {
            Write-Host "UCRT auto install failed. Please install KB2999226 manually: $u"
        }
    }
}

if ($needDx) {
    $dx = 'https://download.microsoft.com/download/1/7/1/1718CCC4-6315-4D8E-9543-8E28A4E18C4C/dxwebsetup.exe'
    $outDx = Join-Path $env:TEMP 'dxwebsetup.exe'
    Write-Host 'Downloading DirectX runtime (optional)...'
    try {
        (New-Object System.Net.WebClient).DownloadFile($dx, $outDx)
        Start-Process -FilePath $outDx -ArgumentList '/Q' -Verb RunAs -Wait
    } catch {
        Write-Host "DirectX auto install failed (optional): $dx"
    }
}

Write-Host 'Dependency handling finished.'
exit 0
