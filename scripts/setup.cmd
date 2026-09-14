@echo off
setlocal
REM Python 3.11/3.12 must be at E:\python-stock on this machine.
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
exit /b %ERRORLEVEL%
