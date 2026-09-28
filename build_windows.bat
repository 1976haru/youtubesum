@echo off
setlocal
cd /d "%~dp0"
echo [1/4] Installing pinned build dependencies for Python 3.10...
py -3.10 -m pip install -r requirements-build.txt
echo [2/4] Cleaning old build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo [3/4] Building Windows EXE...
py -3.10 -m PyInstaller --noconfirm --clean YouTubeDynamicThumbnailStudio.spec
if errorlevel 1 goto :fail
echo [4/4] Done.
echo EXE: %CD%\dist\YouTubeDynamicThumbnailStudio.exe
pause
exit /b 0
:fail
echo BUILD FAILED. Review the messages above.
pause
exit /b 1
