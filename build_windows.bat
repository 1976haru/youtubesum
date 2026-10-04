@echo off
setlocal
cd /d "%~dp0"
echo [1/5] Preparing pinned LGPL FFmpeg bundle (build-time download only)...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_ffmpeg.ps1
if errorlevel 1 goto :fail
echo [2/5] Installing pinned build dependencies for Python 3.10...
py -3.10 -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail
echo [3/5] Cleaning old build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo [4/5] Building Windows EXE...
py -3.10 -m PyInstaller --noconfirm --clean YouTubeDynamicThumbnailStudio.spec
if errorlevel 1 goto :fail
echo [5/5] Done.
echo EXE: %CD%\dist\YouTubeDynamicThumbnailStudio.exe
pause
exit /b 0
:fail
echo BUILD FAILED. Review the messages above.
pause
exit /b 1
