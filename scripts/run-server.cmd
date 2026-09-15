@echo off
setlocal
cd /d "%~dp0.."
chcp 65001 >nul
title Stock-Analyzer
echo.
echo Starting Stock-Analyzer. Please wait and do not close this window.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-server.ps1"
set ERR=%ERRORLEVEL%
echo.
echo Server has stopped. Press any key to close this window.
pause
exit /b %ERR%
