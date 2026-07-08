param(
  [int]$BackendPort = 8765,
  [int]$SamplesPort = 8777,
  [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvDir = if ($env:LEARNNOTE_VENV_DIR) { $env:LEARNNOTE_VENV_DIR } else { Join-Path $projectRoot ".venv" }
$python = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $python)) {
  $python = (Get-Command python -ErrorAction Stop).Source
}

$argsList = @(
  (Join-Path $projectRoot "scripts\e2e-local-smoke.py"),
  "--backend-port", $BackendPort,
  "--samples-port", $SamplesPort
)
if ($OpenBrowser) {
  $argsList += "--open-browser"
}

Set-Location $projectRoot
& $python @argsList
exit $LASTEXITCODE
