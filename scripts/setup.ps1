# One-click setup. Runtime Python 3.11/3.12 must live at E:\python-stock on this machine.
$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    $OutputEncoding = [Text.Encoding]::UTF8
} catch { }
try { $Host.UI.RawUI.WindowTitle = "Stock-Analyzer 配置" } catch { }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$PythonHome = "E:\python-stock"
$InstallerUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"

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

function Test-PythonHomeDrive {
    if (-not (Test-Path -LiteralPath "E:\")) {
        Write-Fail "这台电脑没有 E: 盘。"
        Write-Host "软件规定 Python 必须安装在 $PythonHome"
        Write-Host "请先准备好 E: 盘（第二块硬盘、U 盘改盘符，或请会电脑的人帮忙），再重新双击 scripts\setup.cmd"
        exit 1
    }
}

function Test-ManagedPython([string]$exe) {
    if (-not $exe) { return $false }
    if ($exe -match "WindowsApps\\python") { return $false }
    if (-not (Test-Path -LiteralPath $exe)) { return $false }
    try {
        $full = [IO.Path]::GetFullPath($exe)
        $home = [IO.Path]::GetFullPath($PythonHome)
        if (-not $full.StartsWith($home, [StringComparison]::OrdinalIgnoreCase)) { return $false }
        $ver = & $exe -c "import sys; print('%d.%d' % (sys.version_info.major, sys.version_info.minor))" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $ver) { return $false }
        $parts = $ver.Trim().Split(".")
        $maj = [int]$parts[0]
        $min = [int]$parts[1]
        return ($maj -eq 3 -and ($min -eq 11 -or $min -eq 12))
    } catch {
        return $false
    }
}

function Find-Python {
    $candidates = @(
        (Join-Path $PythonHome "python.exe"),
        (Join-Path $PythonHome "Python312\python.exe"),
        (Join-Path $PythonHome "Python311\python.exe")
    )
    foreach ($p in $candidates) {
        if (Test-ManagedPython $p) { return $p }
    }
    return $null
}

function Get-PythonVersion([string]$exe) {
    try {
        $v = & $exe -c "import sys; print(sys.version.split()[0])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { return $v.Trim() }
    } catch { }
    return "?"
}

function Install-Python {
    Test-PythonHomeDrive
    if (-not (Test-Path -LiteralPath $PythonHome)) {
        Write-Info "正在创建目录 $PythonHome"
        New-Item -ItemType Directory -Path $PythonHome -Force | Out-Null
    }

    $installer = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
    $reuse = $false
    if (Test-Path -LiteralPath $installer) {
        $existingMb = [math]::Round((Get-Item -LiteralPath $installer).Length / 1MB, 1)
        if ((Get-Item -LiteralPath $installer).Length -ge 20MB) {
            Write-Info "发现上次已下载的安装包（$existingMb MB），跳过重复下载"
            Write-Info $installer
            $reuse = $true
        } else {
            Write-Warn "临时目录里的安装包不完整（$existingMb MB），将重新下载"
        }
    }

    if (-not $reuse) {
        Write-Info "开始下载 Python 3.12.10（大约 27 MB），请保持网络畅通"
        Write-Info "来源: $InstallerUrl"
        Write-Info "保存到: $installer"
        Write-Info "下面会出现进度条；没有动也不要关窗口"
        & curl.exe -fL --progress-bar --stderr - -o $installer $InstallerUrl
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $installer)) {
            Write-Fail "下载 Python 失败。"
            Write-Host "请检查网络后，再双击 scripts\setup.cmd"
            Write-Host "也可以自己安装 Python 3.11 或 3.12 到 $PythonHome"
            Write-Host "官方安装包: $InstallerUrl"
            exit 1
        }
        $mb = [math]::Round((Get-Item -LiteralPath $installer).Length / 1MB, 1)
        Write-Ok "下载完成，文件大小 $mb MB"
    }

    Write-Info "正在安装到 $PythonHome"
    Write-Warn "安装窗口可能几乎没有进度，静默等待 1～3 分钟是正常的，请不要关闭"
    $installerArgs = @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=0",
        "Include_launcher=0",
        "Include_test=0",
        "Include_doc=0",
        "Include_pip=1",
        "SimpleInstall=1",
        "TargetDir=$PythonHome",
        "DefaultJustForMeTargetDir=$PythonHome",
        "DefaultCustomTargetDir=$PythonHome"
    )
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $proc = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru
    $sw.Stop()
    if ($proc.ExitCode -ne 0) {
        Write-Fail "Python 安装程序退出码 $($proc.ExitCode)"
        Write-Host "如果是权限问题：右键 scripts\setup.cmd → 以管理员身份运行"
        Write-Host "安装成功后，这里必须出现文件：$PythonHome\python.exe"
        exit $proc.ExitCode
    }
    Write-Ok ("Python 安装完成，用时 {0} 秒" -f [int]$sw.Elapsed.TotalSeconds)
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Stock-Analyzer 一键配置" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "请不要关闭本窗口。全部完成后会告诉你下一步怎么做。"
Write-Host "工作目录: $root"
Write-Host "开始时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "将依次检查：E: 盘 → Python → 运行环境 → 依赖包 → 配置文件"

