param(
  [int]$Port = 8876,
  [string]$DataPath = "D:\LearnNote\docker-data",
  [switch]$Build,
  [switch]$Pull,
  [switch]$Stop
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$composeFile = Join-Path $projectRoot "compose.local.yaml"

function Resolve-DockerCli {
  $command = Get-Command docker -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }

  $candidates = @(
    "D:\Docker\Desktop\resources\bin\docker.exe",
    "C:\Program Files\Docker\Docker\resources\bin\docker.exe",
    "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe"
  )
  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }
  throw "Docker CLI is not installed. Install Docker Desktop before running this script."
}

function Test-DockerEngine {
  param([string]$DockerCli)

  $previousPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "SilentlyContinue"
    & $DockerCli info --format "{{.ServerVersion}}" 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
  } finally {
    $ErrorActionPreference = $previousPreference
  }
}

function Start-DockerDesktopIfNeeded {
  param([string]$DockerCli)

  if (Test-DockerEngine -DockerCli $DockerCli) { return }

  $desktopCandidates = @(
    "D:\Docker\Desktop\Docker Desktop.exe",
    "C:\Program Files\Docker\Docker\Docker Desktop.exe",
    "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe"
  )
  $desktop = $desktopCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if (-not $desktop) {
    throw "Docker Desktop is installed but its application executable was not found."
  }

  Start-Process -FilePath $desktop -WindowStyle Hidden | Out-Null
  $deadline = (Get-Date).AddMinutes(3)
  do {
    Start-Sleep -Seconds 3
    if (Test-DockerEngine -DockerCli $DockerCli) { return }
  } while ((Get-Date) -lt $deadline)

  throw "Docker Desktop did not become ready within three minutes. Restart Windows and try again."
}

$docker = Resolve-DockerCli
Start-DockerDesktopIfNeeded -DockerCli $docker

$resolvedDataPath = [System.IO.Path]::GetFullPath($DataPath)
if (-not $resolvedDataPath.StartsWith("D:\", [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "LearnNote Docker data must be stored on the D drive. Received: $resolvedDataPath"
}
New-Item -ItemType Directory -Path $resolvedDataPath -Force | Out-Null

$env:LEARNNOTE_PORT = [string]$Port
$env:LEARNNOTE_DATA_PATH = $resolvedDataPath.Replace("\", "/")

$baseArgs = @("compose", "-f", $composeFile, "-p", "learnnote-local")
if ($Stop) {
  & $docker @baseArgs down
  exit $LASTEXITCODE
}

if ($Pull) {
  & $docker @baseArgs pull
  if ($LASTEXITCODE -ne 0) { throw "Unable to pull the LearnNote container image." }
}

$upArgs = @($baseArgs + "up" + "-d")
if ($Build) { $upArgs += "--build" }
& $docker @upArgs
if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed to start LearnNote." }

$healthUrl = "http://127.0.0.1:$Port/health"
$deadline = (Get-Date).AddMinutes(5)
do {
  try {
    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5
    if ($health.ok) {
      Write-Host "LearnNote Docker is ready." -ForegroundColor Green
      Write-Host "Workspace: http://127.0.0.1:$Port"
      Write-Host "Data:      $resolvedDataPath"
      exit 0
    }
  } catch {
    Start-Sleep -Seconds 3
  }
} while ((Get-Date) -lt $deadline)

& $docker @baseArgs logs --tail 120
throw "LearnNote container did not pass its health check within five minutes."
