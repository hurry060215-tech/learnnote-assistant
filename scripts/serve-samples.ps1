param(
  [int]$Port = 8777,
  [string]$HostName = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvDir = if ($env:LEARNNOTE_VENV_DIR) { $env:LEARNNOTE_VENV_DIR } else { Join-Path $projectRoot ".venv" }
$python = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $python)) {
  $python = (Get-Command python -ErrorAction Stop).Source
}

Set-Location $projectRoot
& $python (Join-Path $projectRoot "scripts\serve-samples.py") --host $HostName --port $Port
