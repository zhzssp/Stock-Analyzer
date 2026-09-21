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
$InstallerLog = Join-Path $env:TEMP "stock-analyzer-python-install.log"
$LogDir = Join-Path $root "data\logs"
$script:RunLog = $null
$script:OwnTranscript = $false
$script:StepWatch = $null

function Write-Step([string]$Title) {
    Write-Host ""
    Write-Host ">>> $Title" -ForegroundColor Cyan
    $script:StepWatch = [Diagnostics.Stopwatch]::StartNew()
}

function Write-StepDone([string]$Text) {
    $sec = 0
    if ($script:StepWatch) { $sec = [int]$script:StepWatch.Elapsed.TotalSeconds }
    Write-Host ("    [完成] {0}（本步 {1} 秒）" -f $Text, $sec) -ForegroundColor Green
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
    if (Test-Path -LiteralPath $InstallerLog) {
        Write-Host "Python 安装器日志：$InstallerLog"
    }
}

function Start-SetupLog {
    try {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
        $script:RunLog = Join-Path $LogDir ("setup-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
        Start-Transcript -Path $script:RunLog -Force | Out-Null
        $script:OwnTranscript = $true
    } catch {
        if ("$($_.Exception.Message)" -match "already|已经") {
            Write-Host "    当前窗口已经在记日志，配置过程会写进同一份文件。"
            $script:RunLog = $null
            return
        }
        $script:RunLog = Join-Path $env:TEMP ("stock-analyzer-setup-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
        try {
            Start-Transcript -Path $script:RunLog -Force | Out-Null
            $script:OwnTranscript = $true
        } catch {
            $script:RunLog = $null
        }
    }
}

function Get-SafeText($Value) {
    if ($null -eq $Value) { return "" }
    try { return ([string]$Value).Trim() } catch { return "" }
}

function Format-ProcessArgs([string[]]$Parts) {
    if ($null -eq $Parts) { return "" }
    $bits = New-Object System.Collections.Generic.List[string]
    foreach ($raw in @($Parts)) {
        $p = [string]$raw
        if ($p -notmatch '[ \t"]') { [void]$bits.Add($p); continue }
        [void]$bits.Add(('"' + ($p -replace '"', '\"') + '"'))
    }
    return ($bits -join " ")
}

function Invoke-Native([string]$File, [string[]]$NativeArgs, [int]$TimeoutSec = 15) {
    $exe = $File
    if (-not (Test-Path -LiteralPath $File)) {
        $cmd = Get-Command $File -ErrorAction SilentlyContinue -CommandType Application
        if ($cmd -and $cmd.Source) { $exe = [string]$cmd.Source }
    }
    if (-not (Test-Path -LiteralPath $exe)) {
        return @{ Code = 1; Text = "找不到可执行文件: $File" }
    }
    if ($TimeoutSec -lt 1) { $TimeoutSec = 15 }

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $exe
        $psi.Arguments = Format-ProcessArgs @($NativeArgs)
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $psi.ErrorDialog = $false
        $parent = Split-Path -Parent $exe
        if ($parent -and (Test-Path -LiteralPath $parent)) {
            $psi.WorkingDirectory = $parent
            try {
                $pathNow = $psi.EnvironmentVariables["PATH"]
                if (-not $pathNow) { $pathNow = [Environment]::GetEnvironmentVariable("PATH") }
                $psi.EnvironmentVariables["PATH"] = $parent + ";" + $pathNow
            } catch { }
        }

        $p = New-Object System.Diagnostics.Process
        $p.StartInfo = $psi
        try {
            [void]$p.Start()
        } catch {
            return @{ Code = 1; Text = "无法启动 ${exe}：$($_.Exception.Message)" }
        }

        $outTask = $null
        $errTask = $null
        try { $outTask = $p.StandardOutput.ReadToEndAsync() } catch { }
        try { $errTask = $p.StandardError.ReadToEndAsync() } catch { }

        if (-not $p.WaitForExit($TimeoutSec * 1000)) {
            Write-Warn "试跑 $exe 超过 ${TimeoutSec} 秒仍无响应，正在结束该进程..."
            try { if (-not $p.HasExited) { $p.Kill() } } catch { }
            try { & taskkill.exe /PID $p.Id /T /F 2>$null | Out-Null } catch { }
            return @{ Code = -1; Text = "试跑超时（${TimeoutSec} 秒）。常见原因：安装不完整、缺少运行库、或弹出了被挡住的错误窗口。" }
        }

        $out = ""
        $err = ""
        try { if ($outTask) { $out = $outTask.GetAwaiter().GetResult() } } catch { }
        try { if ($errTask) { $err = $errTask.GetAwaiter().GetResult() } } catch { }
        $text = Get-SafeText $out
        $errText = Get-SafeText $err
        if ($errText) {
            if ($text) { $text = $text + "`n" + $errText } else { $text = $errText }
        }
        $code = 1
        try { $code = [int]$p.ExitCode } catch { }
        try { $p.Dispose() } catch { }
        return @{ Code = $code; Text = $text }
    } catch {
        return @{ Code = 1; Text = $_.Exception.Message }
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

function Invoke-NativeViaCmd([string]$File, [string[]]$NativeArgs, [int]$TimeoutSec = 15) {
    $outFile = Join-Path $env:TEMP ("stock-analyzer-cmdout-{0}.txt" -f [guid]::NewGuid().ToString("N"))
    $batFile = Join-Path $env:TEMP ("stock-analyzer-cmdrun-{0}.cmd" -f [guid]::NewGuid().ToString("N"))
    $argLine = Format-ProcessArgs @($NativeArgs)
    $parent = Split-Path -Parent $File
    $lines = @(
        "@echo off",
        "cd /d `"$parent`"",
        "`"$File`" $argLine > `"$outFile`" 2>&1"
    )
    try {
        [IO.File]::WriteAllLines($batFile, $lines, [Text.Encoding]::Default)
        $run = Invoke-Native "cmd.exe" @("/d", "/c", $batFile) $TimeoutSec
        $text = ""
        if (Test-Path -LiteralPath $outFile) {
            try { $text = Get-SafeText ([IO.File]::ReadAllText($outFile)) } catch { }
        }
        if (-not $text) { $text = Get-SafeText $run.Text }
        return @{ Code = $run.Code; Text = $text }
    } catch {
        return @{ Code = 1; Text = $_.Exception.Message }
    } finally {
        Remove-Item -LiteralPath $outFile, $batFile -Force -ErrorAction SilentlyContinue
    }
}

function Test-PythonHomeDrive {
    if (-not (Test-Path -LiteralPath "E:\")) {
        Write-Fail "这台电脑没有 E: 盘。"
        Write-Host "软件规定 Python 必须安装在 $PythonHome"
        Write-Host "请先准备好 E: 盘（第二块硬盘、U 盘改盘符，或请会电脑的人帮忙），再重新双击 scripts\setup.cmd"
        Write-LogHint
        exit 1
    }
}

function Get-DriveInfo {
    try {
        $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='E:'" -ErrorAction SilentlyContinue
        if (-not $disk) { return $null }
        return @{
            Free = [int64]$disk.FreeSpace
            Size = [int64]$disk.Size
            FileSystem = [string]$disk.FileSystem
            Volume = [string]$disk.VolumeName
        }
    } catch { return $null }
}

function Test-WritableDir([string]$Dir) {
    try {
        if (-not (Test-Path -LiteralPath $Dir)) {
            New-Item -ItemType Directory -Path $Dir -Force | Out-Null
        }
        $probe = Join-Path $Dir ".stock-analyzer-write-test"
        [IO.File]::WriteAllText($probe, "ok")
        Remove-Item -LiteralPath $probe -Force
        return $true
    } catch {
        Write-Warn "无法写入 ${Dir}：$($_.Exception.Message)"
        return $false
    }
}

function Get-PythonProbe([string]$exe) {
    $probe = @{
        Exe = $exe
        Exists = $false
        Length = 0
        Ok = $false
        Version = $null
        Error = $null
        Dll = $null
    }
    if (-not $exe) {
        $probe.Error = "路径为空"
        return $probe
    }
    if ($exe -match "WindowsApps\\python") {
        $probe.Error = "这是 Microsoft Store 占位程序，不能用"
        return $probe
    }
    if (-not (Test-Path -LiteralPath $exe)) {
        $probe.Error = "文件不存在"
        return $probe
    }
    $probe.Exists = $true
    try { $probe.Length = (Get-Item -LiteralPath $exe).Length } catch { }
    if ($probe.Length -lt 20KB) {
        $probe.Error = "文件只有 $([math]::Round($probe.Length / 1KB, 1)) KB，不像完整的 python.exe（多半是上次没装完留下的）"
        return $probe
    }
    $dir = Split-Path -Parent $exe
    foreach ($name in @("python312.dll", "python311.dll")) {
        $dll = Join-Path $dir $name
        if (Test-Path -LiteralPath $dll) {
            $probe.Dll = $name
            break
        }
    }
    if (-not $probe.Dll) {
        $probe.Error = "同目录缺少 python312.dll / python311.dll，不是完整安装。"
        return $probe
    }
    Write-Detail "正在试跑 $exe --version （最多 15 秒，卡住会自动跳过）..."
    try {
        $run = Invoke-Native $exe @("--version") 15
        if ($run.Code -eq -1) {
            $probe.Error = Get-SafeText $run.Text
            return $probe
        }
        if ($run.Code -ne 0 -or -not (Get-SafeText $run.Text)) {
            Write-Detail "改用 -c 再试一次..."
            $run = Invoke-Native $exe @("-c", "import sys; sys.stdout.write('%d.%d' % (sys.version_info.major, sys.version_info.minor))") 15
        }
        if ($run.Code -ne 0 -or -not (Get-SafeText $run.Text)) {
            Write-Detail "改用 cmd 重定向再试一次..."
            $run = Invoke-NativeViaCmd $exe @("--version") 15
        }
        if ($run.Code -ne 0 -or -not (Get-SafeText $run.Text)) {
            $detail = Get-SafeText $run.Text
            if (-not $detail) { $detail = "没有输出。常见原因：安装不完整或被安全软件拦截。" }
            $probe.Error = "退出码 $($run.Code)：$detail"
            return $probe
        }
    } catch {
        $probe.Error = "试跑异常：$($_.Exception.Message)"
        return $probe
    }
    $verText = Get-SafeText $run.Text
    if ($verText -match "(\d+)\.(\d+)") {
        $maj = [int]$Matches[1]
        $min = [int]$Matches[2]
        $probe.Version = "$maj.$min"
        if ($maj -eq 3 -and ($min -eq 11 -or $min -eq 12)) {
            $probe.Ok = $true
        } else {
            $probe.Error = "版本是 $($probe.Version)，本软件只要 3.11 或 3.12"
        }
        return $probe
    }
    $probe.Error = "无法解析版本输出：$($run.Text)"
    return $probe
}

function Test-CPythonVersion([string]$exe) {
    $probe = Get-PythonProbe $exe
    return [bool]$probe.Ok
}

function Test-UnderPythonHome([string]$exe) {
    try {
        $full = [IO.Path]::GetFullPath($exe).TrimEnd("\")
        $home = [IO.Path]::GetFullPath($PythonHome).TrimEnd("\")
        if ($full.Equals($home, [StringComparison]::OrdinalIgnoreCase)) { return $true }
        $prefix = $home + [IO.Path]::DirectorySeparatorChar
        return $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

function Test-ManagedPython([string]$exe) {
    return ((Test-CPythonVersion $exe) -and (Test-UnderPythonHome $exe))
}

function Find-Python {
    $candidates = @(
        (Join-Path $PythonHome "python.exe"),
        (Join-Path $PythonHome "Python312\python.exe"),
        (Join-Path $PythonHome "Python311\python.exe")
    )
    foreach ($p in $candidates) {
        if (-not (Test-Path -LiteralPath $p)) {
            Write-Detail "没有 $p"
            continue
        }
        $probe = Get-PythonProbe $p
        if ($probe.Ok) { return $p }
        Write-Detail "不能用：$($probe.Error)"
    }
    return $null
}

function Get-RegisteredPythonCandidates {
    $list = @()
    $roots = @(
        "HKCU:\Software\Python\PythonCore",
        "HKLM:\Software\Python\PythonCore",
        "HKLM:\Software\Wow6432Node\Python\PythonCore"
    )
    foreach ($rootKey in $roots) {
        if (-not (Test-Path -LiteralPath $rootKey)) { continue }
        Get-ChildItem -LiteralPath $rootKey -ErrorAction SilentlyContinue | ForEach-Object {
            $ip = Join-Path $_.PSPath "InstallPath"
            if (-not (Test-Path -LiteralPath $ip)) { return }
            $prop = Get-ItemProperty -LiteralPath $ip -ErrorAction SilentlyContinue
            if (-not $prop) { return }
            if ($prop.ExecutablePath) { $list += $prop.ExecutablePath }
            $dir = $prop.'(default)'
            if ($dir) {
                if ($dir -match "python\.exe$") { $list += $dir }
                else { $list += (Join-Path $dir "python.exe") }
            }
        }
    }
    return $list
}

function Get-PyLauncherPython {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if (-not $cmd) { return @() }
    if ($cmd.Source -match "WindowsApps") { return @() }
    $found = @()
    foreach ($tag in @("-3.12", "-3.11")) {
        $run = Invoke-Native $cmd.Source @($tag, "-c", "import sys; sys.stdout.write(sys.executable)")
        if ($run.Code -ne 0 -or -not $run.Text) { continue }
        $exe = (Get-SafeText $run.Text).Trim('"')
        if (Test-Path -LiteralPath $exe) { $found += $exe }
    }
    return $found
}

function Get-PathPythonCandidates {
    $found = @()
    $where = Invoke-Native "where.exe" @("python")
    if (-not $where.Text) { return $found }
    foreach ($line in ($where.Text -split "`n")) {
        $p = Get-SafeText $line
        if ($p -and ($p -match "python\.exe$")) { $found += $p }
    }
    return $found
}

function Get-MisplacedPythonCandidates {
    $list = @()
    $roots = @(
        (Join-Path $env:LocalAppData "Programs\Python"),
        (Join-Path ${env:ProgramFiles} "Python"),
        ${env:ProgramFiles},
        ${env:ProgramFiles(x86)}
    )
    foreach ($rootDir in $roots) {
        if (-not $rootDir) { continue }
        foreach ($name in @("Python312", "Python311", "Python3.12", "Python3.11")) {
            $list += (Join-Path $rootDir "$name\python.exe")
        }
    }
    $list += (Join-Path ${env:ProgramFiles} "Python312\python.exe")
    $list += (Join-Path ${env:ProgramFiles} "Python311\python.exe")
    $list += Get-RegisteredPythonCandidates
    $list += Get-PyLauncherPython
    $list += Get-PathPythonCandidates
    $unique = @()
    $seen = @{}
    foreach ($p in $list) {
        if (-not $p) { continue }
        try { $full = [IO.Path]::GetFullPath($p) } catch { continue }
        $key = $full.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $unique += $full
    }
    return $unique
}

function Find-MisplacedPython {
    $hits = New-Object System.Collections.Generic.List[object]
    $candidates = @(Get-MisplacedPythonCandidates)
    Write-Info ("正在搜索其它位置的 Python 3.11/3.12（共 {0} 个候选路径）..." -f $candidates.Count)
    foreach ($p in $candidates) {
        if (-not (Test-Path -LiteralPath $p)) { continue }
        if (Test-UnderPythonHome $p) {
            Write-Detail "跳过（已在 ${PythonHome}）：$p"
            continue
        }
        $probe = Get-PythonProbe $p
        if ($probe.Ok) {
            Write-Detail ("可用  {0}  版本 {1}  {2}" -f $p, $probe.Version, $probe.Dll)
            $hits.Add([pscustomobject]@{ Exe = $p; Version = $probe.Version })
        } else {
            Write-Detail ("不可用  {0}  {1}" -f $p, $probe.Error)
        }
    }
    if ($hits.Count -eq 0) { return $null }
    $best = $hits | Where-Object { $_.Version -like "3.12*" } | Select-Object -First 1
    if (-not $best) { $best = $hits[0] }
    return $best.Exe
}

function Write-PythonHomeStatus {
    if (-not (Test-Path -LiteralPath $PythonHome)) {
        Write-Info "目录还不存在：$PythonHome"
        return
    }
    $names = @(Get-ChildItem -LiteralPath $PythonHome -ErrorAction SilentlyContinue | Select-Object -First 12 -ExpandProperty Name)
    if ($names.Count -eq 0) {
        Write-Info "$PythonHome 目前是空文件夹。安装器没有往这里写文件。"
        return
    }
    Write-Info ("$PythonHome 里能看到：{0}" -f ($names -join ", "))
    foreach ($name in @("python.exe", "python312.dll", "python311.dll", "python3.dll", "vcruntime140.dll")) {
        $f = Join-Path $PythonHome $name
        if (Test-Path -LiteralPath $f) {
            $len = (Get-Item -LiteralPath $f).Length
            Write-Detail ("有 {0}  ({1} KB)" -f $name, [math]::Round($len / 1KB, 1))
        } else {
            Write-Detail "缺 $name"
        }
    }
}

function Get-PythonVersion([string]$exe) {
    $probe = Get-PythonProbe $exe
    if ($probe.Version) { return $probe.Version }
    return "?"
}

function Copy-PythonToHome([string]$sourceExe) {
    $srcDir = Split-Path -Parent $sourceExe
    $srcVer = Get-PythonVersion $sourceExe
    Write-Warn "将把系统里已有的 Python 放到 $PythonHome，然后继续配置。"
    Write-Info "来源：$sourceExe"
    Write-Info "版本：$srcVer"
    Write-Info "本软件仍然只认 $PythonHome，不会直接用上面这个路径启动服务。"
    if (Test-UnderPythonHome $sourceExe) {
        Write-Warn "来源已经在 $PythonHome 内，无法用自己覆盖自己。"
        return $false
    }
    if (Test-Path -LiteralPath $PythonHome) {
        $bakName = "python-stock.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
        Write-Info "先把现在的 $PythonHome 改名为 E:\$bakName（避免用不完整的旧文件）"
        try {
            Rename-Item -LiteralPath $PythonHome -NewName $bakName
            Write-Ok "旧目录已改名为 E:\$bakName"
        } catch {
            Write-Warn "改名失败：$($_.Exception.Message)。将尝试直接覆盖。"
        }
    }
    if (-not (Test-Path -LiteralPath $PythonHome)) {
        New-Item -ItemType Directory -Path $PythonHome -Force | Out-Null
    }
    if (-not (Test-WritableDir $PythonHome)) {
        Write-Warn "没有权限写入 $PythonHome。请右键 scripts\setup.cmd → 以管理员身份运行。"
        return $false
    }
    Write-Info "正在复制全部文件，请不要关闭窗口（大约半分钟）。"
    $copied = $false
    $robo = Get-Command robocopy.exe -ErrorAction SilentlyContinue
    if ($robo) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & robocopy.exe $srcDir $PythonHome /E /COPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
        $roboCode = $LASTEXITCODE
        $ErrorActionPreference = $prev
        Write-Detail "robocopy 退出码 $roboCode（0～7 都表示复制过程可用）"
        if ($roboCode -le 7) { $copied = $true }
    }
    if (-not $copied) {
        try {
            Copy-Item -Path (Join-Path $srcDir "*") -Destination $PythonHome -Recurse -Force
            $copied = $true
        } catch {
            Write-Warn "复制失败：$($_.Exception.Message)"
            return $false
        }
    }
    $dest = Join-Path $PythonHome "python.exe"
    $probe = Get-PythonProbe $dest
    if ($probe.Ok) {
        Write-Ok "已放到 $dest （版本 $($probe.Version)，$($probe.Dll)）"
        return $true
    }
    Write-Warn "复制结束后仍不能用：$($probe.Error)"
    Write-PythonHomeStatus
    return $false
}

function Test-PythonHomeLooksComplete {
    $exe = Join-Path $PythonHome "python.exe"
    $osPy = Join-Path $PythonHome "Lib\os.py"
    if (-not (Test-Path -LiteralPath $exe)) { return $false }
    if (-not (Test-Path -LiteralPath $osPy)) { return $false }
    try {
        if ((Get-Item -LiteralPath $exe).Length -lt 20KB) { return $false }
    } catch { return $false }
    $dll312 = Join-Path $PythonHome "python312.dll"
    $dll311 = Join-Path $PythonHome "python311.dll"
    return ((Test-Path -LiteralPath $dll312) -or (Test-Path -LiteralPath $dll311))
}

function Write-PythonNotReadyHelp {
    Write-Host "这不等于软件已经能打开网页。创建运行环境、安装依赖都还没做，现在启动服务会失败。"
    Write-Host ""
    Write-PythonHomeStatus
    Write-Host ""
    if (Test-PythonHomeLooksComplete) {
        Write-Host "目录看起来已经是完整的 Python 3.11/3.12，问题出在「试跑 python.exe」。"
        Write-Host "请按顺序试："
        Write-Host "  1. 确认本仓库脚本已更新到最新（git pull），再双击 scripts\run.cmd。"
        Write-Host "  2. 打开资源管理器，双击 $PythonHome\python.exe，看是否弹出报错。"
        Write-Host "  3. 若杀毒软件拦截了 python.exe，请允许后再试。"
        Write-Host "  4. 不要反复跑官方安装器：系统若认为 3.12 已安装，它会 2 秒结束且不重写 $PythonHome。"
        Write-Host "  5. 仍不行：右键 scripts\setup.cmd → 以管理员身份运行。"
    } else {
        Write-Host "请按顺序试："
        Write-Host "  1. 打开文件资源管理器，看 $PythonHome\python.exe 和 python312.dll 是否都在。"
        Write-Host "  2. 再看这个文件在不在："
        Write-Host "       $env:LocalAppData\Programs\Python\Python312\python.exe"
        Write-Host "  3. 打开 Windows「设置 → 应用」，若已有 Python 3.11 或 3.12，可先卸载后再装到 E:\python-stock。"
        Write-Host "  4. 关掉本窗口，右键 scripts\setup.cmd → 以管理员身份运行。"
    }
    Write-LogHint
}

function Install-Python {
    Test-PythonHomeDrive
    if (-not (Test-WritableDir $PythonHome)) {
        Write-Fail "没有权限写入 $PythonHome。"
        Write-Host "请右键 scripts\setup.cmd → 以管理员身份运行。"
        Write-LogHint
        exit 1
    }

    $installer = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
    $reuse = $false
    if (Test-Path -LiteralPath $installer) {
        $existingBytes = (Get-Item -LiteralPath $installer).Length
        $existingMb = [math]::Round($existingBytes / 1MB, 1)
        if ($existingBytes -ge 20MB) {
            Write-Info "发现上次已下载的安装包（$existingMb MB），跳过重复下载"
            Write-Detail $installer
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
        $prevCurl = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & curl.exe -fL --retry 3 --retry-delay 2 --progress-bar --stderr - -o $installer $InstallerUrl
        $curlCode = $LASTEXITCODE
        $ErrorActionPreference = $prevCurl
        if ($curlCode -ne 0 -or -not (Test-Path -LiteralPath $installer)) {
            Write-Fail "下载 Python 失败（curl 退出码 $curlCode）。"
            Write-Host "请检查网络后，再双击 scripts\setup.cmd"
            Write-Host "也可以自己安装 Python 3.11 或 3.12 到 $PythonHome"
            Write-Host "官方安装包: $InstallerUrl"
            Write-LogHint
            exit 1
        }
        $mb = [math]::Round((Get-Item -LiteralPath $installer).Length / 1MB, 1)
        Write-Ok "下载完成，文件大小 $mb MB"
    }

    Write-Info "正在安装到 $PythonHome"
    Write-Info "会弹出一个带进度条的安装窗口，大约 1～3 分钟。请不要关闭那个窗口，也不要关闭本窗口。"
    Write-Info "安装器日志：$InstallerLog"
    $installerArgs = @(
        "/passive",
        "/install",
        "/log", $InstallerLog,
        "InstallAllUsers=0",
        "PrependPath=0",
        "Include_launcher=0",
        "Include_test=0",
        "Include_doc=0",
        "Include_pip=1",
        "TargetDir=$PythonHome",
        "DefaultJustForMeTargetDir=$PythonHome",
        "DefaultCustomTargetDir=$PythonHome"
    )
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $proc = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru
    $sw.Stop()
    $seconds = [int]$sw.Elapsed.TotalSeconds
    if ($null -eq $proc) {
        Write-Fail "无法启动 Python 安装程序。"
        Write-LogHint
        exit 1
    }
    if ($proc.ExitCode -ne 0) {
        Write-Fail "Python 安装程序退出码 $($proc.ExitCode)，用时 $seconds 秒。这才是安装失败。"
        Write-Host "如果是权限问题：右键 scripts\setup.cmd → 以管理员身份运行"
        Write-Host "安装成功后，这里必须出现文件：$PythonHome\python.exe 和 python312.dll"
        Write-LogHint
        exit $proc.ExitCode
    }
    Write-Info ("安装程序已退出（退出码 0，用时 {0} 秒）。退出码 0 只表示安装器跑完了，还要检查文件是否真的在 $PythonHome。" -f $seconds)
    Write-PythonHomeStatus
}

function Resolve-ManagedPython {
    Write-Info "先检查 $PythonHome ..."
    $py = Find-Python
    if ($py) {
        $probe = Get-PythonProbe $py
        Write-Ok "$py 可用（版本 $($probe.Version)，$($probe.Dll)）"
        return $py
    }

    $homeExe = Join-Path $PythonHome "python.exe"
    $homeProbe = Get-PythonProbe $homeExe
    if ($homeProbe.Exists -and -not $homeProbe.Ok) {
        Write-Warn "看到了 $homeExe，但不能当 3.11/3.12 用。"
        Write-Info ("文件大小 {0} MB。具体原因：{1}" -f [math]::Round($homeProbe.Length / 1MB, 1), $homeProbe.Error)
        Write-Info "这通常是上次安装没写完整，并不代表这台电脑没有 Python 3.12。"
        Write-PythonHomeStatus
    } elseif (-not $homeProbe.Exists) {
        Write-Info "$homeExe 还不存在。"
    }

    $misplaced = Find-MisplacedPython
    if ($misplaced) {
        Write-Warn "在系统里找到了可用的 Python 3.11/3.12："
        Write-Info $misplaced
        if (Copy-PythonToHome $misplaced) {
            return (Find-Python)
        }
        Write-Warn "复制没有成功，将再试官方安装器。"
    } else {
        Write-Info "用户目录 / 注册表 / PATH 里没有找到另一份能跑的 3.11/3.12。"
    }
    return $null
}

function Test-VenvWorks([string]$exe) {
    $result = @{ Ok = $false; Version = $null; Error = $null }
    if (-not $exe -or -not (Test-Path -LiteralPath $exe)) {
        $result.Error = "文件不存在"
        return $result
    }
    Write-Detail "正在试跑 $exe --version （最多 15 秒）..."
    $run = Invoke-Native $exe @("--version") 15
    if ($run.Code -ne 0 -or -not $run.Text) {
        $result.Error = $(if ($run.Text) { $run.Text } else { "退出码 $($run.Code)" })
        return $result
    }
    if ($run.Text -match "(\d+)\.(\d+)") {
        $maj = [int]$Matches[1]
        $min = [int]$Matches[2]
        $result.Version = "$maj.$min"
        if ($maj -eq 3 -and ($min -eq 11 -or $min -eq 12)) {
            $result.Ok = $true
            return $result
        }
        $result.Error = "版本是 $($result.Version)，本软件只要 3.11 或 3.12"
        return $result
    }
    $result.Error = "无法解析版本：$($run.Text)"
    return $result
}

function Test-VenvDependencies([string]$venvPy) {
    $line = "import fastapi,uvicorn,sqlalchemy,pydantic_settings,httpx,openpyxl,multipart,langgraph,langchain_core,apscheduler,yaml; print('ok')"
    Write-Detail "正在导入运行所需的依赖包（最多 45 秒）..."
    $run = Invoke-Native $venvPy @("-c", $line) 45
    if ($run.Code -eq 0 -and $run.Text -match "ok") {
        return @{ Ok = $true; Error = $null }
    }
    $err = $run.Text
    if (-not $err) { $err = "退出码 $($run.Code)" }
    return @{ Ok = $false; Error = $err }
}

function Test-ReadyEnvironment {
    $state = @{
        Ready = $false
        PythonExe = $null
        PythonVersion = $null
        VenvExe = (Join-Path $root ".venv\Scripts\python.exe")
        VenvVersion = $null
        HasPython = $false
        HasVenv = $false
        HasPip = $false
        HasDeps = $false
        HasEnv = $false
        Failures = New-Object System.Collections.Generic.List[string]
    }
    Write-Info "先做一遍环境检查。若上次已经配置成功，这里会很快结束，不会重新下载或重装。"

    Write-Info "检查 $PythonHome ..."
    $py = Find-Python
    if ($py) {
        $probe = Get-PythonProbe $py
        $state.HasPython = $true
        $state.PythonExe = $py
        $state.PythonVersion = $probe.Version
        Write-Ok "$py 可用（版本 $($probe.Version)）"
    } else {
        $state.Failures.Add("E:\python-stock 没有可用的 Python 3.11/3.12")
        Write-Warn "基础 Python 还不能用。"
    }

    $venv = Test-VenvWorks $state.VenvExe
    if ($venv.Ok) {
        $state.HasVenv = $true
        $state.VenvVersion = $venv.Version
        Write-Ok ".venv 可用（版本 $($venv.Version)）"
    } else {
        $state.Failures.Add(".venv 不能用（$($venv.Error)）")
        Write-Warn ".venv 还不能用：$($venv.Error)"
    }

    if ($state.HasVenv) {
        $pip = Invoke-Native $state.VenvExe @("-m", "pip", "--version") 20
        if ($pip.Code -eq 0 -and $pip.Text) {
            $state.HasPip = $true
            Write-Ok $pip.Text
        } else {
            $state.Failures.Add("pip 不能用")
            Write-Warn "pip 还不能用：$($pip.Text)"
        }
        if ($state.HasPip) {
            $deps = Test-VenvDependencies $state.VenvExe
            if ($deps.Ok) {
                $state.HasDeps = $true
                Write-Ok "运行依赖可以导入（FastAPI / SQLAlchemy / LangGraph 等）"
            } else {
                $state.Failures.Add("依赖包不完整")
                Write-Warn "依赖检查未通过：$($deps.Error)"
            }
        }
    }

    $req = Join-Path $root "requirements.txt"
    if (-not (Test-Path -LiteralPath $req)) {
        $state.Failures.Add("缺少 requirements.txt")
        Write-Warn "找不到 requirements.txt，软件文件不完整。"
    }
    $envFile = Join-Path $root ".env"
    if (Test-Path -LiteralPath $envFile) {
        $state.HasEnv = $true
        Write-Ok ".env 存在"
    } else {
        $state.Failures.Add("缺少 .env")
        Write-Warn ".env 还不存在。"
    }

    $state.Ready = ($state.Failures.Count -eq 0)
    return $state
}

function Write-SetupSuccess([bool]$CheckOnly) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    if ($CheckOnly) {
        Write-Host "  环境检查通过" -ForegroundColor Green
    } else {
        Write-Host "  配置成功" -ForegroundColor Green
    }
    Write-Host "========================================" -ForegroundColor Green
    if ($CheckOnly) {
        Write-Host "上次已经配置好，本次没有重新下载 Python，也没有重装依赖。"
    }
    if ($env:STOCK_ANALYZER_NESTED_SETUP -eq "1" -or $env:STOCK_ANALYZER_FROM_RUN -eq "1") {
        Write-Host "接下来会自动启动服务，请继续等待。"
    } else {
        Write-Host "下一步（请按顺序做）："
        Write-Host "  1. 读完后关掉本窗口"
        Write-Host "  2. 双击  scripts\run.cmd  启动软件（会先检查环境再开服务）"
        Write-Host "  3. 打开浏览器，在地址栏输入（不要去搜索）："
        Write-Host "       http://127.0.0.1:8765" -ForegroundColor Yellow
        Write-Host "  4. 登录账号: hanish"
        Write-Host "     登录密码: change-me"
    }
    Write-Host ""
    Write-Host "结束时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-LogHint
}

function Invoke-Pip([string[]]$PipArgs, [int]$Tries = 3) {
    $venvPy = Join-Path $root ".venv\Scripts\python.exe"
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        for ($i = 1; $i -le $Tries; $i++) {
            Write-Info ("pip 第 {0}/{1} 次：{2}" -f $i, $Tries, ($PipArgs -join " "))
            & $venvPy -m pip @PipArgs
            $code = $LASTEXITCODE
            if ($code -eq 0) { return $true }
            Write-Warn "pip 失败，退出码 $code"
            if ($i -lt $Tries) {
                Write-Info "2 秒后重试..."
                Start-Sleep -Seconds 2
            }
        }
        return $false
    } finally {
        $ErrorActionPreference = $prev
    }
}

Start-SetupLog

$script:ExitCode = 0
try {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Stock-Analyzer 环境检查 / 配置" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "请不要关闭本窗口。全部完成后会告诉你下一步怎么做。"
    Write-Host "工作目录: $root"
    Write-Host "开始时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "系统: $([Environment]::OSVersion.VersionString)　用户: $env:USERNAME　PowerShell: $($PSVersionTable.PSVersion)"
    if ($script:RunLog) { Write-Host "本轮日志: $script:RunLog" }
    Write-Host "将先检查现有环境；缺什么再补什么。"

    Write-Step "[1/6] 检查是否有 E: 盘"
    Test-PythonHomeDrive
    $drive = Get-DriveInfo
    if ($drive) {
        $freeGb = [math]::Round($drive.Free / 1GB, 2)
        $sizeGb = [math]::Round($drive.Size / 1GB, 2)
        Write-Info ("E: 卷标「{0}」文件系统 {1}，总容量 {2} GB，剩余 {3} GB" -f $drive.Volume, $drive.FileSystem, $sizeGb, $freeGb)
        if ($drive.Free -lt 500MB) {
            Write-Fail "E: 盘剩余空间不足 500 MB，装不下 Python 和依赖。"
            Write-Host "请先清理 E: 盘后再双击 scripts\setup.cmd"
            Write-LogHint
            exit 1
        }
    } else {
        Write-Info "已找到 E: 盘（未能读取容量信息，将继续尝试）。"
    }
    if (-not (Test-WritableDir $PythonHome)) {
        Write-Fail "没有权限在 $PythonHome 创建或写入文件。"
        Write-Host "请右键 scripts\setup.cmd → 以管理员身份运行。"
        Write-LogHint
        exit 1
    }
    Write-StepDone "E: 盘可用，Python 将安装/使用 $PythonHome"

    Write-Step "[2/6] 环境检查"
    $state = Test-ReadyEnvironment
    $force = ($env:STOCK_ANALYZER_FORCE_SETUP -eq "1")
    if ($state.Ready -and -not $force) {
        Write-StepDone "环境已就绪"
        Write-SetupSuccess $true
        return
    }
    if ($force) {
        Write-Warn "已设置 STOCK_ANALYZER_FORCE_SETUP=1，将按首次配置再跑一遍。"
    } elseif ($state.Failures.Count -gt 0) {
        Write-Warn "环境未就绪，将只补缺的部分："
        foreach ($item in $state.Failures) { Write-Info "- $item" }
    }

    $py = $state.PythonExe
    $venvPy = $state.VenvExe

    Write-Step "[3/6] 准备 Python 3.11/3.12"
    if ($state.HasPython -and -not $force) {
        Write-Ok "已有可用的 $py （版本 $($state.PythonVersion)），跳过安装"
    } else {
        Write-Info "运行时只认 $PythonHome 下的 3.11 / 3.12。"
        Write-Info "若安装器把它装到了用户目录，或 E:\ 里是一份不能用的残留，会尝试用系统里已有的 3.12 覆盖过去。"
        $py = Resolve-ManagedPython
        if (-not $py) {
            if (Test-PythonHomeLooksComplete) {
                Write-Warn "$PythonHome 看起来已经是完整安装（有 python.exe、python3xx.dll 和 Lib），但试跑仍失败。"
                Write-Info "不会再跑官方安装器。系统若认为 Python 3.12 已经装过，安装器会 2 秒结束并且不重写文件。"
            } else {
                Write-Warn "还没有可用的 Python，将自动下载并安装 3.12.10（需要联网）"
                Install-Python
                Write-Info "正在确认 $PythonHome 里有没有能用的 python.exe ..."
                $py = Resolve-ManagedPython
            }
        }
        if (-not $py) {
            Write-Fail "还不能继续配置：未在 $PythonHome 找到可用的 Python 3.11/3.12。"
            Write-PythonNotReadyHelp
            exit 1
        }
        $state.PythonVersion = Get-PythonVersion $py
        Write-Ok "将使用 $py （版本 $($state.PythonVersion)）"
    }
    Write-StepDone "Python 就绪"

    Write-Step "[4/6] 准备本软件运行环境（.venv）"
    if ($state.HasVenv -and -not $force) {
        Write-Ok ".venv 已可用（版本 $($state.VenvVersion)），跳过创建"
    } else {
        if (Test-Path -LiteralPath $venvPy) {
            $venvProbe = Test-VenvWorks $venvPy
            if (-not $venvProbe.Ok) {
                Write-Warn ".venv 在，但是坏的：$($venvProbe.Error)"
                Write-Info "将删除后重建。请不要关闭窗口。"
                try {
                    Remove-Item -LiteralPath (Join-Path $root ".venv") -Recurse -Force
                } catch {
                    Write-Fail "无法删除损坏的 .venv：$($_.Exception.Message)"
                    Write-Host "请关掉其它黑色窗口后再试。"
                    Write-LogHint
                    exit 1
                }
            }
        }
        if (-not (Test-Path -LiteralPath $venvPy)) {
            Write-Info "第一次创建大约需要半分钟到一分钟，请稍候"
            $prevVenv = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            & $py -m venv .venv
            $venvCode = $LASTEXITCODE
            $ErrorActionPreference = $prevVenv
            if ($venvCode -ne 0 -or -not (Test-Path -LiteralPath $venvPy)) {
                Write-Fail "创建 .venv 失败（退出码 $venvCode）。"
                Write-Host "请把本窗口完整内容发给工作人员。"
                Write-LogHint
                exit 1
            }
        }
        $venvProbe = Test-VenvWorks $venvPy
        if (-not $venvProbe.Ok) {
            Write-Fail ".venv 不能运行：$($venvProbe.Error)"
            Write-LogHint
            exit 1
        }
        Write-Ok ".venv 就绪（版本 $($venvProbe.Version)）"
    }
    Write-StepDone "运行环境就绪"

    Write-Step "[5/6] 检查并安装依赖包"
    $needPip = $force -or -not $state.HasPip -or -not $state.HasDeps
    if (-not $needPip) {
        Write-Ok "依赖已经可以导入，跳过 pip install"
    } else {
        if (-not $state.HasPip -or $force) {
            Write-Info "下面会刷一些英文进度，属于正常现象"
            if (-not (Invoke-Pip @("install", "-U", "pip"))) {
                $pipVer = Invoke-Native $venvPy @("-m", "pip", "--version")
                if ($pipVer.Code -eq 0) {
                    Write-Warn "升级 pip 失败，但现有 pip 还能用，将继续装依赖。"
                    Write-Detail $pipVer.Text
                } else {
                    Write-Fail "pip 不能用。请检查网络后重试。"
                    Write-LogHint
                    exit 1
                }
            }
        }
        if (-not (Test-Path -LiteralPath (Join-Path $root "requirements.txt"))) {
            Write-Fail "找不到 requirements.txt，软件文件不完整。"
            Write-LogHint
            exit 1
        }
        Write-Info "可能需要几分钟。已装过的包会很快跳过；请不要关闭窗口"
        if (-not (Invoke-Pip @("install", "-r", "requirements.txt"))) {
            Write-Fail "安装依赖失败。请检查网络后，再双击 scripts\setup.cmd"
            Write-LogHint
            exit 1
        }
        $deps = Test-VenvDependencies $venvPy
        if (-not $deps.Ok) {
            Write-Fail "依赖装完后仍无法导入：$($deps.Error)"
            Write-LogHint
            exit 1
        }
        Write-Ok "依赖包已就绪"
    }
    Write-StepDone "依赖检查结束"

    Write-Step "[6/6] 检查配置文件 .env"
    $envFile = Join-Path $root ".env"
    $example = Join-Path $root ".env.example"
    if ($state.HasEnv -and -not $force) {
        Write-Ok ".env 已存在，未改动"
    } else {
        if (-not (Test-Path -LiteralPath $envFile)) {
            if (-not (Test-Path -LiteralPath $example)) {
                Write-Fail "找不到 .env.example，软件文件不完整。"
                Write-LogHint
                exit 1
            }
            Copy-Item -LiteralPath $example -Destination $envFile
            Write-Ok "已从模板复制 .env（模板默认 MAIRUI_OFFLINE=0；要纯样例模式请改为 1）"
            Write-Info "以后若有正式行情授权或 AI 密钥，再请工作人员帮你改 .env"
        } else {
            Write-Ok ".env 已存在，未改动"
        }
    }
    Write-StepDone "配置文件就绪"

    Write-SetupSuccess $false
} catch {
    $script:ExitCode = 1
    Write-Fail "配置遇到未处理的错误。"
    Write-Host $_.Exception.Message
    if ($_.ScriptStackTrace) { Write-Host $_.ScriptStackTrace }
    Write-Host "请把本窗口全文发给工作人员。"
    Write-LogHint
} finally {
    if ($script:OwnTranscript) {
        try { Stop-Transcript | Out-Null } catch { }
    }
}
if ($script:ExitCode -ne 0) { exit $script:ExitCode }
