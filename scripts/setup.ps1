# One-click machine setup: find or install Python 3.11+, create .venv, install deps, copy .env.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Test-RealPython([string]$exe) {
    if (-not $exe) { return $false }
    if ($exe -match "WindowsApps\\python") { return $false }
    if (-not (Test-Path -LiteralPath $exe)) { return $false }
    try {
        $ver = & $exe -c "import sys; print('%d.%d' % (sys.version_info.major, sys.version_info.minor))" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $ver) { return $false }
        $parts = $ver.Trim().Split(".")
        $maj = [int]$parts[0]
        $min = [int]$parts[1]
        return ($maj -gt 3) -or ($maj -eq 3 -and $min -ge 11)
    } catch {
        return $false
    }
}

function Find-Python {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python313\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "${env:ProgramFiles(x86)}\Python313\python.exe",
        "${env:ProgramFiles(x86)}\Python312\python.exe",
        "${env:ProgramFiles(x86)}\Python311\python.exe"
    )
    foreach ($p in $candidates) {
        if (Test-RealPython $p) { return $p }
    }

    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($arg in @("-3.13", "-3.12", "-3.11", "-3")) {
            try {
                $exe = & py $arg -c "import sys; print(sys.executable)" 2>$null
                if ($exe) {
                    $exe = $exe.Trim()
                    if (Test-RealPython $exe) { return $exe }
                }
            } catch {}
        }
    }

    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and (Test-RealPython $cmd.Source)) { return $cmd.Source }
    }
    return $null
}

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Install-Python {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Host "Need Python 3.11+ (3.12 preferred). winget was not found."
        Write-Host "Install from https://www.python.org/downloads/windows/"
        Write-Host "During setup, enable 'Add python.exe to PATH' and the py launcher."
        Write-Host "Then run scripts\setup.cmd again."
        exit 1
    }
    Write-Host "Installing Python 3.12 with winget (may ask for elevation)..."
    & winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity
    Refresh-Path
}

Write-Host "Stock-Analyzer setup"
Write-Host "Working directory: $root"

$py = Find-Python
if (-not $py) {
    Install-Python
    $py = Find-Python
}
if (-not $py) {
    Write-Host "Python may have been installed, but this terminal cannot see it yet."
    Write-Host "Close the window and run: .\scripts\setup.cmd"
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
