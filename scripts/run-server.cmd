@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv
  ) else (
    py -3.12 -m venv .venv
  )
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if not exist ".env" copy ".env.example" ".env" >nul
".venv\Scripts\python.exe" -m src.main
