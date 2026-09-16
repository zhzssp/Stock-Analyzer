@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
chcp 65001 >nul
title Stock-Analyzer setup
echo.
echo ========================================
echo   Stock-Analyzer 配置
echo ========================================
echo 请不要关闭本窗口。全部完成后会告诉你下一步。
echo.

where powershell >nul 2>&1
if errorlevel 1 (
  echo [失败] 找不到 Windows PowerShell。
  echo 请把本窗口发给工作人员。
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0setup.ps1" (
  echo [失败] 找不到 scripts\setup.ps1，软件文件不完整。
  echo.
  pause
  exit /b 1
)

echo 正在启动配置脚本 setup.ps1 ...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" (
  echo [失败] 配置没有完成，退出码 %ERR%。
  echo 请向上滚动阅读中文说明，不要只看这一行。
  echo 完整日志一般在 data\logs\ 目录。
) else (
  echo 配置脚本已结束。若上面显示「配置成功」，就可以关掉本窗口。
)
echo.
pause
exit /b %ERR%
