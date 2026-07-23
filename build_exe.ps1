$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

Get-Process -Name "LeafPilot", "OverleafAutomationUI", "Overleaf Automation" -ErrorAction SilentlyContinue | Stop-Process -Force

foreach ($path in @(
    (Join-Path $projectRoot "dist"),
    (Join-Path $projectRoot "build")
)) {
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

& $pythonExe -m pip install -r requirements.txt

$requiredAssets = @("logo.ico", "logo.png", "ccl_pd.jpeg", "LeafPilot.spec")
foreach ($asset in $requiredAssets) {
    $fullPath = Join-Path $projectRoot $asset
    if (-not (Test-Path $fullPath)) {
        throw "Required build file not found: $fullPath"
    }
}

& $pythonExe -m PyInstaller --noconfirm --clean LeafPilot.spec

$exePath = Join-Path $projectRoot "dist\LeafPilot.exe"
if (-not (Test-Path $exePath)) {
    throw "Build failed: $exePath was not created."
}

Write-Host "Build complete. EXE: .\dist\LeafPilot.exe"
