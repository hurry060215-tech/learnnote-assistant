param(
  [int]$Port = 8765,
  [switch]$Debug,
  [switch]$InstallAsr,
  [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $projectRoot "backend\requirements.desktop.txt"
$launcher = Join-Path $projectRoot "desktop\main.py"
$backendBootstrap = Join-Path $projectRoot "start-backend.ps1"

if (-not $projectRoot.StartsWith("D:\", [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "LearnNote Desktop must run from D: on this machine. Current path: $projectRoot"
}
if (-not $SkipInstall) {
  $bootstrapArgs = @{ BootstrapOnly = $true; Port = $Port }
  if ($InstallAsr) {
    $bootstrapArgs.InstallAsr = $true
  }
  & $backendBootstrap @bootstrapArgs
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

if (-not (Test-Path -LiteralPath $python)) {
  throw "D-drive virtual environment is missing: $python. Run without -SkipInstall to create it."
}

$arguments = @($launcher, "--port", $Port)
if ($Debug) {
  $arguments += "--debug"
}

# Running a package module from its file path removes the project root from
# Python's import path. Keep the root explicit so desktop/main.py can import
# the desktop package when the launcher is started from any working directory.
$projectPath = $env:PYTHONPATH
$env:PYTHONPATH = if ($projectPath) { "$projectRoot;$projectPath" } else { $projectRoot }

Write-Host "Starting LearnNote Desktop..." -ForegroundColor Green
Write-Host "Data: $projectRoot\data"
& $python @arguments
