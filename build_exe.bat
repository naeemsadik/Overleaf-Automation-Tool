@echo off
setlocal
echo.
echo ===========================================
echo   LeafPilot - EXE Builder
echo ===========================================
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1"
if errorlevel 1 (
  echo.
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Your executable is located in the "dist" folder:
echo   dist\LeafPilot.exe
echo.
pause
