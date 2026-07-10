param(
  [int]$Port = 8765,
  [switch]$Debug,
  [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $projectRoot "backend\requirements.desktop.txt"
$launcher = Join-Path $projectRoot "desktop\main.py"

if (-not $projectRoot.StartsWith("D:\", [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "LearnNote Desktop must run from D: on this machine. Current path: $projectRoot"
}
if (-not (Test-Path -LiteralPath $python)) {
  throw "D-drive virtual environment is missing: $python"
}

if (-not $SkipInstall) {
  $env:PIP_CACHE_DIR = Join-Path $projectRoot "data\pip-cache"
  & $python -c "import webview" 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing LearnNote Desktop runtime into the D-drive virtual environment..." -ForegroundColor Cyan
    & $python -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) {
      throw "Desktop runtime installation failed."
    }
  }
}

$arguments = @($launcher, "--port", $Port)
if ($Debug) {
  $arguments += "--debug"
}

Write-Host "Starting LearnNote Desktop..." -ForegroundColor Green
Write-Host "Data: $projectRoot\data"
& $python @arguments
