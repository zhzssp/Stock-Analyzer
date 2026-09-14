# One-click setup. Runtime Python 3.11/3.12 must live at E:\python-stock on this machine.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$PythonHome = "E:\python-stock"
$InstallerUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"

function Test-PythonHomeDrive {
    if (-not (Test-Path -LiteralPath "E:\")) {
        Write-Host "This machine has no E: drive."
        Write-Host "Python 3.11/3.12 must be installed at $PythonHome."
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

function Install-Python {
    Test-PythonHomeDrive
    if (-not (Test-Path -LiteralPath $PythonHome)) {
        New-Item -ItemType Directory -Path $PythonHome -Force | Out-Null
    }

    $installer = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
    Write-Host "Downloading Python 3.12.10 to $installer ..."
    & curl.exe -fsSL -o $installer $InstallerUrl
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $installer)) {
        Write-Host "Download failed. Check the network, or install Python 3.11/3.12 yourself to $PythonHome"
        Write-Host "Official installer: $InstallerUrl"
        Write-Host "Silent example: installer /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 TargetDir=$PythonHome"
        exit 1
    }

    Write-Host "Installing Python 3.12.10 to $PythonHome ..."
    $args = @(
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
    $proc = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        Write-Host "Installer exited $($proc.ExitCode). If this is a permission error, run scripts\setup.cmd as Administrator."
        Write-Host "Python 3.11/3.12 must end up at $PythonHome\python.exe"
        exit $proc.ExitCode
    }
}

Write-Host "Stock-Analyzer setup"
Write-Host "Working directory: $root"
Write-Host "Required Python home: $PythonHome (3.11 or 3.12 only)"
Test-PythonHomeDrive

$py = Find-Python
if (-not $py) {
    $existing = Join-Path $PythonHome "python.exe"
    if (Test-Path -LiteralPath $existing) {
        Write-Host "Found $existing but it is not Python 3.11 or 3.12."
        Write-Host "Move that install aside, then run scripts\setup.cmd again."
        exit 1
    }
    Install-Python
    $py = Find-Python
}
if (-not $py) {
    Write-Host "Python 3.11/3.12 was not found at $PythonHome after install."
    Write-Host "Confirm E:\python-stock\python.exe exists, then run scripts\setup.cmd again."
    exit 1
}

Write-Host "Using $py"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv ..."
    & $py -m venv .venv
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        Write-Host "venv creation failed."
        exit 1
    }
}

Write-Host "Installing Python packages ..."
& .\.venv\Scripts\python.exe -m pip install -U pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example (offline mode, no licence needed to start)."
    Write-Host "Optional later: MAIRUI_LICENCE, LLM_API_KEY in .env"
} else {
    Write-Host ".env already exists, left unchanged."
}

Write-Host "Setup finished. Start with: .\scripts\run-server.cmd"
Write-Host "Then open http://127.0.0.1:8765  (hanish / change-me)"