Write-Step "[1/6] 检查是否有 E: 盘"
Test-PythonHomeDrive
Write-Ok "已找到 E: 盘。Python 将安装/使用 $PythonHome"

Write-Step "[2/6] 查找 Python 3.11 或 3.12"
Write-Info "只认 $PythonHome 下的 3.11 / 3.12，系统里其它 Python 一律不用"
$py = Find-Python
if (-not $py) {
    $existing = Join-Path $PythonHome "python.exe"
    if (Test-Path -LiteralPath $existing) {
        Write-Fail "找到了 $existing，但不是 Python 3.11 或 3.12。"
        Write-Host "请先把这个安装移走或卸载，再重新运行 scripts\setup.cmd"
        exit 1
    }
    Write-Warn "还没有可用的 Python，将自动下载并安装 3.12.10（需要联网）"
    Install-Python
    Write-Info "正在确认安装结果..."
    $py = Find-Python
}
if (-not $py) {
    Write-Fail "安装结束后，仍未在 $PythonHome 找到 Python 3.11/3.12。"
    Write-Host "请打开文件资源管理器，看是否存在 $PythonHome\python.exe，然后重试 scripts\setup.cmd"
    exit 1
}
$pyVer = Get-PythonVersion $py
Write-Ok "将使用 $py （版本 $pyVer）"

Write-Step "[3/6] 准备本软件运行环境（.venv）"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Info "第一次创建大约需要半分钟到一分钟，请稍候"
    & $py -m venv .venv
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        Write-Fail "创建 .venv 失败。"
        Write-Host "请把本窗口完整内容发给工作人员。"
        exit 1
    }
    Write-Ok "已创建 .venv"
} else {
    Write-Ok ".venv 已存在，跳过创建"
}

Write-Step "[4/6] 升级 pip（安装工具本身）"
Write-Info "下面会刷一些英文进度，属于正常现象"
& .\.venv\Scripts\python.exe -m pip install -U pip
if ($LASTEXITCODE -ne 0) {
    Write-Fail "升级 pip 失败。请检查网络后重试。"
    exit $LASTEXITCODE
}
Write-Ok "pip 已就绪"

Write-Step "[5/6] 安装软件依赖包"
Write-Info "可能需要几分钟。已装过的包会很快跳过；请不要关闭窗口"
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Fail "安装依赖失败。请检查网络后，再双击 scripts\setup.cmd"
    exit $LASTEXITCODE
}
Write-Ok "依赖包安装完成"

Write-Step "[6/6] 准备配置文件 .env"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Ok "已从模板复制 .env（默认离线模式，不必填 licence 也能打开）"
    Write-Info "以后若有正式行情授权或 AI 密钥，再请工作人员帮你改 .env"
} else {
    Write-Ok ".env 已存在，未改动"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  配置成功" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
if ($env:STOCK_ANALYZER_NESTED_SETUP -eq "1") {
    Write-Host "配置已完成，接下来会自动启动服务，请继续等待。"
} else {
    Write-Host "下一步（请按顺序做）："
    Write-Host "  1. 读完后关掉本窗口"
    Write-Host "  2. 双击  scripts\run-server.cmd  启动软件"
    Write-Host "  3. 打开浏览器，在地址栏输入（不要去搜索）："
    Write-Host "       http://127.0.0.1:8765" -ForegroundColor Yellow
    Write-Host "  4. 登录账号: hanish"
    Write-Host "     登录密码: change-me"
}
Write-Host ""
Write-Host "结束时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
