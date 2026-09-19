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

# Ctrl+C used to interrupt PowerShell mid-taskkill; cmd.exe then asked
# "Terminate batch job (Y/N)?" while Quick Edit / a dying child still owned
# stdin, so the user could not type Y. Closing the window never ran finally.
# Native ctrl handler + job object KILL_ON_JOB_CLOSE cover both paths.
$saRunHostSrc = @"
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

public static class SaRunHost {
    public const uint CTRL_C = 0;
    public const uint CTRL_BREAK = 1;
    public const uint CTRL_CLOSE = 2;
    public const uint CTRL_LOGOFF = 5;
    public const uint CTRL_SHUTDOWN = 6;
    public const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;
    public const int JobObjectExtendedLimitInformation = 9;
    public const uint ENABLE_QUICK_EDIT = 0x0040;
    public const uint ENABLE_EXTENDED_FLAGS = 0x0080;
    public const int STD_INPUT_HANDLE = -10;
    public const uint PROCESS_ALL_ACCESS = 0x001F0FFF;

    public static volatile bool StopRequested;
    public static volatile bool Closing;
    public static int ChildPid;
    public static string PidPath;
    public static uint SavedConsoleMode;
    public static bool HaveSavedConsoleMode;
    public static HandlerRoutine HandlerRef;

    public delegate bool HandlerRoutine(uint ctrlType);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetConsoleCtrlHandler(HandlerRoutine handler, bool add);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetInformationJobObject(IntPtr hJob, int jobObjectInfoClass, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, int dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr hObject);

    [StructLayout(LayoutKind.Sequential)]
    public struct IO_COUNTERS {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    public static bool OnCtrl(uint ctrlType) {
        if (ctrlType == CTRL_C || ctrlType == CTRL_BREAK) {
            StopRequested = true;
            return true;
        }
        if (ctrlType == CTRL_CLOSE || ctrlType == CTRL_LOGOFF || ctrlType == CTRL_SHUTDOWN) {
            Closing = true;
            StopRequested = true;
            KillChild();
            return true;
        }
        return false;
    }

    public static void Register() {
        if (HandlerRef != null) return;
        HandlerRef = new HandlerRoutine(OnCtrl);
        SetConsoleCtrlHandler(HandlerRef, true);
    }

    public static void RequestStop() {
        StopRequested = true;
    }

    public static void DisableQuickEdit() {
        IntPtr h = GetStdHandle(STD_INPUT_HANDLE);
        uint mode;
        if (h == IntPtr.Zero || h == new IntPtr(-1)) return;
        if (!GetConsoleMode(h, out mode)) return;
        if (!HaveSavedConsoleMode) {
            SavedConsoleMode = mode;
            HaveSavedConsoleMode = true;
        }
        uint next = (mode | ENABLE_EXTENDED_FLAGS) & ~ENABLE_QUICK_EDIT;
        SetConsoleMode(h, next);
    }

    public static void RestoreConsoleMode() {
        if (!HaveSavedConsoleMode) return;
        IntPtr h = GetStdHandle(STD_INPUT_HANDLE);
        if (h == IntPtr.Zero || h == new IntPtr(-1)) return;
        SetConsoleMode(h, SavedConsoleMode);
    }

    public static IntPtr CreateKillOnCloseJob() {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) return IntPtr.Zero;
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        int length = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
        IntPtr ptr = Marshal.AllocHGlobal(length);
        try {
            Marshal.StructureToPtr(info, ptr, false);
            if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, ptr, (uint)length)) {
                CloseHandle(job);
                return IntPtr.Zero;
            }
        } finally {
            Marshal.FreeHGlobal(ptr);
        }
        return job;
    }

    public static bool AssignPidToJob(IntPtr job, int pid) {
        if (job == IntPtr.Zero || pid <= 0) return false;
        IntPtr h = OpenProcess(PROCESS_ALL_ACCESS, false, pid);
        if (h == IntPtr.Zero) return false;
        try {
            return AssignProcessToJobObject(job, h);
        } finally {
            CloseHandle(h);
        }
    }

    public static void CloseJob(IntPtr job) {
        if (job == IntPtr.Zero) return;
        try { CloseHandle(job); } catch { }
    }

    public static void KillChild() {
        int pid = ChildPid;
        if (pid > 0) {
            try {
                string rootDir = Environment.GetEnvironmentVariable("SystemRoot");
                if (string.IsNullOrEmpty(rootDir)) rootDir = "C:\\Windows";
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = Path.Combine(rootDir, "System32", "taskkill.exe");
                psi.Arguments = "/PID " + pid.ToString() + " /T /F";
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                Process p = Process.Start(psi);
                if (p != null) p.WaitForExit(3000);
            } catch { }
            try {
                Process proc = Process.GetProcessById(pid);
                if (!proc.HasExited) proc.Kill();
            } catch { }
        }
        try {
            if (!string.IsNullOrEmpty(PidPath) && File.Exists(PidPath)) File.Delete(PidPath);
        } catch { }
    }
}
"@

