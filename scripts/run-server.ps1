$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Virtual env missing. Running one-click setup..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "setup.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Setup finished but .venv is still missing. Run scripts\setup.cmd in a new terminal."
    exit 1
}
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}
& .\.venv\Scripts\python.exe -m src.main
