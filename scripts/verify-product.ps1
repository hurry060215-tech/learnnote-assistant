param(
  [ValidateSet("edge", "chrome")]
  [string]$Browser = "edge",
  [switch]$SkipLocalSmoke,
  [switch]$SkipExtensionSmoke,
  [switch]$StrictDoctor,
  [switch]$KeepBrowser
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Get-FreeLocalPort {
  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
  try {
    $listener.Start()
    return $listener.LocalEndpoint.Port
  }
  finally {
    $listener.Stop()
  }
}

function Invoke-Step {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [scriptblock]$Action
  )

  Write-Host ""
  Write-Host "==> $Name"
  & $Action
  if ($LASTEXITCODE -ne 0) {
    throw "$Name failed with exit code $LASTEXITCODE"
  }
}

Set-Location $projectRoot

Invoke-Step "doctor" {
  $doctorArgs = @{}
  if ($StrictDoctor) {
    $doctorArgs["Strict"] = $true
  }
  & (Join-Path $projectRoot "scripts\doctor.ps1") @doctorArgs
}

if (-not $SkipLocalSmoke) {
  Invoke-Step "local backend/sample smoke" {
    $backendPort = Get-FreeLocalPort
    $samplesPort = Get-FreeLocalPort
    & (Join-Path $projectRoot "scripts\e2e-local-smoke.ps1") -BackendPort $backendPort -SamplesPort $samplesPort
  }
}

if (-not $SkipExtensionSmoke) {
  Invoke-Step "real browser extension smoke ($Browser)" {
    $extensionArgs = @{
      BackendPort = 0
      SamplesPort = 0
      DebugPort = 0
      Browser = $Browser
    }
    if ($KeepBrowser) {
      $extensionArgs["KeepBrowser"] = $true
    }
    & (Join-Path $projectRoot "scripts\e2e-extension-smoke.ps1") @extensionArgs
  }
}

Write-Host ""
Write-Host "Product verification passed."
