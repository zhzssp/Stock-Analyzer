@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
chcp 65001 >nul
title Stock-Analyzer restart
REM 与 run.cmd 相同：窗口末尾只留 powershell 一行，避免 Ctrl+C 后出现 Terminate batch job (Y/N)?
set STOCK_ANALYZER_KEEP_WINDOW=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart.ps1"
