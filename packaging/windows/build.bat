@echo off
REM ── Windows packaging script for AI Desktop Agent ──────────────────────────
REM Run from the project root: packaging\windows\build.bat

echo [1/4] Installing PyInstaller...
pip install pyinstaller

echo [2/4] Cleaning previous build...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

echo [3/4] Building executable...
pyinstaller ^
  --onefile ^
  --windowed ^
  --name "AI Desktop Agent" ^
  --add-data "config;config" ^
  --add-data "assets;assets" ^
  --hidden-import PySide6.QtCore ^
  --hidden-import PySide6.QtWidgets ^
  --hidden-import PySide6.QtGui ^
  --hidden-import keyring.backends.Windows ^
  --hidden-import pyttsx3.drivers ^
  --hidden-import pyttsx3.drivers.sapi5 ^
  app.py

echo [4/4] Done. Executable is in dist\
echo NOTE: Copy your .env to the same directory as the executable before running.
echo NOTE: Playwright browsers must be installed separately on the target machine.
echo NOTE: Antivirus software may flag PyInstaller executables (known false positive).
pause
