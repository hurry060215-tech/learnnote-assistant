param(
  [int]$BackendPort = 8765,
  [int]$SamplesPort = 8777,
  [int]$DebugPort = 0,
  [ValidateSet("chrome", "edge")]
  [string]$Browser = "edge",
  [switch]$KeepBrowser
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvDir = if ($env:LEARNNOTE_VENV_DIR) { $env:LEARNNOTE_VENV_DIR } else { Join-Path $projectRoot ".venv" }
$python = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $python)) {
  $python = (Get-Command python -ErrorAction Stop).Source
}

$argsList = @(
  (Join-Path $projectRoot "scripts\e2e-extension-smoke.py"),
  "--backend-port", $BackendPort,
  "--samples-port", $SamplesPort,
  "--debug-port", $DebugPort,
  "--browser", $Browser
)
if ($KeepBrowser) {
  $argsList += "--keep-browser"
}

Set-Location $projectRoot
& $python @argsList
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
