@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
chcp 65001 >nul
title Stock-Analyzer
echo.
echo ========================================
echo   Stock-Analyzer server
echo ========================================
echo Do not close this window.
echo Chinese messages will appear below.
echo.

where powershell >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Windows PowerShell not found.
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0run-server.ps1" (
  echo [ERROR] Missing scripts\run-server.ps1
  echo.
  pause
  exit /b 1
)

echo Starting run-server.ps1 ...
echo.
REM KEEP_WINDOW: PowerShell waits for a key after stop so Explorer's
REM `cmd /c` window does not vanish. This file MUST end with the
REM powershell line — any pause/exit after it makes cmd.exe show
REM "Terminate batch job (Y/N)?" on Ctrl+C and often swallows keyboard input.
set STOCK_ANALYZER_KEEP_WINDOW=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-server.ps1"
