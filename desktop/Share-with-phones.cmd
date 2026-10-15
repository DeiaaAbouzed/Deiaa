@echo off
rem Rushd for the whole pharmacy: phones on the same Wi-Fi can use this computer.
rem If Windows Firewall asks, allow access on private networks.
title Rushd (shared with phones) - keep this window open
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0python\python.exe" -X utf8 -I "%~dp0app\launcher.py" --lan %*
if errorlevel 1 pause
