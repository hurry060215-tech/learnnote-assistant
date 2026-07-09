param(
  [Parameter(Position = 0)]
  [string]$Url = "",
  [ValidateSet("edge", "chrome")]
  [string]$Browser = "edge",
  [string]$ProfileDir = "",
  [int]$BackendPort = 0,
  [int]$DebugPort = 0,
  [int]$SamplesPort = 0,
  [int]$WaitMs = 3500,
  [int]$ProbeLimit = 5,
  [double]$TaskTimeout = 180,
  [string]$LearningRequiredSignals = "ananas,playurl,objectid,dtoken,iframe,cookie",
  [switch]$Mock,
  [switch]$NoInteractiveLogin,
  [switch]$TaskProbe,
  [switch]$KeepBrowser
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dataDir = Join-Path $projectRoot "data"
$auditScript = Join-Path $projectRoot "scripts\audit-real-site.ps1"
$sampleServerScript = Join-Path $projectRoot "scripts\serve-samples.py"
$venvDir = if ($env:LEARNNOTE_VENV_DIR) { $env:LEARNNOTE_VENV_DIR } else { Join-Path $projectRoot ".venv" }
$python = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $python)) {
  $python = (Get-Command python -ErrorAction Stop).Source
}

function Get-FreeLocalPort {
  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse("127.0.0.1"), 0)
  $listener.Start()
  try {
    return $listener.LocalEndpoint.Port
  } finally {
    $listener.Stop()
  }
}

if (-not $ProfileDir) {
  $ProfileDir = Join-Path $dataDir "browser-profiles\learning-platform"
}

$sampleProcess = $null
$targetUrl = $Url

try {
  if ($Mock) {
    if ($SamplesPort -le 0) {
      $SamplesPort = Get-FreeLocalPort
    }
    $logDir = Join-Path $dataDir "logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $sampleOutLog = Join-Path $logDir "learning-platform-mock-samples.out.log"
    $sampleErrLog = Join-Path $logDir "learning-platform-mock-samples.err.log"
    $sampleArgs = @(
      (Join-Path $projectRoot "scripts\serve-samples.py"),
      "--host", "127.0.0.1",
      "--port", $SamplesPort
    )
    $sampleProcess = Start-Process -FilePath $python -ArgumentList $sampleArgs -WorkingDirectory $projectRoot -RedirectStandardOutput $sampleOutLog -RedirectStandardError $sampleErrLog -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    $targetUrl = "http://127.0.0.1:$SamplesPort/chaoxing-mock.html"
    Write-Host "Learning-platform mock: $targetUrl"
  }

  if (-not $targetUrl) {
    throw "Provide a learning-platform URL, or pass -Mock to run the local Chaoxing-style mock."
  }

  New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
  Write-Host "Learning audit profile: $ProfileDir"
  Write-Host "Target: $targetUrl"
  Write-Host "Required signals: $LearningRequiredSignals"
  if (-not $Mock -and -not $NoInteractiveLogin) {
    Write-Host "The browser will pause for login/playback. Open the target lesson video, play it for a few seconds, then return here and press Enter."
  }

  $auditParams = @{
    Url = @($targetUrl)
    Browser = $Browser
    BackendPort = $BackendPort
    DebugPort = $DebugPort
    ProfileDir = $ProfileDir
    WaitMs = $WaitMs
    Preflight = $true
    ProbeLimit = $ProbeLimit
    RequireReady = $true
    RequireLearningProfile = $true
    LearningRequiredSignals = $LearningRequiredSignals
    TaskTimeout = $TaskTimeout
  }
  if ($TaskProbe) {
    $auditParams.TaskProbe = $true
  }
  if (-not $Mock -and -not $NoInteractiveLogin) {
    $auditParams.InteractiveLogin = $true
  }
  if ($KeepBrowser) {
    $auditParams.KeepBrowser = $true
  }

  & $auditScript @auditParams
  exit $LASTEXITCODE
} finally {
  if ($sampleProcess -and -not $sampleProcess.HasExited) {
    $sampleProcess.Kill()
    $sampleProcess.WaitForExit()
  }
}
