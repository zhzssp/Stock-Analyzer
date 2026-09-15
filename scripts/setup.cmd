@echo off
setlocal
cd /d "%~dp0.."
chcp 65001 >nul
title Stock-Analyzer setup
echo.
echo Starting setup. Please wait and do not close this window.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" (
  echo Setup did not finish. Please read the messages above.
) else (
  echo You can close this window after reading the next-step hints above.
)
pause
exit /b %ERR%
