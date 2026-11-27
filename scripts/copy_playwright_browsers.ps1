param(
  [Parameter(Mandatory = $true)]
  [string]$SourcePath,
  [Parameter(Mandatory = $true)]
  [string]$TargetPath
)

$ErrorActionPreference = "Stop"

function ConvertTo-NormalizedPath {
  param([Parameter(Mandatory = $true)][string]$Path)

  return [System.IO.Path]::GetFullPath($Path).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
}

function Copy-ItemWithRetry {
  param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$TargetPath,
    [int]$MaxAttempts = 15
  )

  for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    $tempTargetPath = "$TargetPath.copytmp"
    try {
      if (Test-Path -LiteralPath $tempTargetPath) {
        Remove-Item -LiteralPath $tempTargetPath -Force -ErrorAction SilentlyContinue
      }
      Copy-Item -LiteralPath $SourcePath -Destination $tempTargetPath -Force -ErrorAction Stop
      Move-Item -LiteralPath $tempTargetPath -Destination $TargetPath -Force -ErrorAction Stop
      return
    } catch {
      $copyCommand = "copy /Y `"$SourcePath`" `"$tempTargetPath`""
      & cmd /d /c $copyCommand | Out-Null
      if ($LASTEXITCODE -eq 0) {
        try {
          Move-Item -LiteralPath $tempTargetPath -Destination $TargetPath -Force -ErrorAction Stop
          return
        } catch {
          Remove-Item -LiteralPath $tempTargetPath -Force -ErrorAction SilentlyContinue
        }
      }
      if ($attempt -eq $MaxAttempts) {
        throw "Failed to copy Playwright browsers: $SourcePath -> ${TargetPath}; $($_.Exception.Message)"
      }
      Start-Sleep -Seconds 2
    }
  }
}

function Copy-DirectoryWithRetry {
  param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$TargetPath
  )

  if (!(Test-Path -LiteralPath $SourcePath)) {
    throw "Failed to copy Playwright browsers: source directory does not exist: $SourcePath"
  }

  $sourceRoot = ConvertTo-NormalizedPath $SourcePath
  $sourcePrefix = "$sourceRoot$([System.IO.Path]::DirectorySeparatorChar)"
  New-Item -ItemType Directory -Force -Path $TargetPath | Out-Null

  Get-ChildItem -LiteralPath $SourcePath -Recurse -Directory -Force | ForEach-Object {
    $relativePath = $_.FullName.Substring($sourcePrefix.Length)
    New-Item -ItemType Directory -Force -Path (Join-Path $TargetPath $relativePath) | Out-Null
  }
  Start-Sleep -Seconds 5

  $sensitiveFileNames = @("chrome_elf.dll", "D3DCompiler_47.dll")
  $allFiles = @(Get-ChildItem -LiteralPath $SourcePath -Recurse -File -Force)
  $orderedFiles = @(
    $allFiles | Where-Object { $sensitiveFileNames -contains $_.Name }
    $allFiles | Where-Object { $sensitiveFileNames -notcontains $_.Name }
  )

  $orderedFiles | ForEach-Object {
    $relativePath = $_.FullName.Substring($sourcePrefix.Length)
    $targetFilePath = Join-Path $TargetPath $relativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetFilePath) | Out-Null
    Copy-ItemWithRetry -SourcePath $_.FullName -TargetPath $targetFilePath
  }
}

Copy-DirectoryWithRetry -SourcePath $SourcePath -TargetPath $TargetPath
