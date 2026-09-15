$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Virtual env missing. Running one-click setup..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "setup.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Setup finished but .venv is still missing. Run scripts\setup.cmd in a new terminal."
    exit 1
}
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

function Get-AppPort {
    $port = 8765
    $envFile = Join-Path $root ".env"
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile) {
            if ($line -match '^\s*APP_PORT\s*=\s*(\d+)') {
                $port = [int]$Matches[1]
            }
        }
    }
    return $port
}

function Stop-ProcessTree([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
}

function Get-ListenPids([int]$Port) {
    $ids = New-Object System.Collections.Generic.List[int]
    $pattern = ":$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    foreach ($line in (& netstat.exe -ano -p tcp)) {
        if ($line -match $pattern) {
            $id = [int]$Matches[1]
            if ($id -gt 0 -and -not $ids.Contains($id)) {
                $ids.Add($id)
            }
        }
    }
    return $ids
}

function Test-OurServerProcess([int]$ProcessId) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $p) { return $false }
    $cmd = [string]$p.CommandLine
    if ($cmd -notmatch 'src\.main') { return $false }
    $venvPy = Join-Path $root ".venv\Scripts\python.exe"
    $exe = [string]$p.ExecutablePath
    if ($exe -and (Test-Path -LiteralPath $venvPy)) {
        $want = [IO.Path]::GetFullPath($venvPy)
        if ($exe.Equals($want, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return ($cmd -like "*$root*")
}

function Get-OurServerPids {
    $found = New-Object System.Collections.Generic.List[int]
    $venvPy = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPy)) { return $found }
    $want = [IO.Path]::GetFullPath($venvPy)
    $procs = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue)
    foreach ($p in $procs) {
        if (-not $p) { continue }
        $cmd = [string]$p.CommandLine
        $exe = [string]$p.ExecutablePath
        if ($cmd -notmatch 'src\.main') { continue }
        if (-not $exe -or -not $exe.Equals($want, [StringComparison]::OrdinalIgnoreCase)) { continue }
        if (-not $found.Contains([int]$p.ProcessId)) {
            $found.Add([int]$p.ProcessId)
        }
    }
    return $found
}

function Stop-LeftoverServer {
    $port = Get-AppPort
    $ids = New-Object System.Collections.Generic.List[int]
    foreach ($processId in Get-OurServerPids) {
        if (-not $ids.Contains($processId)) { $ids.Add($processId) }
    }
    foreach ($processId in Get-ListenPids $port) {
        if ((Test-OurServerProcess $processId) -and -not $ids.Contains($processId)) {
            $ids.Add($processId)
        }
    }
    foreach ($processId in $ids) {
        Write-Host "Stopping leftover server PID $processId ..."
        Stop-ProcessTree $processId
    }
}

Stop-LeftoverServer

$py = Join-Path $root ".venv\Scripts\python.exe"
$proc = $null
$code = 0
try {
    $proc = Start-Process -FilePath $py -ArgumentList "-m src.main" -WorkingDirectory $root -NoNewWindow -PassThru
    Write-Host "Server PID $($proc.Id). Press Ctrl+C to stop."
    # Sleep-loop so Ctrl+C is interruptible (WaitForExit is not in Windows PowerShell 5.1).
    while ($proc -and -not $proc.HasExited) {
        Start-Sleep -Milliseconds 300
        $proc.Refresh()
    }
    if ($proc -and $null -ne $proc.ExitCode) {
        $code = $proc.ExitCode
    }
} finally {
    if ($proc) {
        try { $proc.Refresh() } catch { }
        if (-not $proc.HasExited) {
            Write-Host "Stopping server PID $($proc.Id) ..."
            Stop-ProcessTree $proc.Id
        }
    }
}
exit $code
