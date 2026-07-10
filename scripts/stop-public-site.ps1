$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$statePath = Join-Path $projectRoot "data\config\public-site-state.json"
if (-not (Test-Path -LiteralPath $statePath)) {
  Write-Host "No detached LearnNote public website state found."
  exit 0
}

$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
foreach ($entry in @(
  @{ name = "tunnel"; pid = [int]$state.tunnel_pid },
  @{ name = "site"; pid = [int]$state.site_pid }
)) {
  $process = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
  if ($process) {
    Stop-Process -Id $process.Id -Force
    Write-Host "Stopped $($entry.name) process $($process.Id)."
  }
}
Remove-Item -LiteralPath $statePath -Force
