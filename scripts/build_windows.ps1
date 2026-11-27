param(
  [string]$Python = "python",
  [switch]$Pack,
  [string]$PackVersion = "",
  [string]$Channel = "win",
  [string]$VpkVersion = "1.2.161",
  [switch]$SkipFrontend,
  [switch]$SkipPlaywright,
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$AppName = "字幕采集工具"
$PackId = "SubtitleInfoCollection"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$DistRoot = Join-Path $Root "dist"
$PackagePath = Join-Path $DistRoot $AppName
$ReleasePath = Join-Path $DistRoot "releases"
$WorkPath = Join-Path $Root "build\pyinstaller"
$ToolsDir = Join-Path $PSScriptRoot "tools"
$SpecPath = Join-Path $Backend "$AppName.spec"
$IconPath = Join-Path $Backend "assets\head_logo.ico"
Set-Location $Root

function Get-EnvValue {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Key
  )

  if (!(Test-Path $Path)) {
    return ""
  }
  $text = Get-Content $Path -Raw -Encoding UTF8
  $match = [regex]::Match($text, "(?m)^\s*$([regex]::Escape($Key))\s*=\s*(.*?)\s*$")
  if (!$match.Success) {
    return ""
  }
  return $match.Groups[1].Value.Trim().Trim('"').Trim("'")
}

$configuredDistPath = Get-EnvValue (Join-Path $Root ".env") "SUBTITLE_COLLECTION_PACKAGE_DIST_DIR"
if (![string]::IsNullOrWhiteSpace($configuredDistPath)) {
  if ([System.IO.Path]::IsPathRooted($configuredDistPath)) {
    $customDist = [System.IO.Path]::GetFullPath($configuredDistPath)
  } else {
    $customDist = [System.IO.Path]::GetFullPath((Join-Path $Root $configuredDistPath))
  }
  $customDist = $customDist.TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
  if ((Split-Path -Leaf $customDist) -eq $AppName) {
    $DistRoot = Split-Path -Parent $customDist
    $PackagePath = $customDist
  } else {
    $DistRoot = $customDist
    $PackagePath = Join-Path $DistRoot $AppName
  }
  $ReleasePath = Join-Path $DistRoot "releases"
}

function Invoke-CheckedCommand {
  param(
    [Parameter(Mandatory = $true)][string]$CommandPath,
    [string[]]$CommandArguments = @()
  )

  & $CommandPath @CommandArguments | Out-Host
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    throw "命令执行失败（退出码 $exitCode）：$CommandPath $($CommandArguments -join ' ')"
  }
}

function Get-AppVersion {
  $initFile = Join-Path $Backend "src\subtitle_info_collection\__init__.py"
  $text = Get-Content $initFile -Raw -Encoding UTF8
  $match = [regex]::Match($text, '__version__\s*=\s*"([^"]+)"')
  if (!$match.Success) {
    throw "无法从 $initFile 读取 __version__"
  }
  return $match.Groups[1].Value
}

function Assert-PathUnderDirectory {
  param(
    [Parameter(Mandatory = $true)][string]$CandidatePath,
    [Parameter(Mandatory = $true)][string]$DirectoryPath
  )

  $candidate = [System.IO.Path]::GetFullPath($CandidatePath).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
  $directory = [System.IO.Path]::GetFullPath($DirectoryPath).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
  if (
    !$candidate.Equals($directory, [System.StringComparison]::OrdinalIgnoreCase) -and
    !$candidate.StartsWith(
      "$directory$([System.IO.Path]::DirectorySeparatorChar)",
      [System.StringComparison]::OrdinalIgnoreCase
    )
  ) {
    throw "拒绝操作预期目录之外的路径：$candidate"
  }
}

function Remove-SafeDirectory {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$ParentPath
  )

  if (!(Test-Path $Path)) {
    return
  }
  Assert-PathUnderDirectory $Path $ParentPath
  Remove-Item -LiteralPath $Path -Recurse -Force
}

function Test-PlaywrightBrowserCache {
  param(
    [Parameter(Mandatory = $true)][string]$BrowsersPath,
    [switch]$RequireFullChromium
  )

  if (!(Test-Path $BrowsersPath)) {
    return $false
  }
  $headless = Get-ChildItem -Path $BrowsersPath -Filter "chrome-headless-shell.exe" -Recurse -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if (!$headless) {
    return $false
  }
  if ($RequireFullChromium) {
    $chromium = Get-ChildItem -Path $BrowsersPath -Filter "chrome.exe" -Recurse -ErrorAction SilentlyContinue |
      Select-Object -First 1
    return [bool]$chromium
  }
  return $true
}

