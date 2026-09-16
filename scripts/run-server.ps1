$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    $OutputEncoding = [Text.Encoding]::UTF8
} catch { }
try { $Host.UI.RawUI.WindowTitle = "Stock-Analyzer 运行中（请勿关闭）" } catch { }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$LogDir = Join-Path $root "data\logs"
$script:RunLog = $null

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

function Write-Detail([string]$Text) {
    Write-Host "      $Text" -ForegroundColor DarkGray
}

function Write-Warn([string]$Text) {
    Write-Host "    [注意] $Text" -ForegroundColor Yellow
}

function Write-Fail([string]$Text) {
    Write-Host ""
    Write-Host "[失败] $Text" -ForegroundColor Red
}

function Write-LogHint {
    if ($script:RunLog) {
        Write-Host "本轮完整日志：$script:RunLog"
    }
}

function Start-RunLog {
    try {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
        $script:RunLog = Join-Path $LogDir ("run-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
        Start-Transcript -Path $script:RunLog -Force | Out-Null
    } catch {
        $script:RunLog = Join-Path $env:TEMP ("stock-analyzer-run-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
        try { Start-Transcript -Path $script:RunLog -Force | Out-Null } catch { $script:RunLog = $null }
    }
}

function Invoke-Native([string]$File, [string[]]$Args) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $raw = & $File @Args 2>&1
        $code = $LASTEXITCODE
        $text = (($raw | ForEach-Object { "$_" }) -join "`n").Trim()
        return @{ Code = $code; Text = $text }
    } catch {
        return @{ Code = 1; Text = $_.Exception.Message }
    } finally {
        $ErrorActionPreference = $prev
    }
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

function Test-VenvPython([string]$exe) {
    if (-not (Test-Path -LiteralPath $exe)) { return $false }
    $run = Invoke-Native $exe @("-c", "import sys; sys.stdout.write('%d.%d' % (sys.version_info.major, sys.version_info.minor))")
    if ($run.Code -ne 0 -or -not $run.Text) { return $false }
    if ($run.Text -match "(\d+)\.(\d+)") {
        $maj = [int]$Matches[1]
        $min = [int]$Matches[2]
        return ($maj -eq 3 -and ($min -eq 11 -or $min -eq 12))
    }
    return $false
}

Start-RunLog

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Stock-Analyzer 启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "请不要关闭本窗口。关掉它，网页就会打不开。"
Write-Host "工作目录: $root"
Write-Host "开始时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "系统: $([Environment]::OSVersion.VersionString)　用户: $env:USERNAME"
if ($script:RunLog) { Write-Host "本轮日志: $script:RunLog" }

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$code = 0
$proc = $null

try {
    Write-Step "[1/4] 检查运行环境"
    if (-not (Test-VenvPython $venvPy)) {
        if (Test-Path -LiteralPath $venvPy) {
            Write-Warn ".venv 在，但是不能用。将重新跑一键配置。"
        } else {
            Write-Warn "还没有完成配置，将自动运行一键配置（可能要几分钟）"
        }
        $setupPs1 = Join-Path $PSScriptRoot "setup.ps1"
        if (-not (Test-Path -LiteralPath $setupPs1)) {
            Write-Fail "找不到 scripts\setup.ps1，软件文件不完整。"
            Write-LogHint
            exit 1
        }
        Write-Info "正在调用 $setupPs1"
        Write-Host ""
        $env:STOCK_ANALYZER_NESTED_SETUP = "1"
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setupPs1
        $setupCode = $LASTEXITCODE
        $ErrorActionPreference = $prev
        if ($null -eq $setupCode) { $setupCode = 1 }
        if ($setupCode -ne 0) {
            Write-Fail "自动配置没有成功，服务现在还不能打开（配置退出码 $setupCode）。"
            Write-Host "    请向上滚动阅读配置阶段的中文说明，不要只看这一行。"
            Write-Host "    常见原因：E:\python-stock 里的 python.exe 不完整，或 Python 被装到了用户目录。"
            Write-Host "    也可以关掉本窗口，再双击 scripts\setup.cmd。"
            Write-LogHint
            exit $setupCode
        }
    }
    if (-not (Test-VenvPython $venvPy)) {
        Write-Fail "配置跑完后，.venv 仍然不能用。"
        Write-Host "    期望的文件：$venvPy"
        Write-Host "    请新开窗口再双击 scripts\setup.cmd，并把窗口全文发给工作人员。"
        Write-LogHint
        exit 1
    }
    $verRun = Invoke-Native $venvPy @("--version")
    Write-Ok "运行环境已就绪（$venvPy）"
    if ($verRun.Text) { Write-Detail $verRun.Text }

    Write-Step "[2/4] 检查配置文件"
    $envFile = Join-Path $root ".env"
    $example = Join-Path $root ".env.example"
    if (-not (Test-Path -LiteralPath $envFile)) {
        if (-not (Test-Path -LiteralPath $example)) {
            Write-Fail "找不到 .env 和 .env.example，软件文件不完整。"
            Write-LogHint
            exit 1
        }
        Copy-Item -LiteralPath $example -Destination $envFile
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
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
        $ErrorActionPreference = $prev
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
        $exe = [string]$p.ExecutablePath
        if ($exe -and (Test-Path -LiteralPath $venvPy)) {
            $want = [IO.Path]::GetFullPath($venvPy)
            if ($exe.Equals($want, [StringComparison]::OrdinalIgnoreCase)) { return $true }
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
    $listen = @(Get-ListenPids $port)
    foreach ($processId in $listen) {
        if (Test-OurServerProcess $processId) {
            if (-not $ids.Contains($processId)) { $ids.Add($processId) }
        } else {
            $p = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
            $who = "未知进程"
            if ($p) { $who = "$($p.Name) $($p.CommandLine)" }
            Write-Warn "端口 $port 已被其它程序占用：PID $processId （$who）"
            Write-Host "    本软件不会强行结束别人的程序。请先关掉占用 8765 端口的软件，或改 .env 里的 APP_PORT。"
        }
    }
    if ($ids.Count -eq 0) {
        Write-Ok "没有发现本软件的残留进程"
    } else {
        foreach ($processId in $ids) {
            Write-Warn "正在结束本软件残留进程 PID $processId"
            Stop-ProcessTree $processId
        }
        Start-Sleep -Milliseconds 800
        Write-Ok "残留进程已清理"
    }
    $still = @(Get-ListenPids $port)
    $foreign = @($still | Where-Object { -not (Test-OurServerProcess $_) })
    if ($foreign.Count -gt 0) {
        Write-Fail "端口 $port 仍被其它程序占用（PID $($foreign -join ', ')），无法启动。"
        Write-LogHint
        exit 1
    }

    Write-Step "[4/4] 启动服务"
    Write-Info "正在拉起进程，下面可能会出现一些英文日志，属于正常现象"
    $proc = Start-Process -FilePath $venvPy -ArgumentList "-m src.main" -WorkingDirectory $root -NoNewWindow -PassThru
    if (-not $proc) {
        Write-Fail "无法启动 $venvPy -m src.main"
        Write-LogHint
        exit 1
    }
    Write-Ok "进程已启动，PID $($proc.Id)"
    Write-Info "正在等待端口 $port 就绪（首次启动可能要几十秒）..."

    $ready = $false
    $deadline = (Get-Date).AddSeconds(60)
    $lastPing = Get-Date
    $started = Get-Date
    while ($proc -and -not $proc.HasExited -and (Get-Date) -lt $deadline) {
        $listening = @(Get-ListenPids $port)
        if ($listening.Count -gt 0) {
            $ready = $true
            Write-Detail ("端口 {0} 已监听，PID {1}" -f $port, ($listening -join ", "))
            break
        }
        if (((Get-Date) - $lastPing).TotalSeconds -ge 5) {
            $waited = [int]((Get-Date) - $started).TotalSeconds
            Write-Info "仍在启动，已等待 ${waited} 秒，请不要关闭窗口..."
            $lastPing = Get-Date
        }
        Start-Sleep -Milliseconds 300
        $proc.Refresh()
    }

    if ($proc.HasExited) {
        $code = $proc.ExitCode
        Write-Fail "服务进程已退出，退出码 $code"
        Write-Host "请向上滚动，查看红色或英文报错，把完整内容发给工作人员。"
        Write-LogHint
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
    Write-LogHint
    Write-Host ""

    while ($proc -and -not $proc.HasExited) {
        Start-Sleep -Milliseconds 300
        $proc.Refresh()
    }
    if ($proc -and $null -ne $proc.ExitCode) {
        $code = $proc.ExitCode
    }
} catch {
    $code = 1
    Write-Fail "启动遇到未处理的错误。"
    Write-Host $_.Exception.Message
    if ($_.ScriptStackTrace) { Write-Host $_.ScriptStackTrace }
    Write-Host "请把本窗口全文发给工作人员。"
    Write-LogHint
} finally {
    if ($proc) {
        try { $proc.Refresh() } catch { }
        if (-not $proc.HasExited) {
            Write-Host ""
            Write-Warn "正在停止服务 PID $($proc.Id) ..."
            if ($proc.Id -gt 0) {
                $prev = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                & taskkill.exe /PID $proc.Id /T /F 2>$null | Out-Null
                $ErrorActionPreference = $prev
            }
            Write-Ok "服务已停止"
        } else {
            Write-Host ""
            Write-Info "服务已结束（退出码 $code）"
        }
    }
    try { $Host.UI.RawUI.WindowTitle = "Stock-Analyzer 已停止" } catch { }
    try { Stop-Transcript | Out-Null } catch { }
}
exit $code
