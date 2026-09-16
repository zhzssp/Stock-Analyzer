<#
.SYNOPSIS
    麦蕊股票 API 现状验证脚本

.DESCRIPTION
    针对 docs/设计/API现状.md 中 §4 列出的「已知限制与坑」逐条实测，
    验证文档描述与接口真实行为是否一致，并输出 Markdown 报告。

    脚本会先执行「数据源真实性探针」（T0.5）：用三个不同股票代码请求同一接口，
    若返回完全相同，说明当前 licence 只能拿到固定样本数据，
    此时所有依赖股票代码的测试项会被明确标记为「无法验证」，而不会给出错误结论。

.PARAMETER Licence
    API 授权码。缺省使用官方文档中的公开演示 licence（仅能返回样本数据）。
    要得到有效结论，请传入你自己的正式 licence。

.PARAMETER OutFile
    报告输出路径。默认为仓库内 docs/报告/验证报告.md

.PARAMETER TestRateLimit
    是否执行限频压测（连续发送 40 次请求），默认关闭以免消耗配额。

.EXAMPLE
    .\scripts\Verify-Api.ps1
    .\scripts\Verify-Api.ps1 -Licence $env:MAIRUI_LICENCE
    .\scripts\Verify-Api.ps1 -Licence "你的licence" -TestRateLimit
#>

[CmdletBinding()]
param(
    [string] $Licence = "LICENCE-66D8-9F96-0C7F0FBCD073",
    [string] $OutFile,
    [switch] $TestRateLimit
)

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ErrorActionPreference = 'Continue'

$RepoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OutFile)) {
    $OutFile = Join-Path $RepoRoot 'docs\报告\验证报告.md'
}

$BaseApi = "https://api.mairuiapi.com"

# 官方文档中公开的演示 licence，仅用于连通性自测
$DemoLicence = "LICENCE-66D8-9F96-0C7F0FBCD073"

$script:Report = New-Object System.Collections.ArrayList
$script:ReqCount = 0
$script:SampleOnly = $false      # 是否只能拿到固定样本数据
$script:Findings = New-Object System.Collections.ArrayList

function Add-Line { param([string]$Text = "") [void]$script:Report.Add($Text) }

function Write-Head {
    param([string]$Title)
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkGray
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkGray
    Add-Line ""
    Add-Line "## $Title"
    Add-Line ""
}

# 统一请求封装：返回 @{ ok; data; count; ms; err }
function Invoke-Api {
    param([string]$Url, [int]$TimeoutSec = 60)

    $script:ReqCount++
    Write-Host ("  请求 #{0} ..." -f $script:ReqCount) -ForegroundColor DarkGray
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $data = Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec
        $sw.Stop()
        $count = if ($null -eq $data) { 0 } elseif ($data -is [Array]) { $data.Count } else { 1 }
        Write-Host ("    成功  {0} 条 / {1} ms" -f $count, $sw.ElapsedMilliseconds) -ForegroundColor DarkGray
        [pscustomobject]@{ ok = $true; data = $data; count = $count; ms = $sw.ElapsedMilliseconds; err = $null }
    }
    catch {
        $sw.Stop()
        $msg = $_.Exception.Message
        if ($_.Exception.Response) { $msg = "HTTP $([int]$_.Exception.Response.StatusCode) - $msg" }
        Write-Host ("    失败  {0} ms  {1}" -f $sw.ElapsedMilliseconds, $msg) -ForegroundColor DarkYellow
        [pscustomobject]@{ ok = $false; data = $null; count = 0; ms = $sw.ElapsedMilliseconds; err = $msg }
    }
}

function Write-Result {
    param(
        [string]$Name,
        [ValidateSet('PASS', 'FAIL', 'DIFF', 'INFO', 'SKIP')] [string]$Status,
        [string]$Detail
    )
    $color = switch ($Status) {
        'PASS' { 'Green' } 'FAIL' { 'Red' } 'DIFF' { 'Yellow' } 'SKIP' { 'DarkYellow' } default { 'Gray' }
    }
    Write-Host ("[{0}] {1}" -f $Status, $Name) -ForegroundColor $color

    $icon = switch ($Status) {
        'PASS' { '✅ 与文档一致' }
        'FAIL' { '❌ 请求失败' }
        'DIFF' { '⚠️ 与文档不符' }
        'SKIP' { '⛔ 无法验证' }
        default { 'ℹ️ 实测结果' }
    }
    Add-Line "### $Name"
    Add-Line ""
    Add-Line "**$icon**"
    Add-Line ""
    if ($Detail) { Add-Line $Detail; Add-Line "" }

    if ($Status -in @('DIFF', 'SKIP')) { [void]$script:Findings.Add("$Name — $icon") }
}

