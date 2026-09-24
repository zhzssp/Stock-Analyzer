@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
chcp 65001 >nul
title Stock-Analyzer [OFFLINE TEST]
echo.
echo ========================================
echo   Stock-Analyzer  [OFFLINE / TEST ONLY]
echo ========================================
echo Do not close this window.
echo TEST launcher: forces built-in sample data.
echo It does NOT call the live data vendor and does NOT spend licence quota.
echo Normal users: close this and double-click run.cmd instead.
echo Chinese messages will appear below.
echo.

where powershell >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Windows PowerShell not found.
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0run.ps1" (
  echo [ERROR] Missing scripts\run.ps1
  echo.
  pause
  exit /b 1
)

echo Starting run.ps1 with MAIRUI_OFFLINE=1 ...
echo.
REM KEEP_WINDOW: PowerShell waits for a key after stop so Explorer's
REM `cmd /c` window does not vanish. This file MUST end with the
REM powershell line -- any pause/exit after it makes cmd.exe show
REM "Terminate batch job (Y/N)?" on Ctrl+C and often swallows keyboard input.
set STOCK_ANALYZER_KEEP_WINDOW=1
set MAIRUI_OFFLINE=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