function Copy-PlaywrightBrowsers {
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
    throw "复制 Playwright 浏览器失败：$targetPath"
  }

  # 只保留无头浏览器，删除完整 Chromium 与 MCP 浏览器以控制体积
  Get-ChildItem -LiteralPath $targetPath -Directory -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Name -like "chromium-*" -or $_.Name -like "mcp-chrome-*"
    } |
    ForEach-Object {
      Remove-Item -LiteralPath $_.FullName -Recurse -Force
      Write-Host "  - 已精简 $($_.Name)"
    }
}

function Resolve-Vpk {
  $command = Get-Command "vpk" -ErrorAction SilentlyContinue
  if ($command) {
    return @{ Kind = "exe"; Path = $command.Source }
  }

  $dotnetInstaller = Join-Path $ToolsDir "dotnet-install.ps1"
  $dotnetDir = Join-Path $ToolsDir "dotnet"
  $dotnetExe = Join-Path $dotnetDir "dotnet.exe"
  if (!(Test-Path $dotnetExe)) {
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    if (!(Test-Path $dotnetInstaller)) {
      Invoke-WebRequest -Uri "https://dot.net/v1/dotnet-install.ps1" -OutFile $dotnetInstaller -UseBasicParsing -TimeoutSec 120
    }
    Write-Host "安装本地 .NET 8 运行时（仅用于 vpk）..."
    Invoke-CheckedCommand "powershell" @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-File", $dotnetInstaller,
      "-Runtime", "dotnet",
      "-Channel", "8.0",
      "-InstallDir", $dotnetDir
    )
  }

  $vpkRoot = Join-Path $ToolsDir "vpk\$VpkVersion"
  $vpkDll = Join-Path $vpkRoot "tools\net8.0\any\vpk.dll"
  if (!(Test-Path $vpkDll)) {
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    $nupkgPath = Join-Path $ToolsDir "vpk.$VpkVersion.nupkg"
    if (!(Test-Path $nupkgPath)) {
      $url = "https://github.com/velopack/velopack/releases/download/$VpkVersion/vpk.$VpkVersion.nupkg"
      Write-Host "下载 vpk $VpkVersion：$url"
      Invoke-WebRequest -Uri $url -OutFile $nupkgPath -UseBasicParsing -TimeoutSec 300
    }
    $zipPath = Join-Path $ToolsDir "vpk.$VpkVersion.zip"
    Copy-Item -LiteralPath $nupkgPath -Destination $zipPath -Force
    Expand-Archive -Path $zipPath -DestinationPath $vpkRoot -Force
  }
  if (!(Test-Path $vpkDll)) {
    throw "vpk 解压失败，未找到：$vpkDll"
  }
  return @{ Kind = "dotnet"; Dotnet = $dotnetExe; Dll = $vpkDll }
}

function Invoke-VpkPack {
  param(
    [Parameter(Mandatory = $true)][hashtable]$Vpk,
    [Parameter(Mandatory = $true)][string]$Version
  )

  $arguments = @(
    "--yes", "pack",
    "--packId", $PackId,
    "--packVersion", $Version,
    "--packDir", $PackagePath,
    "--mainExe", "$AppName.exe",
    "--packTitle", $AppName,
    "--packAuthors", "jingge007",
    "--icon", $IconPath,
    "--outputDir", $ReleasePath,
    "--channel", $Channel,
    "--runtime", "win-x64",
    "--skipVeloAppCheck"
  )
  $releaseNotes = Join-Path $Root "CHANGELOG.md"
  if (Test-Path $releaseNotes) {
    $arguments += @("--releaseNotes", $releaseNotes)
  }

  if ($Vpk.Kind -eq "exe") {
    Invoke-CheckedCommand $Vpk.Path $arguments
  } else {
    Invoke-CheckedCommand $Vpk.Dotnet (@("exec", $Vpk.Dll) + $arguments)
  }
}

if (!(Test-Path $VenvPython)) {
  Invoke-CheckedCommand $Python @("-m", "venv", (Join-Path $Root ".venv"))
}
Invoke-CheckedCommand $VenvPython @("-m", "pip", "install", "--upgrade", "pip")
Invoke-CheckedCommand $VenvPython @(
  "-m", "pip", "install", "-e", "${Backend}[dev]"
)

if (!$SkipFrontend) {
  if (!(Test-Path (Join-Path $Frontend "package-lock.json"))) {
    throw "缺少 frontend/package-lock.json，无法执行 npm ci"
  }
  Push-Location $Frontend
  try {
    Invoke-CheckedCommand "npm" @("ci")
    Invoke-CheckedCommand "npm" @("run", "build")
  } finally {
    Pop-Location
  }
}
if (!(Test-Path (Join-Path $Frontend "dist\index.html"))) {
  throw "缺少前端构建产物：frontend\dist\index.html"
}

