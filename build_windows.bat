@echo off
setlocal
cd /d "%~dp0"
echo [1/4] Installing build dependencies...
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
py -m pip install pyinstaller
echo [2/4] Cleaning old build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo [3/4] Building Windows EXE...
pyinstaller --noconfirm --clean --onefile --windowed --name YouTubeDynamicThumbnailStudio --collect-all cv2 --collect-all PIL app.py
if errorlevel 1 goto :fail
echo [4/4] Done.
echo EXE: %CD%\dist\YouTubeDynamicThumbnailStudio.exe
pause
exit /b 0
:fail
echo BUILD FAILED. Review the messages above.
pause
exit /b 1
