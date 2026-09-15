<#
.SYNOPSIS
    S0：实测「指数 → 成份股」接口，禁止用交易所全市场冒充指数。

.DESCRIPTION
    演示 licence 会忽略代码，成份结果一律记为无法验证、芯片保持未启用。
    正式 licence 下会尝试若干候选路径，并确认 hscp/sszs 只是个股反查。
    全市场扫一遍 sszs 拼成份默认不做（约 5000 次请求）。

.PARAMETER Licence
    麦蕊授权码。缺省用公开演示 licence。

.PARAMETER OutFile
    报告路径，默认 docs/指数成份探针.md
#>

[CmdletBinding()]
param(
    [string] $Licence = "LICENCE-66D8-9F96-0C7F0FBCD073",
    [string] $OutFile
)

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OutFile)) {
    $OutFile = Join-Path $RepoRoot 'docs\指数成份探针.md'
}

$DemoLicence = "LICENCE-66D8-9F96-0C7F0FBCD073"
$BaseApi = "https://api.mairuiapi.com"
$IsDemo = ($Licence -eq $DemoLicence)
$env:MAIRUI_LICENCE = $Licence
$env:MAIRUI_OFFLINE = "0"

$Py = Join-Path $RepoRoot '.venv\Scripts\python.exe'
Write-Host ""
Write-Host "指数成份探针" -ForegroundColor Cyan
Write-Host "licence : $Licence"
Write-Host "演示码  : $IsDemo"
Write-Host "开始时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "请保持网络畅通，不要关闭窗口。全部完成后会写入报告。"

Write-Host ""
Write-Host ">>> [1/3] 检查 Python" -ForegroundColor Cyan
if (-not (Test-Path $Py)) {
    Write-Host "未找到 .venv\Scripts\python.exe，改用系统 python。建议先运行 scripts\setup.cmd" -ForegroundColor Yellow
    $Py = 'python'
} else {
    Write-Host "    使用 $Py" -ForegroundColor Green
}

Write-Host ""
Write-Host ">>> [2/3] 探测指数成份接口（可能要一两分钟）" -ForegroundColor Cyan
Set-Location $RepoRoot
& $Py -m src.market.index_probe
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host "    探测进程退出码 $code（报告仍会尽量写出）" -ForegroundColor Yellow
} else {
    Write-Host "    探测结束" -ForegroundColor Green
}

$probeJson = Join-Path $RepoRoot 'data\index_probe.json'
$summary = "(尚未生成 data/index_probe.json)"
if (Test-Path $probeJson) {
    $summary = Get-Content $probeJson -Raw -Encoding UTF8
}

$lines = @(
    '# 指数成份探针',
    '',
    "> 由 ``scripts/Verify-Index.ps1`` 生成。未证实的指数芯片必须保持「未启用」。",
    ">",
    "> 执行时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')　｜　licence：``$Licence``　｜　演示 licence：$IsDemo",
    '',
    '## 口径',
    '',
    '- 上证指数 / 深证成指 / 北证50 等是**成份股**，不是沪市/深市/北交所全部挂牌。',
    '- 个股反查 ``hscp/sszs/{code}`` 不能代替「给定指数 → 成份列表」。',
    '- 全市场反扫 sszs 默认不做。',
    '- 演示 licence 不得把样本写成指数实盘。',
    '',
    '## 机器可读结果',
    '',
    '```json',
    $summary,
    '```',
    '',
    '## 下一步',
    '',
    '- 若 ``constituent_api`` 有值且 ``enabled=true``：工作台 S6 芯片自动打开。',
    '- 若仍全部 ``enabled=false``：行情页继续只提供沪市/深市/北交所/创业板/科创**全部**，指数名显示未启用。'
)
Write-Host ""
Write-Host ">>> [3/3] 写入报告" -ForegroundColor Cyan
$lines | Set-Content -Path $OutFile -Encoding UTF8
Write-Host "    报告已写入: $OutFile" -ForegroundColor Green
Write-Host "结束时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
exit $code