$appVersion = Get-AppVersion
if ([string]::IsNullOrWhiteSpace($PackVersion)) {
  $PackVersion = $appVersion
}
if ($PackVersion -ne $appVersion) {
  Write-Warning "PackVersion=$PackVersion 与 __version__=$appVersion 不一致"
}
if ($PackVersion -notmatch '^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$') {
  throw "PackVersion 不是有效 SemVer：$PackVersion"
}

$playwrightCache = Join-Path $env:LOCALAPPDATA "ms-playwright"
if (!$SkipPlaywright) {
  if (!(Test-PlaywrightBrowserCache $playwrightCache -RequireFullChromium)) {
    Invoke-CheckedCommand $VenvPython @("-m", "playwright", "install", "chromium")
  }
  if (!(Test-PlaywrightBrowserCache $playwrightCache -RequireFullChromium)) {
    throw "Playwright Chromium 未完整安装：$playwrightCache"
  }
}

if (!$SkipBuild) {
  Remove-SafeDirectory $PackagePath $DistRoot
  New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
  Invoke-CheckedCommand $VenvPython @(
    "-m", "PyInstaller",
    "--clean",
    "--noconfirm",
    "--distpath", $DistRoot,
    "--workpath", $WorkPath,
    $SpecPath
  )
} elseif (!(Test-Path (Join-Path $PackagePath "$AppName.exe"))) {
  throw "指定了 -SkipBuild，但现有产物不存在：$PackagePath\$AppName.exe"
}

if (!(Test-Path (Join-Path $PackagePath "$AppName.exe"))) {
  throw "PyInstaller 未生成主程序：$PackagePath\$AppName.exe"
}
if (!(Test-Path (Join-Path $PackagePath "_internal\webui\index.html"))) {
  throw "产物缺少前端页面：_internal\webui\index.html"
}
if (!(Test-Path (Join-Path $PackagePath "_internal\assets\head_logo.ico"))) {
  throw "产物缺少图标：_internal\assets\head_logo.ico"
}

if (!$SkipPlaywright) {
  Copy-PlaywrightBrowsers $playwrightCache $PackagePath
}

Write-Host "清理运行时无关文件..."
Get-ChildItem -Path $PackagePath -Filter "*.pyi" -Recurse -File -ErrorAction SilentlyContinue |
  Remove-Item -Force
Get-ChildItem -Path $PackagePath -Filter "__pycache__" -Recurse -Directory -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force
Get-ChildItem -Path $PackagePath -Filter "*.dist-info" -Recurse -Directory -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force
Get-ChildItem -Path $PackagePath -Filter "*.egg-info" -Recurse -Directory -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force

$playwrightTypes = Join-Path $PackagePath "_internal\playwright\driver\package\types"
if (Test-Path $playwrightTypes) {
  Remove-Item -LiteralPath $playwrightTypes -Recurse -Force
}
$leakedEnv = Get-ChildItem -Path $PackagePath -Recurse -Force -Filter ".env" -ErrorAction SilentlyContinue |
  Select-Object -First 1
if ($leakedEnv) {
  throw "打包目录中出现真实 .env，已阻止发布：$($leakedEnv.FullName)"
}

$secretPattern = "(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC )?PRIVATE KEY-----)"
$textExtensions = @(".json", ".txt", ".log", ".js", ".py", ".html", ".css", ".md", ".yaml", ".yml")
$secretHits = Get-ChildItem -Path $PackagePath -Recurse -File -ErrorAction SilentlyContinue |
  Where-Object {
    $_.Length -lt 2MB -and
    $textExtensions -contains $_.Extension.ToLowerInvariant() -and
    $_.FullName -notmatch '\\(SelfTest|tests?)\\'
  } |
  Select-String -Pattern $secretPattern -ErrorAction SilentlyContinue
if ($secretHits) {
  $first = $secretHits | Select-Object -First 1
  throw "产物文本中发现疑似密钥：$($first.Path):$($first.LineNumber)"
}

Write-Host "便携目录打包完成：$PackagePath"

if ($Pack) {
  $vpk = Resolve-Vpk
  Write-Host "使用 vpk 生成 Velopack 发布包（版本 $PackVersion）..."
  Invoke-VpkPack $vpk $PackVersion

  $requiredAssets = @(
    "releases.win.json",
    "$PackId-$PackVersion-full.nupkg",
    "$PackId-win-Setup.exe",
    "$PackId-win-Portable.zip"
  )
  foreach ($asset in $requiredAssets) {
    $assetPath = Join-Path $ReleasePath $asset
    if (!(Test-Path $assetPath)) {
      throw "缺少发布资产：$assetPath"
    }
  }
  Write-Host "Velopack 发布目录：$ReleasePath"
  Get-ChildItem -LiteralPath $ReleasePath | Select-Object Name, Length, LastWriteTime
}
