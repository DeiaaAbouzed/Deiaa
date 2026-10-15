# Try رُشد on this Windows computer only (http://localhost:8000).
# Requires Python 3.11+ from https://www.python.org (tick "Add python.exe to PATH").
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -q --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -q -r backend\requirements.txt
if (-not $env:RUSHD_COOKIE_SECURE) { $env:RUSHD_COOKIE_SECURE = "false" }
Set-Location backend
& ..\.venv\Scripts\python.exe -m rushd init
Write-Host "Open http://localhost:8000 in your browser"
& ..\.venv\Scripts\python.exe -m rushd serve --host 127.0.0.1 --port 8000
