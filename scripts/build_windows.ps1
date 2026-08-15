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

# 下载并配置 UPX 压缩工具
$upxUrl = "https://github.com/upx/upx/releases/download/v4.2.4/upx-4.2.4-win64.zip"
$upxZipPath = Join-Path $PSScriptRoot "upx.zip"
$upxDir = Join-Path $PSScriptRoot "upx"
$upxExePath = Join-Path $upxDir "upx.exe"

if (!(Test-Path $upxExePath)) {
    Write-Host "正在下载 UPX 压缩工具..."
    try {
        Invoke-WebRequest -Uri $upxUrl -OutFile $upxZipPath -ErrorAction Stop
        Expand-Archive -Path $upxZipPath -DestinationPath $upxDir -Force
        # UPX 解压后会在子目录中，找到 upx.exe 并移动到上级目录
        $upxExe = Get-ChildItem -Path $upxDir -Recurse -Filter "upx.exe" | Select-Object -First 1
        if ($upxExe) {
            Move-Item -Path $upxExe.FullName -Destination $upxExePath -Force
        }
        Remove-Item -Path $upxZipPath -Force -ErrorAction SilentlyContinue
        Write-Host "UPX 下载完成：$upxExePath"
    } catch {
        Write-Host "警告: 无法下载 UPX，将不使用压缩：$($_.Exception.Message)"
    }
}

# 将 UPX 目录添加到 PATH（如果可用）
if (Test-Path $upxExePath) {
    $env:PATH = "$upxDir;$env:PATH"
    Write-Host "已启用 UPX 压缩：$upxExePath"
}

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
  "--noconfirm"
)

if (![string]::IsNullOrWhiteSpace($configuredDistPath)) {
  Write-Host "检测到自定义打包输出目录：$packageOutputPath"
  $pyinstallerArgs += "--distpath"
  $pyinstallerArgs += $resolvedDistPath
}

# 使用 spec 文件（已配置收集和排除规则）
Invoke-CheckedCommand ".\.venv\Scripts\pyinstaller.exe" ($pyinstallerArgs + @("字幕采集工具.spec"))

Start-Sleep -Seconds 5
Copy-PlaywrightBrowserCache $playwrightBrowserSourcePath $packageOutputPath


# 精简 Playwright 浏览器：只保留 headless shell，删除完整 Chromium 和 MCP Chrome
Write-Host '开始精简 Playwright 浏览器...'
$browsersDir = Join-Path $packageOutputPath '_internal\playwright\driver\package\.local-browsers'
if (Test-Path $browsersDir) {
    $chromiumDir = Join-Path $browsersDir 'chromium-1217'
    if (Test-Path $chromiumDir) {
        Remove-Item -LiteralPath $chromiumDir -Recurse -Force
        Write-Host '  - 已删除完整 Chromium (chromium-1217)'
    }
    $mcpDirs = Get-ChildItem -Path $browsersDir -Directory -Filter 'mcp-chrome-*' -ErrorAction SilentlyContinue
    foreach ($d in $mcpDirs) {
        Remove-Item -LiteralPath $d.FullName -Recurse -Force
        Write-Host "  - 已删除 MCP Chrome: $($d.Name)"
    }
}
Write-Host 'Playwright 浏览器精简完成！'

# 清理不必要的文件以减小体积
Write-Host "开始清理不必要的文件..."

# 删除翻译文件（.qm）- PySide6 翻译文件在运行时不需要
$qmFiles = Get-ChildItem -Path $packageOutputPath -Filter "*.qm" -Recurse -ErrorAction SilentlyContinue
if ($qmFiles) {
    $qmFiles | Remove-Item -Force
    Write-Host "  - 已删除 $($qmFiles.Count) 个翻译文件（.qm）"
}

# 删除类型注解文件（.pyi）- 运行时不需要
$pyiFiles = Get-ChildItem -Path $packageOutputPath -Filter "*.pyi" -Recurse -ErrorAction SilentlyContinue
if ($pyiFiles) {
    $pyiFiles | Remove-Item -Force
    Write-Host "  - 已删除 $($pyiFiles.Count) 个类型注解文件（.pyi）"
}

# 删除 __pycache__ 目录
$pycacheDirs = Get-ChildItem -Path $packageOutputPath -Filter "__pycache__" -Recurse -Directory -ErrorAction SilentlyContinue
if ($pycacheDirs) {
    $pycacheDirs | Remove-Item -Recurse -Force
    Write-Host "  - 已删除 $($pycacheDirs.Count) 个 __pycache__ 目录"
}

# 删除 .dist-info 和 .egg-info 目录（元数据不需要）
$infoDirs = Get-ChildItem -Path $packageOutputPath -Filter "*.dist-info" -Recurse -Directory -ErrorAction SilentlyContinue
$infoDirs += Get-ChildItem -Path $packageOutputPath -Filter "*.egg-info" -Recurse -Directory -ErrorAction SilentlyContinue
if ($infoDirs) {
    $infoDirs | Remove-Item -Recurse -Force
    Write-Host "  - 已删除 $($infoDirs.Count) 个元数据目录（.dist-info/.egg-info）"
}


# 删除不需要的 PySide6 插件
$pluginsDir = Join-Path $packageOutputPath '_internal\PySide6\plugins'
if (Test-Path $pluginsDir) {
    $unusedPlugins = @(
        'assetimporters', 'canbus', 'designer', 'geometryloaders', 'geoservices',
        'multimedia', 'networkinformation', 'position', 'qmllint', 'qmltooling',
        'renderers', 'renderplugins', 'sceneparsers', 'scxmldatamodel',
        'sensors', 'texttospeech', 'webview'
    )
    $removedPlugins = 0
    foreach ($plugin in $unusedPlugins) {
        $pluginPath = Join-Path $pluginsDir $plugin
        if (Test-Path $pluginPath) {
            Remove-Item -LiteralPath $pluginPath -Recurse -Force
            $removedPlugins++
        }
    }
    if ($removedPlugins -gt 0) {
        Write-Host "  - 已删除 $removedPlugins 个不需要的 Qt 插件目录"
    }
}

# 删除 PySide6 开发头文件和类型系统文件
$pyside6Dir = Join-Path $packageOutputPath '_internal\PySide6'
if (Test-Path $pyside6Dir) {
    foreach ($sub in @('include', 'typesystems')) {
        $subPath = Join-Path $pyside6Dir $sub
# Delete QML
$qmlDir = Join-Path $pyside6Dir "qml\PySide6\qml"
if (Test-Path $qmlDir) { Remove-Item -LiteralPath $qmlDir -Recurse -Force; Write-Host "  - 已删除 QML 目录" }

        if (Test-Path $subPath) {
            Remove-Item -LiteralPath $subPath -Recurse -Force
            Write-Host "  - 已删除 PySide6/$sub"
        }
    }
}

# 删除 Playwright TypeScript 类型定义
$pwTypesDir = Join-Path $packageOutputPath '_internal\playwright\driver\package\types'
if (Test-Path $pwTypesDir) {
    Remove-Item -LiteralPath $pwTypesDir -Recurse -Force
    Write-Host '  - 已删除 Playwright TypeScript 类型定义'
}

Write-Host "清理完成！"

Write-Host "打包完成：$packageOutputPath"
