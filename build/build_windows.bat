@echo off
REM ============================================================
REM  MedStatix Pro - Windows build script
REM  Requires: Python 3.11 or 3.12 (64-bit) from python.org
REM  Optional: Inno Setup 6 (https://jrsoftware.org/isinfo.php) for the installer
REM ============================================================
cd /d "%~dp0\.."
echo [1/5] Creating virtual environment...
python -m venv .venv || goto :error
call .venv\Scripts\activate.bat
echo [2/5] Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller pytest || goto :error
echo [3/5] Running validation suite (45 reference checks)...
python -m pytest tests -q || goto :error
echo [4/5] Building executable...
pyinstaller build\medstatix.spec --noconfirm --distpath dist --workpath build\work || goto :error
echo [5/5] Building installer (if Inno Setup is installed)...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% build\installer.iss || goto :error
  echo Installer created in dist\installer\
) else (
  echo Inno Setup not found - portable app is in dist\MedStatixPro\MedStatixPro.exe
)
echo Done.
pause
exit /b 0
:error
echo Build failed.
pause
exit /b 1
