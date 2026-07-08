param(
  [Parameter(Mandatory = $true, Position = 0)]
  [string[]]$Url,
  [int]$BackendPort = 8765,
  [int]$DebugPort = 0,
  [ValidateSet("chrome", "edge")]
  [string]$Browser = "edge",
  [string]$ProfileDir = "",
  [int]$WaitMs = 3500,
  [switch]$InteractiveLogin,
  [switch]$Preflight,
  [int]$ProbeLimit = 5,
  [switch]$TaskProbe,
  [double]$TaskTimeout = 90,
  [switch]$KeepBrowser,
  [switch]$RequireReady,
  [switch]$RequireLearningProfile,
  [string]$LearningRequiredSignals = "ananas,playurl,objectid,dtoken,iframe,cookie"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvDir = if ($env:LEARNNOTE_VENV_DIR) { $env:LEARNNOTE_VENV_DIR } else { Join-Path $projectRoot ".venv" }
$python = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $python)) {
  $python = (Get-Command python -ErrorAction Stop).Source
}

$argsList = @(
  (Join-Path $projectRoot "scripts\audit-real-site.py")
)
$argsList += $Url
$argsList += @(
  "--backend-port", $BackendPort,
  "--debug-port", $DebugPort,
  "--browser", $Browser,
  "--wait-ms", $WaitMs,
  "--probe-limit", $ProbeLimit,
  "--task-timeout", $TaskTimeout
)
if ($ProfileDir) {
  $argsList += @("--profile-dir", $ProfileDir)
}
if ($InteractiveLogin) {
  $argsList += "--interactive-login"
}
if ($Preflight) {
  $argsList += "--preflight"
}
if ($TaskProbe) {
  $argsList += "--task-probe"
}
if ($KeepBrowser) {
  $argsList += "--keep-browser"
}
if ($RequireReady) {
  $argsList += "--require-ready"
}
if ($RequireLearningProfile) {
  $argsList += "--require-learning-profile"
}
if ($LearningRequiredSignals) {
  $argsList += @("--learning-required-signals", $LearningRequiredSignals)
}

Set-Location $projectRoot
& $python @argsList
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
