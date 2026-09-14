@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo Virtual env missing. Running one-click setup...
  call "%~dp0setup.cmd"
  if errorlevel 1 exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Setup finished but .venv is still missing.
  echo Close this window and run: scripts\setup.cmd
  exit /b 1
)

if not exist ".env" copy ".env.example" ".env" >nul
".venv\Scripts\python.exe" -m src.main
exit /b %ERRORLEVEL%
