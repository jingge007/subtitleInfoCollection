$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (!(Test-Path ".venv")) {
  python -m venv .venv
}

$pipOut = & ".\.venv\Scripts\python.exe" -m pip install -e ".[dev]" 2>$null
$pipOut | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install 失败 (exit code: $LASTEXITCODE)"
    exit 1
}
& ".\.venv\Scripts\python.exe" -m subtitle_info_collection
