param(
  [switch]$Json,
  [switch]$Strict
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvDir = if ($env:LEARNNOTE_VENV_DIR) { $env:LEARNNOTE_VENV_DIR } else { Join-Path $projectRoot ".venv" }
$python = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $python)) {
  $python = (Get-Command python -ErrorAction Stop).Source
}

$argsList = @(Join-Path $projectRoot "scripts\doctor.py")
if ($Json) {
  $argsList += "--json"
}
if ($Strict) {
  $argsList += "--strict"
}

Set-Location $projectRoot
& $python @argsList
