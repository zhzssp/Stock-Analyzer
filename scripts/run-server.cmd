@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
chcp 65001 >nul
title Stock-Analyzer
echo.
echo ========================================
echo   Stock-Analyzer 启动
echo ========================================
echo 请不要关闭本窗口。关掉它，网页就会打不开。
echo.

where powershell >nul 2>&1
if errorlevel 1 (
  echo [失败] 找不到 Windows PowerShell。
  echo 请把本窗口发给工作人员。
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0run-server.ps1" (
  echo [失败] 找不到 scripts\run-server.ps1，软件文件不完整。
  echo.
  pause
  exit /b 1
)

echo 正在启动 run-server.ps1 ...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-server.ps1"
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" (
  echo [失败] 服务没有正常运行，退出码 %ERR%。
  echo 请向上滚动阅读中文说明，不要只看这一行。
  echo 完整日志一般在 data\logs\ 目录。
) else (
  echo 服务已结束。可以关闭本窗口。
)
echo.
pause
exit /b %ERR%