$script:JobHandle = [IntPtr]::Zero
$script:PidFile = Join-Path $root "data\run\server.pid"
$script:HostReady = $false

function Initialize-SaRunHost {
    if ("SaRunHost" -as [type]) {
        $script:HostReady = $true
    } else {
        try {
            Add-Type -TypeDefinition $saRunHostSrc -Language CSharp -ErrorAction Stop
            $script:HostReady = $true
        } catch {
            Write-Warn "无法注册控制台关闭处理：$($_.Exception.Message)"
            Write-Warn "关掉窗口时可能留下 python 进程；下次启动会再清理。"
            $script:HostReady = $false
        }
    }
    if (-not $script:HostReady) { return }
    [SaRunHost]::PidPath = $script:PidFile
    [SaRunHost]::Register()
    [SaRunHost]::DisableQuickEdit()
    try {
        [Console]::TreatControlCAsInput = $false
        [Console]::add_CancelKeyPress({
            param($sender, $e)
            $e.Cancel = $true
            [SaRunHost]::RequestStop()
        })
    } catch { }
    try {
        Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
            try { [SaRunHost]::KillChild() } catch { }
        } | Out-Null
    } catch { }
}

function Test-SaStopRequested {
    if (-not $script:HostReady) { return $false }
    return [bool][SaRunHost]::StopRequested
}

function Test-ControlCExitCode($Value) {
    if ($null -eq $Value) { return $false }
    try {
        $n = [int]$Value
    } catch {
        return $false
    }
    return ($n -eq -1073741510 -or $n -eq 3221225786)
}

function Wait-KeepWindow {
    if ($env:STOCK_ANALYZER_KEEP_WINDOW -ne "1") { return }
    if ($script:HostReady -and [SaRunHost]::Closing) { return }
    Write-Host ""
    Write-Host "按任意键关闭本窗口..."
    try {
        if ($script:HostReady) { [SaRunHost]::RestoreConsoleMode() }
        while ([Console]::KeyAvailable) { $null = [Console]::ReadKey($true) }
        $null = [Console]::ReadKey($true)
    } catch {
        Start-Sleep -Seconds 6
    }
}

function Clear-PidFile {
    if ($script:PidFile -and (Test-Path -LiteralPath $script:PidFile)) {
        try { Remove-Item -LiteralPath $script:PidFile -Force -ErrorAction SilentlyContinue } catch { }
    }
}

