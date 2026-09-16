# Daily launcher: verify/repair environment, then start the server.
$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    $OutputEncoding = [Text.Encoding]::UTF8
} catch { }
try { $Host.UI.RawUI.WindowTitle = "Stock-Analyzer" } catch { }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$setupPs1 = Join-Path $PSScriptRoot "setup.ps1"
$serverPs1 = Join-Path $PSScriptRoot "run-server.ps1"

function Write-Fail([string]$Text) {
    Write-Host ""
    Write-Host "[失败] $Text" -ForegroundColor Red
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Stock-Analyzer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "请不要关闭本窗口。关掉它，网页就会打不开。"
Write-Host "工作目录: $root"
Write-Host "开始时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "将先检查环境（已配置过就只校验），然后启动服务。"
Write-Host ""

if (-not (Test-Path -LiteralPath $setupPs1)) {
    Write-Fail "找不到 scripts\setup.ps1，软件文件不完整。"
    exit 1
}
if (-not (Test-Path -LiteralPath $serverPs1)) {
    Write-Fail "找不到 scripts\run-server.ps1，软件文件不完整。"
    exit 1
}

$env:STOCK_ANALYZER_FROM_RUN = "1"
$env:STOCK_ANALYZER_NESTED_SETUP = "1"
Write-Host ">>> [1/2] 环境检查 / 配置" -ForegroundColor Cyan
Write-Host "    正在调用 $setupPs1"
Write-Host ""
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setupPs1
$setupCode = $LASTEXITCODE
$ErrorActionPreference = $prev
if ($null -eq $setupCode) { $setupCode = 1 }
if ($setupCode -ne 0) {
    Write-Fail "环境检查/配置没有成功（退出码 $setupCode），服务不会启动。"
    Write-Host "请向上滚动阅读中文说明。也可以单独再双击 scripts\setup.cmd。"
    exit $setupCode
}

$env:STOCK_ANALYZER_SKIP_SETUP = "1"
Write-Host ""
Write-Host ">>> [2/2] 启动服务" -ForegroundColor Cyan
Write-Host "    正在调用 $serverPs1"
Write-Host ""
$ErrorActionPreference = "Continue"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $serverPs1
$serverCode = $LASTEXITCODE
$ErrorActionPreference = $prev
if ($null -eq $serverCode) { $serverCode = 1 }
exit $serverCode
