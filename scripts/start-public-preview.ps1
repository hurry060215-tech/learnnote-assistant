param(
  [int]$Port = 8767,
  [string]$Username = "ln",
  [switch]$Tunnel,
  [switch]$Detach
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$backendDir = Join-Path $projectRoot "backend"
$dataDir = Join-Path $projectRoot "data\public-preview"
$configDir = Join-Path $projectRoot "data\config"
$toolsDir = Join-Path $projectRoot "data\tools"
$logsDir = Join-Path $projectRoot "data\logs"
$credentialsPath = Join-Path $configDir "public-preview.json"
$statePath = Join-Path $configDir "public-preview-state.json"
$cloudflared = Join-Path $toolsDir "cloudflared.exe"

if (-not (Test-Path $python)) {
  throw "Project Python not found: $python"
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
  throw "Port $Port is already in use. Stop the existing service or choose another -Port."
}

New-Item -ItemType Directory -Force -Path $dataDir, $configDir, $toolsDir, $logsDir | Out-Null

if (Test-Path $credentialsPath) {
  $credentials = Get-Content -Raw -Encoding UTF8 $credentialsPath | ConvertFrom-Json
} else {
  $bytes = New-Object byte[] 24
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  $password = [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
  $credentials = [pscustomobject]@{ username = $Username; password = $password }
  $credentials | ConvertTo-Json | Set-Content -Encoding UTF8 $credentialsPath
}

if (-not $credentials.username -or [string]$credentials.password -match '^.{0,11}$') {
  throw "Public preview credentials are invalid: $credentialsPath"
}

$env:LEARNNOTE_DEPLOYMENT_MODE = "server"
$env:LEARNNOTE_PUBLIC_USERNAME = [string]$credentials.username
$env:LEARNNOTE_PUBLIC_PASSWORD = [string]$credentials.password
$env:LEARNNOTE_DATA_DIR = $dataDir
$env:LEARNNOTE_BACKEND_ORIGIN = "http://127.0.0.1:$Port"
$env:HF_HOME = Join-Path $dataDir "model-cache\huggingface"
$env:XDG_CACHE_HOME = Join-Path $dataDir "model-cache\xdg"
$env:TORCH_HOME = Join-Path $dataDir "model-cache\torch"
$env:TMP = Join-Path $dataDir "temp"
$env:TEMP = $env:TMP
$env:TMPDIR = $env:TMP
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null

$backendOut = Join-Path $logsDir "public-preview-$Port.out.log"
$backendErr = Join-Path $logsDir "public-preview-$Port.err.log"
$backend = Start-Process `
  -FilePath $python `
  -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $Port) `
  -WorkingDirectory $backendDir `
  -RedirectStandardOutput $backendOut `
  -RedirectStandardError $backendErr `
  -WindowStyle Hidden `
  -PassThru

$tunnelProcess = $null
$publicUrl = ""
$completed = $false
try {
  $deadline = (Get-Date).AddSeconds(30)
  do {
    Start-Sleep -Milliseconds 500
    try { $health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2 } catch { $health = $null }
  } while (-not $health.ok -and -not $backend.HasExited -and (Get-Date) -lt $deadline)
  if (-not $health.ok) {
    throw "Public preview backend did not become healthy. See $backendErr"
  }

  if ($Tunnel) {
    if (-not (Test-Path $cloudflared)) {
      Write-Host "Downloading cloudflared to D-drive tools cache..."
      & curl.exe -L --fail --retry 2 -o $cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
      if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $cloudflared -Force -ErrorAction SilentlyContinue
        $gh = Get-Command gh -ErrorAction SilentlyContinue
        if ($gh) {
          & $gh.Source release download --repo cloudflare/cloudflared --pattern "cloudflared-windows-amd64.exe" --dir $toolsDir --clobber
        }
      }
      if (-not (Test-Path $cloudflared) -or (Get-Item $cloudflared).Length -lt 1MB) {
        throw "Failed to download cloudflared from the official GitHub release."
      }
    }
    $tunnelOut = Join-Path $logsDir "public-tunnel-$Port.out.log"
    $tunnelErr = Join-Path $logsDir "public-tunnel-$Port.err.log"
    $tunnelProcess = Start-Process `
      -FilePath $cloudflared `
      -ArgumentList @("tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate") `
      -RedirectStandardOutput $tunnelOut `
      -RedirectStandardError $tunnelErr `
      -WindowStyle Hidden `
      -PassThru
    $deadline = (Get-Date).AddSeconds(45)
    do {
      Start-Sleep -Seconds 1
      $logText = ((Get-Content -Raw -ErrorAction SilentlyContinue $tunnelOut), (Get-Content -Raw -ErrorAction SilentlyContinue $tunnelErr)) -join "`n"
      $match = [regex]::Match($logText, 'https://[a-z0-9-]+\.trycloudflare\.com')
      if ($match.Success) { $publicUrl = $match.Value }
    } while (-not $publicUrl -and -not $tunnelProcess.HasExited -and (Get-Date) -lt $deadline)
    if (-not $publicUrl) {
      throw "Cloudflare Tunnel did not return a public URL. See $tunnelErr"
    }
  }

  $state = [pscustomobject]@{
    backend_pid = $backend.Id
    tunnel_pid = if ($tunnelProcess) { $tunnelProcess.Id } else { $null }
    local_url = "http://127.0.0.1:$Port"
    public_url = $publicUrl
    credentials = $credentialsPath
    data = $dataDir
    started_at = (Get-Date).ToString("o")
  }
  $state | ConvertTo-Json | Set-Content -Encoding UTF8 $statePath

  Write-Host "LearnNote protected website is running." -ForegroundColor Green
  Write-Host "Local:       $($state.local_url)"
  if ($publicUrl) { Write-Host "Public:      $publicUrl" }
  Write-Host "Credentials: $credentialsPath"
  Write-Host "Data:        $dataDir"
  Write-Host "State:       $statePath"

  if ($Detach) {
    $completed = $true
    return
  }
  Write-Host "Press Ctrl+C to stop the preview."
  while (-not $backend.HasExited -and (-not $tunnelProcess -or -not $tunnelProcess.HasExited)) {
    Start-Sleep -Seconds 2
  }
} finally {
  if (-not ($Detach -and $completed)) {
    if ($tunnelProcess -and -not $tunnelProcess.HasExited) { Stop-Process -Id $tunnelProcess.Id -Force -ErrorAction SilentlyContinue }
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
  }
}
