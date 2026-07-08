param(
  [int]$Port = 8765,
  [switch]$WithSamples,
  [int]$SamplesPort = 8777,
  [switch]$InstallAsr,
  [switch]$SkipDoctor,
  [switch]$StrictDoctor
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$dataDir = Join-Path $projectRoot "data"
$extensionDir = Join-Path $projectRoot "extension"
$doctorScript = Join-Path $projectRoot "scripts\doctor.ps1"
$backendScript = Join-Path $projectRoot "start-backend.ps1"
$backendUrl = "http://127.0.0.1:$Port"
$samplesUrl = "http://127.0.0.1:$SamplesPort"

function Write-Step {
  param([string]$Text)
  Write-Host ""
  Write-Host "==> $Text" -ForegroundColor Cyan
}

function Test-LocalPortOpen {
  param([int]$PortNumber)
  $client = $null
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $async = $client.BeginConnect("127.0.0.1", $PortNumber, $null, $null)
    if (-not $async.AsyncWaitHandle.WaitOne(250, $false)) {
      return $false
    }
    $client.EndConnect($async)
    return $true
  } catch {
    return $false
  } finally {
    if ($client) {
      $client.Close()
    }
  }
}

function Resolve-ProjectPython {
  $venvDir = if ($env:LEARNNOTE_VENV_DIR) { $env:LEARNNOTE_VENV_DIR } else { Join-Path $projectRoot ".venv" }
  $venvPython = Join-Path $venvDir "Scripts\python.exe"
  if (Test-Path $venvPython) {
    return $venvPython
  }
  $pathPython = Get-Command python -ErrorAction SilentlyContinue
  if ($pathPython) {
    return $pathPython.Source
  }
  $anacondaPython = "D:\Anaconda3\python.exe"
  if (Test-Path $anacondaPython) {
    return $anacondaPython
  }
  return "python"
}

function Start-SampleServer {
  param(
    [int]$PortNumber,
    [string]$Url
  )

  if (Test-LocalPortOpen -PortNumber $PortNumber) {
    Write-Host "WARN: $Url is already accepting connections. Reusing it as the sample site." -ForegroundColor Yellow
    return $null
  }

  $logDir = Join-Path $dataDir "logs"
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  $stdoutLog = Join-Path $logDir "samples-$PortNumber.out.log"
  $stderrLog = Join-Path $logDir "samples-$PortNumber.err.log"
  $python = Resolve-ProjectPython
  $sampleServer = Join-Path $projectRoot "scripts\serve-samples.py"
  $args = @(
    $sampleServer,
    "--host",
    "127.0.0.1",
    "--port",
    $PortNumber
  )
  $process = Start-Process `
    -FilePath $python `
    -ArgumentList $args `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog
  Write-Host "Sample server: $Url"
  Write-Host "Sample logs:   $stdoutLog"
  return $process
}

$rootDrive = ([System.IO.DirectoryInfo]$projectRoot).Root.FullName
if ($rootDrive -like "C:\*") {
  throw "LearnNote must run from a non-C drive project path. Move this project to D:\Projects\learnnote-assistant before starting."
}

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$previousBackendOrigin = $env:LEARNNOTE_BACKEND_ORIGIN
$env:LEARNNOTE_BACKEND_ORIGIN = $backendUrl

Write-Host "LearnNote local launcher" -ForegroundColor Green
Write-Host "Project:   $projectRoot"
Write-Host "Data:      $dataDir"
Write-Host "Backend:   $backendUrl"
Write-Host "Origin:    $env:LEARNNOTE_BACKEND_ORIGIN"
if ($WithSamples) {
  Write-Host "Samples:   $samplesUrl"
}
Write-Host "Extension: $extensionDir"
if ($previousBackendOrigin -and $previousBackendOrigin -ne $backendUrl) {
  Write-Host "Origin note: replaced previous LEARNNOTE_BACKEND_ORIGIN=$previousBackendOrigin for this session." -ForegroundColor DarkYellow
}

if (-not $SkipDoctor) {
  Write-Step "Readiness check"
  $doctorArgs = @()
  if ($StrictDoctor) {
    $doctorArgs += "-Strict"
  }
  & $doctorScript @doctorArgs
  $doctorExit = $LASTEXITCODE
  if ($doctorExit -eq 1) {
    throw "Doctor reported a required failure. Fix the FAIL item above, then run .\start-learnnote.ps1 again."
  }
  if ($doctorExit -eq 2) {
    throw "Doctor reported warnings and -StrictDoctor was set. Fix the WARN item above or rerun without -StrictDoctor."
  }
} else {
  Write-Step "Readiness check skipped"
  Write-Host "Run .\scripts\doctor.ps1 when dependencies or browser setup change."
}

Write-Step "Browser setup"
Write-Host "Machine-specific first-run guide:"
Write-Host "  .\scripts\first-run-checklist.ps1 -WriteGuide"
Write-Host "Load the unpacked extension from:"
Write-Host "  $extensionDir"
Write-Host "Chrome: chrome://extensions  Edge: edge://extensions"
Write-Host "After loading, set Side Panel backend URL to:"
Write-Host "  $backendUrl"

if (Test-LocalPortOpen -PortNumber $Port) {
  Write-Host ""
  Write-Host "WARN: $backendUrl is already accepting connections. If this is another service, restart with -Port 8766." -ForegroundColor Yellow
}

$sampleProcess = $null
try {
  if ($WithSamples) {
    Write-Step "Starting local regression samples"
    $sampleProcess = Start-SampleServer -PortNumber $SamplesPort -Url $samplesUrl
    Write-Host "Open these with the unpacked extension loaded:"
    Write-Host "  $samplesUrl/mp4.html          direct MP4"
    Write-Host "  $samplesUrl/hls.html          HLS manifest"
    Write-Host "  $samplesUrl/blob-iframe.html  blob iframe fallback"
    Write-Host "  $samplesUrl/post-api.html     POST play API"
    Write-Host "  $samplesUrl/chaoxing-mock.html  Chaoxing-style diagnostic mock"
  }

  Write-Step "Starting backend"
  Write-Host "Open the web UI after startup:"
  Write-Host "  $backendUrl"
  if (-not $WithSamples) {
    Write-Host "Sample pages, in another terminal:"
    Write-Host "  .\scripts\serve-samples.ps1"
    Write-Host "Or start both together:"
    Write-Host "  .\start-learnnote.ps1 -WithSamples"
  }
  Write-Host "Stop the backend with Ctrl+C."
  Write-Host ""

  $backendArgs = @{ Port = $Port }
  if ($InstallAsr) {
    $backendArgs.InstallAsr = $true
  }
  & $backendScript @backendArgs
} finally {
  if ($sampleProcess -and -not $sampleProcess.HasExited) {
    Write-Host ""
    Write-Host "Stopping sample server on $samplesUrl"
    Stop-Process -Id $sampleProcess.Id -Force -ErrorAction SilentlyContinue
  }
}
