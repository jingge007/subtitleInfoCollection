﻿param(
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

$pyinstallerArgs = @(
  "--noconfirm",
  "--name", "字幕采集工具",
  "--windowed",
  "--collect-all", "PySide6",
  "--collect-all", "playwright",
  "--add-data", ".env.example;."
)

if (Test-Path ".env") {
  Write-Host "检测到项目 .env 文件，将自动复制到打包目录。"
  $pyinstallerArgs += "--add-data"
  $pyinstallerArgs += ".env;."
}

& ".\.venv\Scripts\pyinstaller.exe" @pyinstallerArgs "src\subtitle_info_collection\main.py"

Write-Host "打包完成：$Root\dist\字幕采集工具"
