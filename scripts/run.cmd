@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
chcp 65001 >nul

if /i "%~1"=="restart" goto do_restart

title Stock-Analyzer
echo.
echo ========================================
echo   Stock-Analyzer
echo ========================================
echo Do not close this window.
echo Checking environment, then starting the server.
echo In the black window after start: Ctrl+R restarts the service; Ctrl+C stops.
echo You can also double-click scripts\restart.cmd or run: scripts\run.cmd restart
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

echo Starting run.ps1 ...
echo.
REM KEEP_WINDOW: PowerShell waits for a key after stop so Explorer's
REM `cmd /c` window does not vanish. This file MUST end with the
REM powershell line — any pause/exit after it makes cmd.exe show
REM "Terminate batch job (Y/N)?" on Ctrl+C and often swallows keyboard input.
set STOCK_ANALYZER_KEEP_WINDOW=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
exit /b %ERRORLEVEL%

:do_restart
title Stock-Analyzer restart
echo.
echo ========================================
echo   Stock-Analyzer restart
echo ========================================
echo Stopping the old server, then starting again.
echo You can close any other old black window after this.
echo.

where powershell >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Windows PowerShell not found.
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0restart.ps1" (
  echo [ERROR] Missing scripts\restart.ps1
  echo.
  pause
  exit /b 1
)

set STOCK_ANALYZER_KEEP_WINDOW=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart.ps1"
