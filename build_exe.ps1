$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

Get-Process -Name "OverleafAutomationUI" -ErrorAction SilentlyContinue | Stop-Process -Force
$existingExe = Join-Path $projectRoot "dist\OverleafAutomationUI.exe"
if (Test-Path $existingExe) {
    Remove-Item $existingExe -Force -ErrorAction SilentlyContinue
}

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install pyinstaller pillow

$iconPath = Join-Path $projectRoot "ccl_pd.jpeg"
if (-not (Test-Path $iconPath)) {
    throw "Icon file not found: $iconPath"
}

& $pythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --collect-all selenium `
    --collect-all webdriver_manager `
    --hidden-import selenium.webdriver.chrome.webdriver `
    --hidden-import selenium.webdriver.chromium.webdriver `
    --add-data "$iconPath;." `
    --icon "$iconPath" `
    --name OverleafAutomationUI `
    main.py

Write-Host "Build complete. EXE: .\dist\OverleafAutomationUI.exe"
