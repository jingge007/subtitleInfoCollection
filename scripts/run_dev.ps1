param(
  [string]$Python = ".\.venv\Scripts\python.exe",
  [int]$Port = 5173
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (!(Test-Path $Python)) {
  throw "未找到 Python 虚拟环境：$Python；请先执行 python -m venv .venv 并安装依赖。"
}

$env:PYTHONPATH = Join-Path $Root "backend\src"

$nodeVersion = (node -v).TrimStart("v")
if ([int]($nodeVersion.Split(".")[0]) -lt 20) {
  throw "需要 Node.js 20 或更高版本，当前为 $nodeVersion。"
}

if (!(Test-Path "frontend\node_modules")) {
  Write-Host "首次运行，安装前端依赖..."
  Push-Location "frontend"
  npm ci
  Pop-Location
}

Write-Host "启动 Vite 开发服务器：http://127.0.0.1:$Port"
$viteJob = Start-Job -ScriptBlock {
  param($Dir)
  Set-Location $Dir
  npm run dev
} -ArgumentList (Join-Path $Root "frontend")

try {
  $ready = $false
  for ($i = 0; $i -lt 60; $i++) {
    try {
      Invoke-WebRequest -Uri "http://127.0.0.1:$Port" -UseBasicParsing -TimeoutSec 1 | Out-Null
      $ready = $true
      break
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  if (!$ready) {
    throw "Vite 未在预期时间内就绪，请检查 npm run dev 输出。"
  }

  Write-Host "启动 pywebview 窗口..."
  & $Python -m subtitle_info_collection --dev-url "http://127.0.0.1:$Port"
} finally {
  Stop-Job $viteJob -ErrorAction SilentlyContinue
  Remove-Job $viteJob -Force -ErrorAction SilentlyContinue
}
