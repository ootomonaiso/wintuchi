# EnvMonitor one-command build.
#   .\build.ps1              # build the exe and stage distributable files into dist\
#   .\build.ps1 -NoSamples   # do not copy sample config/sensors into dist\
#
# First-time setup on a new machine:
#   python -m venv C:\Users\<you>\envmon-venv   # avoid OneDrive-synced folders
#   C:\Users\<you>\envmon-venv\Scripts\python.exe -m pip install -r requirements.txt
#
# NOTE: ASCII-only on purpose so Windows PowerShell 5.1 parses it regardless of code page.
param([switch]$NoSamples)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Pick the venv python if present, otherwise fall back to PATH python.
$python = "python"
$venv1 = "C:\Users\$env:USERNAME\envmon-venv\Scripts\python.exe"
$venv2 = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venv1) { $python = $venv1 }
elseif (Test-Path $venv2) { $python = $venv2 }
Write-Host "Using python: $python"

& $python -m PyInstaller build\envmon.spec --distpath dist --workpath build\_work --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

if (-not $NoSamples) {
    # Starter files for portable operation. Do NOT overwrite an existing dist\config.json
    # so a machine's live settings are preserved across rebuilds.
    if (-not (Test-Path "dist\config.json"))  { Copy-Item "packaging\config.sample.json"  "dist\config.json" }
    if (-not (Test-Path "dist\sensors.json")) { Copy-Item "packaging\sensors.sample.json" "dist\sensors.json" }
    Copy-Item "packaging\README-deploy.txt"   "dist\README-deploy.txt"   -Force -ErrorAction SilentlyContinue
    Copy-Item "packaging\config.sample.json"  "dist\config.sample.json"  -Force
    Copy-Item "packaging\sensors.sample.json" "dist\sensors.sample.json" -Force
}

Write-Host "`nBuild complete: dist\EnvMonitor.exe"
Get-ChildItem dist | Select-Object Name, Length | Format-Table -AutoSize
