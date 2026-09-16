@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
chcp 65001 >nul
title Stock-Analyzer setup
echo.
echo ========================================
echo   Stock-Analyzer setup
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

if not exist "%~dp0setup.ps1" (
  echo [ERROR] Missing scripts\setup.ps1
  echo.
  pause
  exit /b 1
)

echo Starting setup.ps1 ...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" (
  echo [ERROR] Setup exit code %ERR%. Scroll up for the Chinese messages.
  echo Log files are under data\logs
) else (
  echo Setup finished. If you saw success above, you can close this window.
)
echo.
pause
exit /b %ERR%