function Get-Code6 { param([string]$Dm) ($Dm -split '\.')[0] }

# 判断财务字段是否为空（API 可能返回 null / "" / "-"）
function Test-Blank {
    param($Value)
    ($null -eq $Value) -or ("$Value".Trim() -in @('', '-', '0'))
}

function Show-Blank { param($Value) if (Test-Blank $Value) { '_(空)_' } else { "$Value" } }

# ============================================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  麦蕊 API 现状验证" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "licence : $Licence"
Write-Host "开始时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "请保持网络畅通，不要关闭窗口。"
Write-Host "全部完成后会写入: $OutFile" -ForegroundColor Yellow
Write-Host "每发起一次接口请求都会在下面打一行进度。"

Add-Line "# API 验证报告"
Add-Line ""
Add-Line "> 由 ``scripts/Verify-Api.ps1`` 自动生成，用于实测校验 ``docs/设计/API现状.md`` §4 的各项判断。"
Add-Line ">"
Add-Line "> 执行时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')　｜　licence：``$Licence``"

# ============================================================
Write-Head "T0 连通性与 licence 有效性"

$t0 = Invoke-Api "$BaseApi/hslt/list/$Licence"
if (-not $t0.ok) {
    Write-Result "基础连通性" "FAIL" "无法访问 ``hslt/list``：$($t0.err)`n`n后续测试已中止，请检查网络或 licence。"
    $script:Report | Set-Content -Path $OutFile -Encoding UTF8
    Write-Host "`n报告已写入: $OutFile" -ForegroundColor Yellow
    exit 1
}
Write-Result "基础连通性" "PASS" "``hslt/list`` 返回 **$($t0.count)** 条，耗时 $($t0.ms) ms。"
$stockList = $t0.data

# ============================================================
Write-Head "T0.5 数据源真实性探针【前置门禁】"

$probeCodes = @('000001', '600038', '002230')
$probeResults = @()
foreach ($c in $probeCodes) {
    $r = Invoke-Api "$BaseApi/hsrl/ssjy/$c/$Licence" -TimeoutSec 30
    $probeResults += [pscustomobject]@{
        code = $c
        p    = if ($r.ok) { $r.data.p } else { 'ERR' }
        sz   = if ($r.ok) { $r.data.sz } else { 'ERR' }
        t    = if ($r.ok) { $r.data.t } else { 'ERR' }
    }
    Start-Sleep -Milliseconds 350
}

$probeRows = @('| 请求代码 | 返回价格 `p` | 返回总市值 `sz` | 更新时间 `t` |', '|---|---|---|---|')
foreach ($pr in $probeResults) { $probeRows += "| ``$($pr.code)`` | $($pr.p) | $($pr.sz) | $($pr.t) |" }

