param(
  [switch]$Json,
  [string]$Output = "",
  [switch]$Strict,
  [switch]$RequireRealSiteAudits,
  [switch]$SkipAcceptanceGate
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$argsList = @((Join-Path $projectRoot "scripts\audit-product-readiness.py"))
if ($Json) {
  $argsList += "--json"
}
if ($Output) {
  $argsList += @("--output", $Output)
}
if ($Strict) {
  $argsList += "--strict"
}
if ($RequireRealSiteAudits) {
  $argsList += "--require-real-site-audits"
}
if ($SkipAcceptanceGate) {
  $argsList += "--skip-acceptance-gate"
}

& $python @argsList
exit $LASTEXITCODE
