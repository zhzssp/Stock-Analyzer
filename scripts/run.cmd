@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
chcp 65001 >nul
title Stock-Analyzer
echo.
echo ========================================
echo   Stock-Analyzer
echo ========================================
echo Do not close this window.
echo Checking environment, then starting the server.
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
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" (
  echo [ERROR] Exit code %ERR%. Scroll up for the Chinese messages.
  echo Log files are under data\logs
) else (
  echo Server stopped. You can close this window.
)
echo.
pause
exit /b %ERR%
