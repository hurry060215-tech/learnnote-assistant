param(
  [int]$Port = 8765,
  [int]$SamplesPort = 8777,
  [ValidateSet("edge", "chrome")]
  [string]$Browser = "edge",
  [switch]$Json
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$doctorScript = Join-Path $projectRoot "scripts\doctor.ps1"
$extensionDir = Join-Path $projectRoot "extension"
$dataDir = Join-Path $projectRoot "data"
$backendUrl = "http://127.0.0.1:$Port"
$samplesUrl = "http://127.0.0.1:$SamplesPort"

function Get-DoctorChecks {
  $output = & $doctorScript -Json 2>&1
  $exitCode = $LASTEXITCODE
  $text = ($output | Out-String).Trim()
  try {
    $checks = $text | ConvertFrom-Json
  } catch {
    throw "Unable to parse doctor JSON output: $text"
  }
  return [pscustomobject]@{
    ExitCode = $exitCode
    Checks = @($checks)
  }
}

function Find-Check {
  param(
    [array]$Checks,
    [string]$Name
  )
  return $Checks | Where-Object { $_.name -eq $Name } | Select-Object -First 1
}

function Status-Text {
  param($Check)
  if (-not $Check) { return "MISSING" }
  return $Check.status
}

function Write-StatusLine {
  param(
    [string]$Label,
    $Check
  )
  $status = Status-Text $Check
  $color = if ($status -eq "PASS") { "Green" } elseif ($status -eq "WARN") { "Yellow" } else { "Red" }
  $detail = if ($Check -and $Check.detail) { $Check.detail } else { "-" }
  Write-Host ("[{0}] {1}: {2}" -f $status, $Label, $detail) -ForegroundColor $color
  if ($Check.fix) {
    Write-Host ("      fix: {0}" -f $Check.fix) -ForegroundColor DarkYellow
  }
}

$doctor = Get-DoctorChecks
$checks = @($doctor.Checks)
$fails = @($checks | Where-Object { $_.status -eq "FAIL" })
$warns = @($checks | Where-Object { $_.status -eq "WARN" })

if ($Json) {
  [pscustomobject]@{
    project = $projectRoot
    data = $dataDir
    backend = $backendUrl
    samples = $samplesUrl
    extension = $extensionDir
    browser = $Browser
    fail_count = $fails.Count
    warn_count = $warns.Count
    checks = $checks
    commands = @{
      start = ".\start-learnnote.ps1"
      start_with_samples = ".\start-learnnote.ps1 -WithSamples"
      install_asr = ".\start-learnnote.ps1 -InstallAsr"
      verify = ".\scripts\verify-product.ps1 -Browser $Browser"
    }
  } | ConvertTo-Json -Depth 6
  exit $doctor.ExitCode
}

Write-Host "LearnNote first-run checklist" -ForegroundColor Green
Write-Host "Project:   $projectRoot"
Write-Host "Data:      $dataDir"
Write-Host "Backend:   $backendUrl"
Write-Host "Samples:   $samplesUrl"
Write-Host "Extension: $extensionDir"
Write-Host ""

Write-Host "Readiness" -ForegroundColor Cyan
Write-StatusLine "Project location" (Find-Check $checks "project location")
Write-StatusLine "Python environment" (Find-Check $checks "Python environment")
Write-StatusLine "Backend runtime" (Find-Check $checks "backend runtime")
Write-StatusLine "Browser extension" (Find-Check $checks "browser extension")
Write-StatusLine $Browser (Find-Check $checks $Browser)
Write-StatusLine "faster-whisper ASR" (Find-Check $checks "faster-whisper ASR")
Write-StatusLine "Multimodal API" (Find-Check $checks "multimodal API")

Write-Host ""
if ($fails.Count) {
  Write-Host "Required fixes before startup" -ForegroundColor Red
  foreach ($item in $fails) {
    Write-Host ("- {0}: {1}" -f $item.name, $item.detail) -ForegroundColor Red
    if ($item.fix) { Write-Host ("  fix: {0}" -f $item.fix) -ForegroundColor DarkYellow }
  }
} else {
  Write-Host "Startup path" -ForegroundColor Cyan
  Write-Host "1. Start backend:"
  Write-Host "   .\start-learnnote.ps1"
  Write-Host "2. Load unpacked extension:"
  Write-Host "   $extensionDir"
  Write-Host "3. In Chrome/Edge extensions page, enable Developer Mode and Load unpacked."
  Write-Host "4. Put this backend URL in Side Panel settings if needed:"
  Write-Host "   $backendUrl"
  Write-Host "5. For local sample pages:"
  Write-Host "   .\start-learnnote.ps1 -WithSamples"
  Write-Host "   $samplesUrl"
  Write-Host "6. Product verification:"
  Write-Host "   .\scripts\verify-product.ps1 -Browser $Browser"
}

if ($warns.Count) {
  Write-Host ""
  Write-Host "Optional capability warnings" -ForegroundColor Yellow
  foreach ($item in $warns) {
    Write-Host ("- {0}: {1}" -f $item.name, $item.detail) -ForegroundColor Yellow
    if ($item.fix) { Write-Host ("  fix: {0}" -f $item.fix) -ForegroundColor DarkYellow }
  }
}

Write-Host ""
Write-Host "Boundaries" -ForegroundColor Cyan
Write-Host "- Runtime files stay under the D-drive project data directory."
Write-Host "- The extension loads from the local extension directory."
Write-Host "- The app directly downloads accessible media only; it does not record tabs or bypass DRM."

exit $doctor.ExitCode
