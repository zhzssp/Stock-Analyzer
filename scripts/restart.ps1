# 一键重启：结束本软件后台服务，再拉起 run-server（跳过环境检查）。
$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    $OutputEncoding = [Text.Encoding]::UTF8
} catch { }
try { $Host.UI.RawUI.WindowTitle = "Stock-Analyzer 重启" } catch { }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$serverPs1 = Join-Path $PSScriptRoot "run-server.ps1"
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$pidFile = Join-Path $root "data\run\server.pid"

function Write-Info([string]$Text) { Write-Host "    $Text" }
function Write-Ok([string]$Text) { Write-Host "    [完成] $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "    [注意] $Text" -ForegroundColor Yellow }
function Write-Fail([string]$Text) {
    Write-Host ""
    Write-Host "[失败] $Text" -ForegroundColor Red
}

function Stop-ProcessTree([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
    $ErrorActionPreference = $prev
}

function Test-OurServerProcess([int]$ProcessId) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $p) { return $false }
    $cmd = [string]$p.CommandLine
    if ($cmd -notmatch 'src\.main') { return $false }
    if (Test-Path -LiteralPath $venvPy) {
        $want = [IO.Path]::GetFullPath($venvPy)
        $exe = [string]$p.ExecutablePath
        if ($exe -and $exe.Equals($want, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return ($cmd -like "*$root*")
}

function Get-OurServerPids {
    $found = New-Object System.Collections.Generic.List[int]
    if (-not (Test-Path -LiteralPath $venvPy)) { return $found }
    $want = [IO.Path]::GetFullPath($venvPy)
    $procs = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue)
    foreach ($p in $procs) {
        if (-not $p) { continue }
        $cmd = [string]$p.CommandLine
        $exe = [string]$p.ExecutablePath
        if ($cmd -notmatch 'src\.main') { continue }
        if (-not $exe -or -not $exe.Equals($want, [StringComparison]::OrdinalIgnoreCase)) { continue }
        if (-not $found.Contains([int]$p.ProcessId)) { $found.Add([int]$p.ProcessId) }
    }
    return $found
}

function Get-DotEnv([string]$Name, [string]$Default) {
    $envFile = Join-Path $root ".env"
    if (-not (Test-Path -LiteralPath $envFile)) { return $Default }
    foreach ($line in Get-Content -LiteralPath $envFile -ErrorAction SilentlyContinue) {
        if ($line -match ("^\s*" + [regex]::Escape($Name) + "\s*=\s*(.*?)\s*$")) {
            $val = $Matches[1].Trim()
            if ($val.StartsWith('"') -and $val.EndsWith('"') -and $val.Length -ge 2) {
                $val = $val.Substring(1, $val.Length - 2)
            }
            if ($val) { return $val }
        }
    }
    return $Default
}

function Get-ListenPids([int]$Port) {
    $ids = New-Object System.Collections.Generic.List[int]
    $pattern = ":$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $lines = @(& netstat.exe -ano -p tcp 2>$null)
    $ErrorActionPreference = $prev
    foreach ($line in $lines) {
        if ($line -match $pattern) {
            $id = [int]$Matches[1]
            if ($id -gt 0 -and -not $ids.Contains($id)) { $ids.Add($id) }
        }
    }
    return $ids
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Stock-Analyzer 一键重启" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "会先结束本软件后台服务，再重新启动（不重复跑环境检查）。"
Write-Host "若还有一个旧的黑色窗口在等按键，可以关掉它。"
Write-Host ""

if (-not (Test-Path -LiteralPath $serverPs1)) {
    Write-Fail "找不到 scripts\run-server.ps1"
    exit 1
}

$port = 8765
$portText = Get-DotEnv "APP_PORT" "8765"
if ($portText -match '^\d+$') { $port = [int]$portText }

$ids = New-Object System.Collections.Generic.List[int]
if (Test-Path -LiteralPath $pidFile) {
    $oldPidText = (Get-Content -LiteralPath $pidFile -TotalCount 1 -ErrorAction SilentlyContinue | ForEach-Object { "$_".Trim() })
    if ($oldPidText -match '^\d+$') {
        $oldPid = [int]$oldPidText
        if (Test-OurServerProcess $oldPid) { $ids.Add($oldPid) }
    }
    try { Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue } catch { }
}
foreach ($processId in Get-OurServerPids) {
    if (-not $ids.Contains($processId)) { $ids.Add($processId) }
}
foreach ($processId in @(Get-ListenPids $port)) {
    if (Test-OurServerProcess $processId -and -not $ids.Contains($processId)) {
        $ids.Add($processId)
    }
}

if ($ids.Count -eq 0) {
    Write-Warn "没有发现正在运行的本软件服务，将直接启动。"
} else {
    foreach ($processId in $ids) {
        Write-Info "正在结束服务 PID $processId ..."
        Stop-ProcessTree $processId
    }
    Start-Sleep -Milliseconds 800
    Write-Ok "旧服务已结束"
}

$env:STOCK_ANALYZER_SKIP_SETUP = "1"
$env:STOCK_ANALYZER_FROM_RUN = "1"
if (-not $env:STOCK_ANALYZER_KEEP_WINDOW) { $env:STOCK_ANALYZER_KEEP_WINDOW = "1" }

Write-Host ""
Write-Info "正在重新启动服务 ..."
Write-Host ""
& $serverPs1
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 0 }
exit $code
