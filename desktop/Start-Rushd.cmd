@echo off
rem Rushd - runs the app on this computer. Keep this window open while you use Rushd.
title Rushd - keep this window open
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0python\python.exe" -X utf8 -I "%~dp0app\launcher.py" %*
if errorlevel 1 pause
