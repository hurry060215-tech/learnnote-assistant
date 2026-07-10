param(
  [int]$Port = 8790,
  [switch]$Detach
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$siteDir = Join-Path $projectRoot "site"
$dataDir = Join-Path $projectRoot "data"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$cloudflared = Join-Path $dataDir "tools\cloudflared.exe"
$logDir = Join-Path $dataDir "logs"
$configDir = Join-Path $dataDir "config"
$statePath = Join-Path $configDir "public-site-state.json"

if (-not $projectRoot.StartsWith("D:\", [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "LearnNote public-site runtime must stay on D:. Current path: $projectRoot"
}
foreach ($path in @($siteDir, $python, $cloudflared)) {
  if (-not (Test-Path -LiteralPath $path)) {
    throw "Required public-site component is missing: $path"
  }
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
  throw "Port $Port is already in use. Stop the existing service or choose another port."
}

New-Item -ItemType Directory -Force -Path $logDir, $configDir | Out-Null
$siteOut = Join-Path $logDir "public-site-$Port.out.log"
$siteErr = Join-Path $logDir "public-site-$Port.err.log"
$tunnelOut = Join-Path $logDir "public-site-tunnel-$Port.out.log"
$tunnelErr = Join-Path $logDir "public-site-tunnel-$Port.err.log"

$completed = $false
$siteProcess = $null
$tunnelProcess = $null
try {
  $siteProcess = Start-Process `
    -FilePath $python `
    -ArgumentList @("-m", "http.server", $Port, "--bind", "127.0.0.1", "--directory", $siteDir) `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $siteOut `
    -RedirectStandardError $siteErr

  $deadline = (Get-Date).AddSeconds(15)
  while ((Get-Date) -lt $deadline -and -not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
    Start-Sleep -Milliseconds 200
  }
  if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
    throw "Static LearnNote website did not start on port $Port."
  }

  $tunnelProcess = Start-Process `
    -FilePath $cloudflared `
    -ArgumentList @("tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate") `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $tunnelOut `
    -RedirectStandardError $tunnelErr

  $publicUrl = ""
  $deadline = (Get-Date).AddSeconds(35)
  while ((Get-Date) -lt $deadline -and -not $publicUrl) {
    Start-Sleep -Milliseconds 350
    $logs = @()
    if (Test-Path -LiteralPath $tunnelOut) { $logs += Get-Content -Raw -LiteralPath $tunnelOut }
    if (Test-Path -LiteralPath $tunnelErr) { $logs += Get-Content -Raw -LiteralPath $tunnelErr }
    $match = [regex]::Match(($logs -join "`n"), "https://[a-z0-9-]+\.trycloudflare\.com")
    if ($match.Success) { $publicUrl = $match.Value }
  }
  if (-not $publicUrl) {
    throw "Cloudflare did not return a public website URL. Check $tunnelErr"
  }

  $state = [ordered]@{
    site_pid = $siteProcess.Id
    tunnel_pid = $tunnelProcess.Id
    local_url = "http://127.0.0.1:$Port"
    public_url = $publicUrl
    started_at = (Get-Date).ToString("o")
  }
  $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
  $completed = $true

  Write-Host "LearnNote public website is running." -ForegroundColor Green
  Write-Host "Public: $publicUrl"
  Write-Host "Local:  http://127.0.0.1:$Port"
  Write-Host "No login is required. This static site exposes no processing API."

  if (-not $Detach) {
    Write-Host "Press Ctrl+C to stop the site."
    Wait-Process -Id $tunnelProcess.Id
  }
} finally {
  if (-not $Detach -or -not $completed) {
    foreach ($process in @($tunnelProcess, $siteProcess)) {
      if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
      }
    }
  }
}
