param(
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$AppName = "字幕采集工具"
Set-Location $Root

if (!(Test-Path ".venv")) {
  & $Python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -e ".[dev]"
& ".\.venv\Scripts\python.exe" -m playwright install chromium

$configuredDistPath = ""
if (Test-Path ".env") {
  $envText = Get-Content ".env" -Raw -Encoding UTF8
  $distMatch = [regex]::Match(
    $envText,
    "(?m)^\s*SUBTITLE_COLLECTION_PACKAGE_DIST_DIR\s*=\s*(.+?)\s*$"
  )
  if (!$distMatch.Success) {
    $distMatch = [regex]::Match(
      $envText,
      "SUBTITLE_COLLECTION_PACKAGE_DIST_DIR\s*=\s*([^\r\n#]+)"
    )
  }
  if ($distMatch.Success) {
    $configuredDistPath = $distMatch.Groups[1].Value.Trim()
    $configuredDistPath = $configuredDistPath.Trim('"').Trim("'")
  }
}

$resolvedDistPath = Join-Path $Root "dist"
$packageOutputPath = Join-Path $resolvedDistPath $AppName
if (![string]::IsNullOrWhiteSpace($configuredDistPath)) {
  if ([System.IO.Path]::IsPathRooted($configuredDistPath)) {
    $resolvedDistPath = [System.IO.Path]::GetFullPath($configuredDistPath)
  } else {
    $resolvedDistPath = [System.IO.Path]::GetFullPath((Join-Path $Root $configuredDistPath))
  }

  $normalizedConfiguredPath = $resolvedDistPath.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
  if ((Split-Path -Leaf $normalizedConfiguredPath) -eq $AppName) {
    $resolvedDistPath = Split-Path -Parent $normalizedConfiguredPath
    $packageOutputPath = $normalizedConfiguredPath
  } else {
    $packageOutputPath = Join-Path $resolvedDistPath $AppName
  }
}

$pyinstallerArgs = @(
  "--noconfirm",
  "--name", "字幕采集工具",
  "--windowed",
  "--specpath", (Join-Path $Root "build\spec"),
  "--collect-all", "PySide6",
  "--collect-all", "playwright",
  "--add-data", "$Root\.env.example;."
)

if (Test-Path ".env") {
  Write-Host "检测到项目 .env 文件，将自动复制到打包目录。"
  $pyinstallerArgs += "--add-data"
  $pyinstallerArgs += "$Root\.env;."
}

if (![string]::IsNullOrWhiteSpace($configuredDistPath)) {
  Write-Host "检测到自定义打包输出目录：$packageOutputPath"
  $pyinstallerArgs += "--distpath"
  $pyinstallerArgs += $resolvedDistPath
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "build\spec") | Out-Null

& ".\.venv\Scripts\pyinstaller.exe" @pyinstallerArgs "src\subtitle_info_collection\main.py"

Write-Host "打包完成：$packageOutputPath"
