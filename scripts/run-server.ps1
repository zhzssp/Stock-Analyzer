$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    $OutputEncoding = [Text.Encoding]::UTF8
} catch { }
try { $Host.UI.RawUI.WindowTitle = "Stock-Analyzer 运行中（请勿关闭）" } catch { }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Write-Step([string]$Title) {
    Write-Host ""
    Write-Host ">>> $Title" -ForegroundColor Cyan
}

function Write-Ok([string]$Text) {
    Write-Host "    [完成] $Text" -ForegroundColor Green
}

function Write-Info([string]$Text) {
    Write-Host "    $Text"
}

function Write-Warn([string]$Text) {
    Write-Host "    [注意] $Text" -ForegroundColor Yellow
}

function Write-Fail([string]$Text) {
    Write-Host ""
    Write-Host "[失败] $Text" -ForegroundColor Red
}

function Get-DotEnv([string]$Name, [string]$Default) {
    $envFile = Join-Path $root ".env"
    if (-not (Test-Path -LiteralPath $envFile)) { return $Default }
    foreach ($line in Get-Content -LiteralPath $envFile) {
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

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Stock-Analyzer 启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "请不要关闭本窗口。关掉它，网页就会打不开。"
Write-Host "工作目录: $root"
Write-Host "开始时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

Write-Step "[1/4] 检查运行环境"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Warn "还没有完成配置，将自动运行一键配置（可能要几分钟）"
    Write-Host ""
    $env:STOCK_ANALYZER_NESTED_SETUP = "1"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "setup.ps1")
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "自动配置没有成功，服务现在还不能打开。"
        Write-Host "    配置在创建运行环境之前就停了（常见：Python 被装到了用户目录，而本软件只认 E:\python-stock）。"
        Write-Host "    请把上面的配置日志看完；或再双击 scripts\setup.cmd。"
        exit $LASTEXITCODE
    }
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Fail "配置跑完后仍然没有 .venv。请新开窗口再双击 scripts\setup.cmd"
    exit 1
}
Write-Ok "运行环境已就绪（.venv）"

Write-Step "[2/4] 检查配置文件"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Ok "已从模板创建 .env（离线模式）"
} else {
    Write-Ok ".env 已存在"
}

$port = 8765
$portText = Get-DotEnv "APP_PORT" "8765"
if ($portText -match '^\d+$') { $port = [int]$portText }
$user = Get-DotEnv "BOOTSTRAP_USER" "hanish"
$pass = Get-DotEnv "BOOTSTRAP_PASSWORD" "change-me"
$url = "http://127.0.0.1:$port"
Write-Info "访问地址将是 $url"

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

Write-Step "[3/4] 清理上次没关干净的服务"
$ids = New-Object System.Collections.Generic.List[int]
foreach ($processId in Get-OurServerPids) {
    if (-not $ids.Contains($processId)) { $ids.Add($processId) }
}
foreach ($processId in Get-ListenPids $port) {
    if ((Test-OurServerProcess $processId) -and -not $ids.Contains($processId)) {
        $ids.Add($processId)
    }
}
if ($ids.Count -eq 0) {
    Write-Ok "没有发现残留进程"
} else {
    foreach ($processId in $ids) {
        Write-Warn "正在结束残留进程 PID $processId"
        Stop-ProcessTree $processId
    }
    Start-Sleep -Milliseconds 800
    Write-Ok "残留进程已清理"
}

Write-Step "[4/4] 启动服务"
$py = Join-Path $root ".venv\Scripts\python.exe"
$proc = $null
$code = 0
try {
    Write-Info "正在拉起进程，下面可能会出现一些英文日志，属于正常现象"
    $proc = Start-Process -FilePath $py -ArgumentList "-m src.main" -WorkingDirectory $root -NoNewWindow -PassThru
    Write-Ok "进程已启动，PID $($proc.Id)"
    Write-Info "正在等待端口 $port 就绪（首次启动可能要几十秒）..."

    $ready = $false
    $deadline = (Get-Date).AddSeconds(60)
    $lastPing = Get-Date
    while ($proc -and -not $proc.HasExited -and (Get-Date) -lt $deadline) {
        $listening = Get-ListenPids $port
        if ($listening.Count -gt 0) {
            $ready = $true
            break
        }
        if (((Get-Date) - $lastPing).TotalSeconds -ge 5) {
            Write-Warn "仍在启动，请再等一会儿，不要关闭窗口..."
            $lastPing = Get-Date
        }
        Start-Sleep -Milliseconds 300
        $proc.Refresh()
    }

    if ($proc.HasExited) {
        $code = $proc.ExitCode
        Write-Fail "服务进程已退出，退出码 $code"
        Write-Host "请向上滚动，查看红色或英文报错，把完整内容发给工作人员。"
        exit $code
    }

    if ($ready) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  启动成功，可以打开浏览器了" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
    } else {
        Write-Warn "60 秒内还没检测到端口 $port，服务可能仍在加载"
        Write-Warn "请再等一会儿再试浏览器；一直打不开就把本窗口内容发给工作人员"
        Write-Host ""
    }

    Write-Host "  请在浏览器地址栏输入（不要去搜索）：" 
    Write-Host "    $url" -ForegroundColor Yellow
    Write-Host "  登录账号: $user"
    Write-Host "  登录密码: $pass"
    Write-Host ""
    Write-Host "  *** 请不要关闭本窗口，不要点右上角的叉 ***" -ForegroundColor Yellow
    Write-Host "  用完后：用鼠标点一下本窗口，按 Ctrl+C 停止。"
    Write-Host ""

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
            Write-Host ""
            Write-Warn "正在停止服务 PID $($proc.Id) ..."
            Stop-ProcessTree $proc.Id
            Write-Ok "服务已停止"
        } else {
            Write-Host ""
            Write-Info "服务已结束（退出码 $code）"
        }
    }
    try { $Host.UI.RawUI.WindowTitle = "Stock-Analyzer 已停止" } catch { }
}
exit $code
