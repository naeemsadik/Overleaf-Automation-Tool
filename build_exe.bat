@echo off
echo.
echo ===========================================
echo   Overleaf Automation Tool - EXE Builder
echo ===========================================
echo.

echo [0/3] Closing running instances...
taskkill /F /IM "Overleaf Automation.exe" /T 2>nul

echo [1/3] Installing dependencies...
python -m pip install -r requirements.txt

echo.
echo [2/3] Building standalone EXE (this may take a minute)...
python -m PyInstaller --onefile --noconsole ^
    --collect-all selenium ^
    --add-data "logo.png;." ^
    --add-data "ccl pd.jpeg;." ^
    --icon="logo.ico" ^
    --name "LeafPilot" main.py

echo.
echo [3/3] Done!
echo.
echo Your executable is located in the "dist" folder.
echo You can share "Overleaf Automation.exe" with others.
echo.
pause