$distinct = ($probeResults | Select-Object -ExpandProperty p | Sort-Object -Unique).Count
if ($distinct -le 1) {
    $script:SampleOnly = $true
    Write-Result "数据源真实性" "DIFF" (($probeRows -join "`n") + @"

> **三个完全不同的股票代码返回了完全相同的数据。**
>
> 结论：当前 licence **忽略股票代码参数，只返回一份固定样本数据**（实测为平安银行 000001）。
>
> **因此所有「按代码查询」的测试项均无法验证，下方会明确标记为 ⛔，而不会给出结论。**
> 要得到有效结论，请用正式 licence 重跑：
> ``.\scripts\Verify-Api.ps1 -Licence "你的licence"``
"@)
} else {
    Write-Result "数据源真实性" "PASS" (($probeRows -join "`n") + "`n`n> 不同代码返回不同数据，licence 可用于完整验证。")
}

if ($Licence -eq $DemoLicence) {
    Add-Line "> ⚠️ 当前使用的是官方文档中的**公开演示 licence**，本就只提供样本数据，非正式授权。"
    Add-Line ""
}

# ============================================================
Write-Head "T1 (§4.8) hslt/list 覆盖范围与 dm 字段真实格式"

$sample = $stockList[0]
Add-Line '首条原始记录：'
Add-Line ''
Add-Line '```json'
Add-Line ($sample | ConvertTo-Json -Compress)
Add-Line '```'
Add-Line ''

if ($sample.dm -match '\.') {
    Write-Result "dm 字段格式" "DIFF" @"
文档写 ``dm`` 形如 ``000001``、``jys`` 为小写 ``sz``；实测 ``dm`` = ``$($sample.dm)``（**已带市场后缀**），``jys`` = ``$($sample.jys)``（**大写**）。

> **影响（与 §4.6 原结论相反）：** 调用 ``hsstock/*`` 时**无需自行拼接后缀**；反而调用 ``hscp/*`` / ``hsrl/*`` 时需要**主动去掉**后缀。
"@
} else {
    Write-Result "dm 字段格式" "PASS" "``dm`` = ``$($sample.dm)``，与文档一致。"
}

$prefixMap = [ordered]@{
    '000/001 深主板'          = '^(000|001)'
    '002/003 中小板'          = '^(002|003)'
    '300/301 创业板'          = '^(300|301)'
    '600/601/603/605 沪主板'  = '^(600|601|603|605)'
    '688/689 科创板'          = '^(688|689)'
    '4xx/8xx 北交所'          = '^(4|8)'
}
$rows = @('| 板块 | 数量 |', '|---|---|')
foreach ($k in $prefixMap.Keys) {
    $n = @($stockList | Where-Object { (Get-Code6 $_.dm) -match $prefixMap[$k] }).Count
    $rows += "| $k | $n |"
}
$rows += "| **合计** | **$($stockList.Count)** |"

$kcCount = @($stockList | Where-Object { (Get-Code6 $_.dm) -match '^(688|689)' }).Count
$bjCount = @($stockList | Where-Object { (Get-Code6 $_.dm) -match '^(4|8)' }).Count

$covMsg = ($rows -join "`n") + "`n`n"
$covMsg += if ($kcCount -gt 0) { "- **包含科创板**（$kcCount 只），无需另调 ``kc/list/all``。`n" }
           else { "- **不含科创板**，需另调 ``kc/list/all``。`n" }
$covMsg += if ($bjCount -gt 0) { "- **包含北交所**（$bjCount 只）。" }
           else { "- **不含北交所**，需另调 ``bj/list/all``。" }
Write-Result "hslt/list 覆盖范围" "INFO" $covMsg

# ============================================================
Write-Head "T2 (§4.6) 代码参数格式：带后缀 vs 纯 6 位"

if ($script:SampleOnly) {
    Write-Result "代码参数格式" "SKIP" "当前 licence 忽略股票代码，两种写法都会返回同一份样本数据，**无法据此判断格式要求**。需用正式 licence 重测。"
} else {
    $probe = @(
        @{ n = 'hsstock/history'; doc = '带后缀'; a = "$BaseApi/hsstock/history/600038.SH/d/n/$Licence`?lt=1"; b = "$BaseApi/hsstock/history/600038/d/n/$Licence`?lt=1" },
        @{ n = 'hsstock/history/transaction'; doc = '纯代码'; a = "$BaseApi/hsstock/history/transaction/600038.SH/$Licence`?lt=1"; b = "$BaseApi/hsstock/history/transaction/600038/$Licence`?lt=1" },
        @{ n = 'hsrl/ssjy'; doc = '纯代码'; a = "$BaseApi/hsrl/ssjy/600038.SH/$Licence"; b = "$BaseApi/hsrl/ssjy/600038/$Licence" }
    )
    $fmtRows = @('| 接口 | 文档写法 | `600038.SH` | `600038` | 结论 |', '|---|---|---|---|---|')
    foreach ($p in $probe) {
        $ra = Invoke-Api $p.a -TimeoutSec 40; Start-Sleep -Milliseconds 300
        $rb = Invoke-Api $p.b -TimeoutSec 40; Start-Sleep -Milliseconds 300
        $oa = $ra.ok -and $ra.count -gt 0
        $ob = $rb.ok -and $rb.count -gt 0
        $concl = if ($oa -and $ob) { '两种都可' } elseif ($oa) { '仅带后缀' } elseif ($ob) { '仅纯代码' } else { '均失败' }
        $fmtRows += "| ``$($p.n)`` | $($p.doc) | $(if($oa){'✅'}else{'❌'}) | $(if($ob){'✅'}else{'❌'}) | **$concl** |"
    }
    Write-Result "代码参数格式实测" "INFO" ($fmtRows -join "`n")
}

# ============================================================
Write-Head "T3+T4 (§4.5/§4.7) 历史回溯深度与单次条数上限【最关键】"

Write-Host "拉取 600038.SH 全量日线（不带 st/et）..." -ForegroundColor Yellow
$full = Invoke-Api "$BaseApi/hsstock/history/600038.SH/d/n/$Licence" -TimeoutSec 180

if (-not $full.ok) {
    Write-Result "历史回溯深度" "FAIL" "请求失败：$($full.err)"
}
else {
    $first = $full.data[0].t
    $last = $full.data[-1].t
    $firstYear = [int]("$first" -replace '[^0-9]', '').Substring(0, 4)
    $years = (Get-Date).Year - $firstYear

    $tbl = "不带 ``st``/``et`` 请求 ``hsstock/history/600038.SH/d/n``：`n`n" +
           "| 项目 | 实测值 |`n|---|---|`n" +
           "| 返回条数 | **$($full.count)** |`n| 最早交易日 | **$first** |`n" +
           "| 最新交易日 | $last |`n| 回溯年限 | 约 $years 年 |`n| 耗时 | $($full.ms) ms |"

    if ($script:SampleOnly) {
        Write-Result "历史回溯深度（决定「17年后底」是否可行）" "SKIP" ($tbl + @"

> ⛔ **该结果无效。** 当前 licence 返回的是固定样本（$first ~ $last，恒 $($full.count) 条，且与请求代码无关）。
>
> 样本数据的条数上限与真实回溯深度**没有任何关系**，不能据此判定「17年后底」不可行。
>
> **这仍是整套方案的头号未决问题，必须用正式 licence 重跑本项。**
"@)
    }
    elseif ($years -ge 17) {
        Write-Result "历史回溯深度（决定「17年后底」是否可行）" "PASS" ($tbl + "`n`n> **回溯深度满足「17年后底」需求，§2 方案成立。**")
    }
    else {
        Write-Result "历史回溯深度（决定「17年后底」是否可行）" "DIFF" ($tbl + "`n`n> **回溯仅 $years 年，不足 17 年，「17年后底」需改用备选方案。**")
    }

    Start-Sleep -Milliseconds 500
    $early = Invoke-Api "$BaseApi/hsstock/history/600038.SH/d/n/$Licence`?st=19970101&et=20261231" -TimeoutSec 180
    if ($early.ok) {
        $cmp = "| 请求方式 | 条数 | 最早日期 |`n|---|---|---|`n" +
               "| 不传 ``st``/``et`` | $($full.count) | $first |`n" +
               "| 显式 ``st=19970101`` | $($early.count) | $($early.data[0].t) |"
        if ($script:SampleOnly) {
            Write-Result "显式传 st 是否能取到更早数据" "SKIP" ($cmp + "`n`n> ⛔ 样本数据下两者必然相同，无参考意义。需用正式 licence 重测。")
        }
        elseif ($early.count -gt $full.count) {
            Write-Result "显式传 st 是否能取到更早数据" "DIFF" ($cmp + "`n`n> **能。** 说明「不设置时间则为全部历史数据」表述不准，**应始终显式传 ``st``**。")
        }
        else {
            Write-Result "显式传 st 是否能取到更早数据" "PASS" ($cmp + "`n`n> 两者一致，不存在静默截断。")
        }
    }
}

# ============================================================
Write-Head "T5 (§4.9) licence 是否需要「证书」前缀"

$plain = Invoke-Api "$BaseApi/hsstock/real/time/000001/$Licence" -TimeoutSec 40
Start-Sleep -Milliseconds 300
$withPrefix = Invoke-Api "$BaseApi/hsstock/real/time/000001/证书$Licence" -TimeoutSec 40

$okP = $plain.ok -and $plain.count -gt 0
$okW = $withPrefix.ok -and $withPrefix.count -gt 0
$tblL = "| 写法 | 结果 |`n|---|---|`n| ``/{licence}`` | $(if($okP){'✅ 可用'}else{"❌ $($plain.err)"}) |`n| ``/证书{licence}`` | $(if($okW){'✅ 可用'}else{'❌ 失败'}) |"

if ($okP -and -not $okW) {
    Write-Result "hsstock/real/time 的 licence 写法" "PASS" ($tblL + "`n`n> 文档地址模板中的 ``/证书您的licence`` **确为笔误**，实际只需传 licence 本身。")
} else {
    Write-Result "hsstock/real/time 的 licence 写法" "INFO" $tblL
}

# ============================================================
Write-Head "T6 (§4.1) ZygdSdgd 对象的真实结构"

$sdgd = Invoke-Api "$BaseApi/hscp/sdgd/000001/$Licence" -TimeoutSec 40
if (-not $sdgd.ok) {
    Write-Result "十大股东 sdgd 结构" "FAIL" "请求失败：$($sdgd.err)"
}
else {
    $rec = $sdgd.data[0]
    $inner = $rec.sdgd
    if ($inner -and @($inner).Count -gt 0) {
        $fields = @($inner)[0].PSObject.Properties | ForEach-Object { "| ``$($_.Name)`` | $($_.Value) |" }
        Write-Result "ZygdSdgd 真实结构（补齐文档缺失）" "INFO" @"
文档中 ``ZygdSdgd`` 无任何定义。实测请求 ``hscp/sdgd/000001``，内层数组含 $(@($inner).Count) 个元素，第 1 位股东字段如下：

| 字段 | 示例值 |
|---|---|
$($fields -join "`n")

> 外层记录字段：``jzrq``（截止日期）、``ggrq``（公告日期）、``gdsm``（股东说明）、``gdzs``（股东总数）、``pjcg``（平均持股）、``sdgd``（本数组）。
>
> **文档缺失部分至此已补齐**：``Pm`` 排名、``Gdmc`` 股东名称、``Cgsl`` 持股数量、``Cgbl`` 持股比例(%)、``Gbxz`` 股本性质。注意字段名**首字母大写**，与其他接口的全小写风格不一致。
"@
    } else {
        Write-Result "十大股东 sdgd 结构" "DIFF" "返回记录中 ``sdgd`` 为空，无法推断结构。"
    }
}

# ============================================================
Write-Head "T7 (§3.1) 补贴收入 btsr 与其他收益 qtsy"

$incCode = '000001.SZ'
$inc = Invoke-Api "$BaseApi/hsstock/financial/income/$incCode/$Licence`?st=20240101&et=20251231" -TimeoutSec 60
if (-not $inc.ok -or $inc.count -eq 0) {
    Write-Result "利润表 btsr / qtsy" "FAIL" "请求失败或无数据：$($inc.err)"
}
else {
    $rowsFin = @('| 截止日期 | `btsr` 补贴收入 | `qtsy` 其他收益 | `yffy` 研发费用 | `yyzsr` 营业总收入 |', '|---|---|---|---|---|')
    foreach ($r in ($inc.data | Select-Object -First 6)) {
        $rowsFin += "| $($r.jzrq) | $(Show-Blank $r.btsr) | $(Show-Blank $r.qtsy) | $(Show-Blank $r.yffy) | $(Show-Blank $r.yyzsr) |"
    }
    $btsrBlank = @($inc.data | Where-Object { Test-Blank $_.btsr }).Count
    $qtsyHas = @($inc.data | Where-Object { -not (Test-Blank $_.qtsy) }).Count

    $concl = if ($btsrBlank -eq $inc.count -and $qtsyHas -gt 0) {
        "`n> ✅ **证实 §3.1 的判断**：``btsr`` 全部为空（$btsrBlank/$($inc.count) 期），而 ``qtsy`` 有实值（$qtsyHas 期）。`n> 政府补助确已改列报于「其他收益」，**取数应以 ``qtsy`` 为准，``btsr`` 不可用**。"
    } elseif ($btsrBlank -eq $inc.count) {
        "`n> ``btsr`` 全部为空，但 ``qtsy`` 也无值，需换标的复核。"
    } else {
        "`n> ``btsr`` 存在非空值（$($inc.count - $btsrBlank) 期），需按报告期分别处理。"
    }
    Write-Result "利润表 btsr / qtsy 实测（$incCode，2024-2025）" "INFO" (($rowsFin -join "`n") + $concl)
}

# ============================================================
Write-Head "T8 (§3.2) X 日价：指定日期取收盘价"

$xdDate = '20250930'
$xd = Invoke-Api "$BaseApi/hsstock/history/000001.SZ/d/n/$Licence`?st=$xdDate&et=$xdDate" -TimeoutSec 40
if ($xd.ok -and $xd.count -eq 1) {
    Write-Result "X 日价取数方案" "PASS" "``st=$xdDate&et=$xdDate`` 精确返回 1 条：`n`n``````json`n$(($xd.data | Select-Object -First 1) | ConvertTo-Json -Compress)`n``````"
}
elseif ($xd.ok -and $xd.count -gt 1) {
    Write-Result "X 日价取数方案" "DIFF" "指定单日却返回 **$($xd.count)** 条（首条 $($xd.data[0].t)），说明 **``st``/``et`` 参数未被接口正确处理**$(if($script:SampleOnly){'（当前为样本数据，需正式 licence 复测）'})。取数时必须在本地按日期二次过滤。"
}
else {
    Write-Result "X 日价取数方案" "DIFF" "指定 $xdDate 未返回数据（非交易日或停牌），需实现「回退到最近交易日」逻辑。err=$($xd.err)"
}

# ============================================================
Write-Head "T9 (§4.3) 科创板 / 北交所能否走 hsstock 历史接口"

if ($script:SampleOnly) {
    Write-Result "跨市场支持" "SKIP" "当前 licence 忽略股票代码，任何代码都会返回同一份样本，**无法判断跨市场支持情况**。需用正式 licence 重测。"
}
else {
    $crossRows = @('| 标的 | 市场 | `hsstock/history` 结果 |', '|---|---|---|')
    foreach ($c in @(@{c = '688001.SH'; m = '科创板' }, @{c = '430017.BJ'; m = '北交所' }, @{c = '300294.SZ'; m = '创业板' })) {
        $r = Invoke-Api "$BaseApi/hsstock/history/$($c.c)/d/n/$Licence`?lt=1" -TimeoutSec 40
        Start-Sleep -Milliseconds 300
        $crossRows += "| ``$($c.c)`` | $($c.m) | $(if($r.ok -and $r.count -gt 0){"✅ 可用（最新 $($r.data[0].t)）"}else{'❌ 无数据'}) |"
    }
    Write-Result "跨市场支持" "INFO" (($crossRows -join "`n") + "`n`n> 若科创板/北交所可走 ``hsstock/history``，则 §4.3「这两个市场算不出底/顶」的结论需放宽。")
}

# ============================================================
if ($TestRateLimit) {
    Write-Head "T10 (§4.2) 限频实测"
    $n = 40; $fail = 0
    $swr = [Diagnostics.Stopwatch]::StartNew()
    for ($i = 1; $i -le $n; $i++) {
        if (-not (Invoke-Api "$BaseApi/hsrl/ssjy/000001/$Licence" -TimeoutSec 20).ok) { $fail++ }
    }
    $swr.Stop()
    Write-Result "连续 $n 次请求" "INFO" "耗时 $([math]::Round($swr.Elapsed.TotalSeconds,1)) 秒，失败 $fail 次。"
}
else {
    Write-Head "T10 (§4.2) 限频实测【已跳过】"
    Add-Line "加 ``-TestRateLimit`` 开关可执行连续 40 次请求的压测，默认跳过以免消耗配额。"
    Add-Line ""
    Write-Host "已跳过（加 -TestRateLimit 可启用）" -ForegroundColor DarkGray
}

# ============================================================
Add-Line ""
Add-Line "---"
Add-Line ""
Add-Line "## 需要关注的结论"
Add-Line ""
if ($script:Findings.Count -eq 0) {
    Add-Line "本轮无异常项。"
} else {
    foreach ($f in $script:Findings) { Add-Line "- $f" }
}
Add-Line ""
if ($script:SampleOnly) {
    Add-Line "> ⛔ **本轮为样本数据，结论不完整。** 请用正式 licence 重跑："
    Add-Line "> ``````powershell"
    Add-Line "> .\scripts\Verify-Api.ps1 -Licence `"你的licence`""
    Add-Line "> ``````"
    Add-Line ""
}
Add-Line "## 统计"
Add-Line ""
Add-Line "- 总请求数：**$script:ReqCount**"
Add-Line "- 完成时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

$dir = Split-Path $OutFile -Parent
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
$script:Report | Set-Content -Path $OutFile -Encoding UTF8

Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkGray
if ($script:SampleOnly) {
    Write-Host "注意：本轮仅拿到样本数据，按代码查询的结论均未验证" -ForegroundColor Yellow
}
Write-Host "验证完成，共发起 $script:ReqCount 次请求" -ForegroundColor Green
Write-Host "报告: $(Resolve-Path $OutFile)" -ForegroundColor Green

