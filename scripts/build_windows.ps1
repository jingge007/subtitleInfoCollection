param(
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$AppName = "字幕采集工具"
Set-Location $Root

function Invoke-CheckedCommand {
  param(
    [Parameter(Mandatory = $true)]
    [string]$CommandPath,
    [string[]]$CommandArguments = @()
  )

  & $CommandPath @CommandArguments
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    throw "命令执行失败（退出码 $exitCode）：$CommandPath $($CommandArguments -join ' ')"
  }
}

function ConvertTo-NormalizedPath {
  param([Parameter(Mandatory = $true)][string]$Path)

  return [System.IO.Path]::GetFullPath($Path).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
}

function Test-PathIsUnderDirectory {
  param(
    [string]$CandidatePath,
    [Parameter(Mandatory = $true)][string]$DirectoryPath
  )

  if ([string]::IsNullOrWhiteSpace($CandidatePath)) {
    return $false
  }

  try {
    $normalizedCandidatePath = ConvertTo-NormalizedPath $CandidatePath
    $normalizedDirectoryPath = ConvertTo-NormalizedPath $DirectoryPath
  } catch {
    return $false
  }

  if (
    $normalizedCandidatePath.Equals(
      $normalizedDirectoryPath,
      [System.StringComparison]::OrdinalIgnoreCase
    )
  ) {
    return $true
  }

  $directoryWithSeparator = "$normalizedDirectoryPath$([System.IO.Path]::DirectorySeparatorChar)"
  return $normalizedCandidatePath.StartsWith(
    $directoryWithSeparator,
    [System.StringComparison]::OrdinalIgnoreCase
  )
}

function Find-ProcessesUsingPackagePath {
  param([Parameter(Mandatory = $true)][string]$PackagePath)

  $normalizedPackagePath = ConvertTo-NormalizedPath $PackagePath
  Get-CimInstance Win32_Process |
    Where-Object {
      $usesExecutablePath = Test-PathIsUnderDirectory `
        -CandidatePath $_.ExecutablePath `
        -DirectoryPath $normalizedPackagePath
      $usesCommandLine = $false
      if (![string]::IsNullOrWhiteSpace($_.CommandLine)) {
        $usesCommandLine = $_.CommandLine.IndexOf(
          $normalizedPackagePath,
          [System.StringComparison]::OrdinalIgnoreCase
        ) -ge 0
      }
      $usesExecutablePath -or $usesCommandLine
    }
}

if (!(Test-Path ".venv")) {
  Invoke-CheckedCommand $Python @("-m", "venv", ".venv")
}

Invoke-CheckedCommand ".\.venv\Scripts\python.exe" @("-m", "pip", "install", "--upgrade", "pip")
Invoke-CheckedCommand ".\.venv\Scripts\python.exe" @("-m", "pip", "install", "-e", ".[dev]")

function Find-BrowserExecutable {
  param(
    [string]$BrowsersPath,
    [string]$ExecutableName
  )

  if ([string]::IsNullOrWhiteSpace($BrowsersPath) -or !(Test-Path $BrowsersPath)) {
    return $null
  }
  return Get-ChildItem -Path $BrowsersPath -Filter $ExecutableName -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Test-PlaywrightBrowserCache {
  param([string]$BrowsersPath)

  $chromium = Find-BrowserExecutable $BrowsersPath "chrome.exe"
  $headlessShell = Find-BrowserExecutable $BrowsersPath "chrome-headless-shell.exe"
  return [bool]($chromium -and $headlessShell)
}

function Copy-PlaywrightBrowserCache {
  param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$PackagePath
  )

  $targetPath = Join-Path $PackagePath "_internal\playwright\driver\package\.local-browsers"
  $copyScriptPath = Join-Path $PSScriptRoot "copy_playwright_browsers.ps1"
  Invoke-CheckedCommand "powershell" @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $copyScriptPath,
    $SourcePath,
    $targetPath
  )
  if (!(Test-PlaywrightBrowserCache $targetPath)) {
    throw "复制 Playwright 浏览器失败：目标目录缺少 chrome.exe 或 chrome-headless-shell.exe：$targetPath"
  }
}

