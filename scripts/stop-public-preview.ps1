$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$statePath = Join-Path $projectRoot "data\config\public-preview-state.json"

if (-not (Test-Path $statePath)) {
  Write-Host "No detached public preview state found."
  exit 0
}

$state = Get-Content -Raw -Encoding UTF8 $statePath | ConvertFrom-Json
foreach ($processId in @($state.tunnel_pid, $state.backend_pid)) {
  if ($processId) {
    Stop-Process -Id ([int]$processId) -Force -ErrorAction SilentlyContinue
  }
}
Remove-Item -LiteralPath $statePath -Force
Write-Host "Stopped LearnNote public preview."
