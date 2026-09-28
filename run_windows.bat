@echo off
cd /d "%~dp0"
if exist "dist\YouTubeDynamicThumbnailStudio.exe" (
  start "" "dist\YouTubeDynamicThumbnailStudio.exe"
  exit /b 0
)
echo EXE not found. Run build_windows.bat first.
pause