$playwrightPackageDirOutput = & ".\.venv\Scripts\python.exe" -c "from pathlib import Path; import playwright; print(Path(playwright.__file__).resolve().parent)"
if ($LASTEXITCODE -ne 0) {
  throw "命令执行失败（退出码 $LASTEXITCODE）：.\.venv\Scripts\python.exe -c <resolve playwright package dir>"
}
$playwrightPackageDir = ($playwrightPackageDirOutput | Select-Object -Last 1).Trim()
$playwrightLocalBrowsersPath = Join-Path $playwrightPackageDir "driver\package\.local-browsers"
$defaultPlaywrightCache = Join-Path $env:LOCALAPPDATA "ms-playwright"
$resolvedPlaywrightPackageDir = [System.IO.Path]::GetFullPath($playwrightPackageDir)
$resolvedPlaywrightLocalBrowsersPath = [System.IO.Path]::GetFullPath($playwrightLocalBrowsersPath)
if (
  !$resolvedPlaywrightLocalBrowsersPath.StartsWith(
    $resolvedPlaywrightPackageDir,
    [System.StringComparison]::OrdinalIgnoreCase
  )
) {
  throw "Playwright 浏览器目录解析异常：$playwrightLocalBrowsersPath"
}

$playwrightBrowserSourcePath = $defaultPlaywrightCache
if (!(Test-PlaywrightBrowserCache $playwrightBrowserSourcePath)) {
  if (Test-PlaywrightBrowserCache $playwrightLocalBrowsersPath) {
    Write-Host "检测到包内 Playwright 浏览器缓存，将迁移到本机缓存：$defaultPlaywrightCache"
    $copyScriptPath = Join-Path $PSScriptRoot "copy_playwright_browsers.ps1"
    Invoke-CheckedCommand "powershell" @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-File", $copyScriptPath,
      $playwrightLocalBrowsersPath,
      $defaultPlaywrightCache
    )
  }
}

if (!(Test-PlaywrightBrowserCache $playwrightBrowserSourcePath)) {
  $previousPlaywrightBrowsersPath = $env:PLAYWRIGHT_BROWSERS_PATH
  Remove-Item Env:\PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue
  try {
    Invoke-CheckedCommand ".\.venv\Scripts\python.exe" @("-m", "playwright", "install", "chromium")
  } finally {
    if ($null -eq $previousPlaywrightBrowsersPath) {
      Remove-Item Env:\PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue
    } else {
      $env:PLAYWRIGHT_BROWSERS_PATH = $previousPlaywrightBrowsersPath
    }
  }
}

if (!(Test-PlaywrightBrowserCache $playwrightBrowserSourcePath)) {
  throw "Playwright Chromium 未完整安装，请重新运行本打包脚本。"
}

if (Test-Path $playwrightLocalBrowsersPath) {
  Remove-Item -LiteralPath $playwrightLocalBrowsersPath -Recurse -Force
}

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

$runningPackageProcesses = Find-ProcessesUsingPackagePath $packageOutputPath | Select-Object -First 8
if ($runningPackageProcesses) {
  $processSummary = ($runningPackageProcesses | ForEach-Object {
      "$($_.Name)(PID $($_.ProcessId))"
    }) -join ", "
  throw "请先关闭正在运行的旧版程序或浏览器子进程；它们正在占用打包目录：$packageOutputPath；占用进程：$processSummary"
}

$pyinstallerArgs = @(
  "--clean",
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

Invoke-CheckedCommand ".\.venv\Scripts\pyinstaller.exe" ($pyinstallerArgs + @("src\subtitle_info_collection\main.py"))

Start-Sleep -Seconds 5
Copy-PlaywrightBrowserCache $playwrightBrowserSourcePath $packageOutputPath

Write-Host "打包完成：$packageOutputPath"
