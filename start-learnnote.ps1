param(
  [int]$Port = 8765,
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

$rootDrive = ([System.IO.DirectoryInfo]$projectRoot).Root.FullName
if ($rootDrive -like "C:\*") {
  throw "LearnNote must run from a non-C drive project path. Move this project to D:\Projects\learnnote-assistant before starting."
}

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
if (-not $env:LEARNNOTE_BACKEND_ORIGIN) {
  $env:LEARNNOTE_BACKEND_ORIGIN = $backendUrl
}

Write-Host "LearnNote local launcher" -ForegroundColor Green
Write-Host "Project:   $projectRoot"
Write-Host "Data:      $dataDir"
Write-Host "Backend:   $backendUrl"
Write-Host "Extension: $extensionDir"

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
Write-Host "Load the unpacked extension from:"
Write-Host "  $extensionDir"
Write-Host "Chrome: chrome://extensions  Edge: edge://extensions"
Write-Host "After loading, set Side Panel backend URL to:"
Write-Host "  $backendUrl"

if (Test-LocalPortOpen -PortNumber $Port) {
  Write-Host ""
  Write-Host "WARN: $backendUrl is already accepting connections. If this is another service, restart with -Port 8766." -ForegroundColor Yellow
}

Write-Step "Starting backend"
Write-Host "Open the web UI after startup:"
Write-Host "  $backendUrl"
Write-Host "Sample pages, in another terminal:"
Write-Host "  .\scripts\serve-samples.ps1"
Write-Host "Stop the backend with Ctrl+C."
Write-Host ""

$backendArgs = @{ Port = $Port }
if ($InstallAsr) {
  $backendArgs.InstallAsr = $true
}
& $backendScript @backendArgs
