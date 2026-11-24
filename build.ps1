# EnvMonitor ワンコマンドビルド.
#   .\build.ps1              # exe をビルドし、dist に配布用ファイルを揃える
#   .\build.ps1 -NoSamples   # サンプル config/sensors を dist にコピーしない
#
# 事前準備（別環境での初回のみ）:
#   python -m venv C:\Users\<you>\envmon-venv   # OneDrive 配下を避ける
#   C:\Users\<you>\envmon-venv\Scripts\python.exe -m pip install -r requirements.txt
param([switch]$NoSamples)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# venv の python を自動検出（なければ PATH の python）
$py = Get-ChildItem -ErrorAction SilentlyContinue `
    "C:\Users\$env:USERNAME\envmon-venv\Scripts\python.exe",
    "$root\.venv\Scripts\python.exe" | Select-Object -First 1
$python = if ($py) { $py.FullName } else { "python" }
Write-Host "Using python: $python"

& $python -m PyInstaller build\envmon.spec --distpath dist --workpath build\_work --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller のビルドに失敗しました" }

if (-not $NoSamples) {
    # 配布用の starter ファイルを dist に用意（ポータブル動作用）。
    # 既存の dist\config.json は上書きしない（運用中の設定を壊さないため）。
    if (-not (Test-Path "dist\config.json"))  { Copy-Item "packaging\config.sample.json"  "dist\config.json" }
    if (-not (Test-Path "dist\sensors.json")) { Copy-Item "packaging\sensors.sample.json" "dist\sensors.json" }
    Copy-Item "packaging\README-配布.txt" "dist\README-配布.txt" -Force
    Copy-Item "packaging\config.sample.json"  "dist\config.sample.json"  -Force
    Copy-Item "packaging\sensors.sample.json" "dist\sensors.sample.json" -Force
}

Write-Host "`nビルド完了: dist\EnvMonitor.exe"
Get-ChildItem dist | Select-Object Name, Length | Format-Table -AutoSize
