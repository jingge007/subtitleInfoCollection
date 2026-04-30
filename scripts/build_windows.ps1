param(
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (!(Test-Path ".venv")) {
  & $Python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -e ".[dev]"
& ".\.venv\Scripts\python.exe" -m playwright install chromium
& ".\.venv\Scripts\pyinstaller.exe" `
  --noconfirm `
  --name subtitleInfoCollection `
  --windowed `
  --collect-all PySide6 `
  --collect-all playwright `
  --add-data ".env.example;." `
  "src\subtitle_info_collection\main.py"

Write-Host "打包完成：$Root\dist\subtitleInfoCollection"
