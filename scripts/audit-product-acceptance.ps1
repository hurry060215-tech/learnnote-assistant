param(
  [ValidateSet("edge", "chrome")]
  [string]$Browser = "edge",
  [string]$YtdlpUrl = "https://samplelib.com/sample-mp4.html",
  [string]$LearningUrl = "",
  [switch]$SkipExtensionSmoke,
  [switch]$SkipYtdlpAudit,
  [switch]$SkipLearningMock,
  [switch]$SkipReadiness,
  [switch]$StrictDoctor,
  [switch]$RequireRealSiteAudits,
  [switch]$KeepBrowser
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dataDir = Join-Path $projectRoot "data"
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runDir = Join-Path $dataDir "test-runs\product-acceptance\$runStamp"
$summaryPath = Join-Path $runDir "summary.md"

function New-RunDir {
  New-Item -ItemType Directory -Force -Path $runDir | Out-Null
}

function Write-Summary {
  param([string]$Text)
  Add-Content -Encoding UTF8 -Path $summaryPath -Value $Text
}

function Invoke-AcceptanceStep {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [scriptblock]$Action,
    [switch]$Manual
  )

  Write-Host ""
  Write-Host "==> $Name"
  $started = Get-Date
  try {
    & $Action
    $exitCode = if ($LASTEXITCODE -is [int]) { $LASTEXITCODE } else { 0 }
    if ($exitCode -ne 0) {
      throw "$Name failed with exit code $exitCode"
    }
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    Write-Summary "- PASS $Name (${elapsed}s)"
  } catch {
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    if ($Manual) {
      Write-Summary "- MANUAL $Name (${elapsed}s): $($_.Exception.Message)"
      Write-Host "MANUAL: $($_.Exception.Message)" -ForegroundColor Yellow
      return
    }
    Write-Summary "- FAIL $Name (${elapsed}s): $($_.Exception.Message)"
    throw
  }
}

Set-Location $projectRoot
New-RunDir

@(
  "# LearnNote product acceptance gate",
  "",
  "- Time: $(Get-Date -Format o)",
  "- Project: $projectRoot",
  "- Browser: $Browser",
  "- Data: $dataDir",
  "- Yt-dlp URL: $YtdlpUrl",
  "- Learning URL: $(if ($LearningUrl) { $LearningUrl } else { "not provided; real logged-in learning-platform audit remains manual" })",
  "",
  "## Steps"
) | Set-Content -Encoding UTF8 -Path $summaryPath

Invoke-AcceptanceStep "doctor" {
  $doctorArgs = @{}
  if ($StrictDoctor) {
    $doctorArgs.Strict = $true
  }
  & (Join-Path $projectRoot "scripts\doctor.ps1") @doctorArgs
}

if (-not $SkipExtensionSmoke) {
  Invoke-AcceptanceStep "real browser extension smoke: local MP4/HLS/API/blob/learning mock" {
    $args = @{
      Browser = $Browser
      BackendPort = 0
      SamplesPort = 0
      DebugPort = 0
    }
    if ($KeepBrowser) {
      $args.KeepBrowser = $true
    }
    & (Join-Path $projectRoot "scripts\e2e-extension-smoke.ps1") @args
  }
} else {
  Write-Summary "- SKIP real browser extension smoke"
}

if (-not $SkipYtdlpAudit) {
  Invoke-AcceptanceStep "yt-dlp supported real-site task probe" {
    & (Join-Path $projectRoot "scripts\audit-real-site.ps1") $YtdlpUrl -TaskProbe -YtdlpProbe -RequireReady -TaskTimeout 180 -Browser $Browser
  }
} else {
  Write-Summary "- SKIP yt-dlp supported real-site task probe"
}

if (-not $SkipLearningMock) {
  Invoke-AcceptanceStep "learning-platform local mock gate" {
    & (Join-Path $projectRoot "scripts\audit-learning-platform.ps1") -Mock -Browser $Browser -BackendPort 0 -DebugPort 0
  }
} else {
  Write-Summary "- SKIP learning-platform local mock gate"
}

if ($LearningUrl) {
  Invoke-AcceptanceStep "logged-in learning-platform real gate" {
    $args = @{
      Url = $LearningUrl
      Browser = $Browser
      BackendPort = 0
      DebugPort = 0
    }
    if ($KeepBrowser) {
      $args.KeepBrowser = $true
    }
    & (Join-Path $projectRoot "scripts\audit-learning-platform.ps1") @args
  } -Manual:$false
} else {
  Write-Summary "- MANUAL logged-in learning-platform real gate: provide -LearningUrl after logging in and opening the lesson page"
}

if (-not $SkipReadiness) {
  Invoke-AcceptanceStep "product readiness matrix" {
    $args = @{}
    if ($RequireRealSiteAudits) {
      $args.RequireRealSiteAudits = $true
    }
    & (Join-Path $projectRoot "scripts\audit-product-readiness.ps1") @args
  }
} else {
  Write-Summary "- SKIP product readiness matrix"
}

@(
  "",
  "## Result",
  "",
  "Acceptance report: $summaryPath",
  "",
  "The only expected manual row without -LearningUrl is the real logged-in learning-platform audit."
) | Add-Content -Encoding UTF8 -Path $summaryPath

Write-Host ""
Write-Host "Product acceptance gate finished." -ForegroundColor Green
Write-Host "Report: $summaryPath"
