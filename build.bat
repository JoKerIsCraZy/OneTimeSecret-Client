@echo off
REM ============================================================
REM  OneTime - Build single-file Windows .exe via PyInstaller
REM ============================================================

setlocal

REM 1) Dependencies installieren
python -m pip install --upgrade pip
python -m pip install pyinstaller requests keyring

REM 2) Alte Builds wegraeumen
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist OneTime.spec del /q OneTime.spec

REM 3) Single-File-Build, ohne Konsolenfenster
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name OneTime ^
    --hidden-import=keyring.backends.Windows ^
    --hidden-import=win32timezone ^
    OneTime.py

echo.
echo ============================================================
echo  Build fertig.
echo  Exe: dist\OneTime.exe
echo ============================================================

endlocal