function Stop-ProcessTree([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
    $ErrorActionPreference = $prev
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
    Write-Detail "正在试跑 $exe --version （最多 15 秒）..."
    $run = Invoke-Native $exe @("--version")
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
    Initialize-SaRunHost
    Write-Step "[1/4] 检查运行环境"
    $skipSetup = ($env:STOCK_ANALYZER_SKIP_SETUP -eq "1")
    if ($skipSetup -and (Test-VenvPython $venvPy)) {
        Write-Ok "环境已在上一步检查过，跳过重复配置"
    } elseif (-not (Test-VenvPython $venvPy)) {
        if ($skipSetup) {
            Write-Warn "上一步声称环境已好，但 .venv 仍不能用，将再跑一次配置。"
        }
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
    if (Test-Path -LiteralPath $script:PidFile) {
        $oldPidText = Get-SafeText (Get-Content -LiteralPath $script:PidFile -TotalCount 1 -ErrorAction SilentlyContinue)
        if ($oldPidText -match '^\d+$') {
            $oldPid = [int]$oldPidText
            if (Test-OurServerProcess $oldPid) {
                Write-Warn "发现上次未关闭的服务 PID $oldPid（来自 pid 文件），正在结束"
                Stop-ProcessTree $oldPid
            }
        }
        Clear-PidFile
    }
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
    try {
        $runDir = Split-Path -Parent $script:PidFile
        New-Item -ItemType Directory -Path $runDir -Force | Out-Null
        Set-Content -LiteralPath $script:PidFile -Value ([string]$proc.Id) -Encoding ASCII
    } catch { }
    if ($script:HostReady) {
        [SaRunHost]::ChildPid = [int]$proc.Id
        [SaRunHost]::PidPath = $script:PidFile
        $script:JobHandle = [SaRunHost]::CreateKillOnCloseJob()
        if ($script:JobHandle -eq [IntPtr]::Zero) {
            Write-Warn "未能创建作业对象；直接关掉窗口时，下次启动会再清理残留进程"
        } elseif (-not [SaRunHost]::AssignPidToJob($script:JobHandle, [int]$proc.Id)) {
            Write-Warn "未能把服务进程加入作业对象；关掉窗口时将改用强制结束"
        }
    }
    Write-Info "正在等待端口 $port 就绪（首次启动可能要几十秒）..."

    $ready = $false
    $deadline = (Get-Date).AddSeconds(60)
    $lastPing = Get-Date
    $started = Get-Date
    while ($proc -and -not $proc.HasExited -and (Get-Date) -lt $deadline) {
        if (Test-SaStopRequested) {
            Write-Info "收到停止请求，正在取消启动..."
            break
        }
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

    if (Test-SaStopRequested) {
        $code = 0
    } elseif ($proc -and $proc.HasExited) {
        $code = $proc.ExitCode
        if (Test-ControlCExitCode $code) {
            $code = 0
        } else {
            Write-Fail "服务进程已退出，退出码 $code"
            Write-Host "请向上滚动，查看红色或英文报错，把完整内容发给工作人员。"
            Write-LogHint
            exit $code
        }
    } else {
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
        Write-Host "  用完后：用鼠标点一下本窗口，按 Ctrl+C 停止（不必回答 Terminate batch job）。"
        Write-Host "  如果直接点窗口右上角关闭，服务进程也会一并结束。"
        Write-Host ""
        Write-LogHint
        Write-Host ""

        while ($proc -and -not $proc.HasExited) {
            if (Test-SaStopRequested) { break }
            Start-Sleep -Milliseconds 300
            $proc.Refresh()
        }
        if ($proc -and $proc.HasExited -and $null -ne $proc.ExitCode) {
            $code = $proc.ExitCode
        }
        if (Test-SaStopRequested -or (Test-ControlCExitCode $code)) {
            $code = 0
        }
    }
} catch {
    $code = 1
    Write-Fail "启动遇到未处理的错误。"
    Write-Host $_.Exception.Message
    if ($_.ScriptStackTrace) { Write-Host $_.ScriptStackTrace }
    Write-Host "请把本窗口全文发给工作人员。"
    Write-LogHint
} finally {
    $closingWindow = $false
    try { if ($script:HostReady) { $closingWindow = [bool][SaRunHost]::Closing } } catch { }
    if ($proc) {
        try { $proc.Refresh() } catch { }
        if (-not $proc.HasExited) {
            if (-not $closingWindow) {
                Write-Host ""
                Write-Warn "正在停止服务 PID $($proc.Id) ..."
            }
            if ($script:HostReady) {
                [SaRunHost]::ChildPid = [int]$proc.Id
                [SaRunHost]::KillChild()
            } elseif ($proc.Id -gt 0) {
                Stop-ProcessTree $proc.Id
            }
            try { $proc.WaitForExit(4000) } catch { }
            if (-not $closingWindow) { Write-Ok "服务已停止" }
        } elseif (-not $closingWindow) {
            Write-Host ""
            Write-Info "服务已结束（退出码 $code）"
        }
    } elseif ($script:HostReady) {
        try { [SaRunHost]::KillChild() } catch { }
    }
    Clear-PidFile
    if ($script:JobHandle -ne [IntPtr]::Zero -and $script:HostReady) {
        try { [SaRunHost]::CloseJob($script:JobHandle) } catch { }
        $script:JobHandle = [IntPtr]::Zero
    }
    try { if ($script:HostReady) { [SaRunHost]::RestoreConsoleMode() } } catch { }
    try { $Host.UI.RawUI.WindowTitle = "Stock-Analyzer 已停止" } catch { }
    try { Stop-Transcript | Out-Null } catch { }
    if (Test-ControlCExitCode $code) { $code = 0 }
    Wait-KeepWindow
}
exit $code
