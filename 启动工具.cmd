@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "release\6.5.0\VTStudioToolbox\VTStudioToolbox.exe" (
  start "" "release\6.5.0\VTStudioToolbox\VTStudioToolbox.exe"
  exit /b
)
if exist "release\6.4.0\VTStudioToolbox\VTStudioToolbox.exe" (
  start "" "release\6.4.0\VTStudioToolbox\VTStudioToolbox.exe"
  exit /b
)
if exist "release\VTStudioToolbox\VTStudioToolbox.exe" (
  start "" "release\VTStudioToolbox\VTStudioToolbox.exe"
  exit /b
)
where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw app.py
  exit /b
)
echo 未找到便携程序或 Python。请使用完整便携版，或按 README 安装依赖。
pause
