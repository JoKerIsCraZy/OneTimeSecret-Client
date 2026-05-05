@echo off
REM ============================================================
REM  OneTimeSecret Client - Build single-file Windows .exe
REM ============================================================

setlocal

REM 1) Dependencies installieren
python -m pip install --upgrade pip
python -m pip install pyinstaller requests keyring

REM 2) Alte Builds wegraeumen
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist OneTimeSecret-Client.spec del /q OneTimeSecret-Client.spec

REM 3) Single-File-Build, ohne Konsolenfenster
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name OneTimeSecret-Client ^
    --icon assets/onetime.ico ^
    --add-data "assets/onetime.ico;assets" ^
    --hidden-import=keyring.backends.Windows ^
    --hidden-import=win32timezone ^
    OneTimeSecret_Client.py

echo.
echo ============================================================
echo  Build fertig.
echo  Exe: dist\OneTimeSecret-Client.exe
echo ============================================================

endlocal
