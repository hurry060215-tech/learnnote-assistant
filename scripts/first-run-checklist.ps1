param(
  [int]$Port = 8765,
  [int]$SamplesPort = 8777,
  [ValidateSet("edge", "chrome")]
  [string]$Browser = "edge",
  [switch]$Json,
  [switch]$WriteGuide,
  [string]$GuidePath = ""
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

function Test-CheckPass {
  param($Check)
  return $Check -and $Check.status -eq "PASS"
}

$doctor = Get-DoctorChecks
$checks = @($doctor.Checks)
$fails = @($checks | Where-Object { $_.status -eq "FAIL" })
$warns = @($checks | Where-Object { $_.status -eq "WARN" })
$asrCheck = Find-Check $checks "faster-whisper ASR"
$apiCheck = Find-Check $checks "multimodal API"
$runtimeCheck = Find-Check $checks "backend runtime"
$extensionCheck = Find-Check $checks "browser extension"
$browserCheck = Find-Check $checks $Browser
$baseReady = $fails.Count -eq 0
$localAsrReady = Test-CheckPass $asrCheck
$visionReady = Test-CheckPass $apiCheck
$browserReady = (Test-CheckPass $extensionCheck) -and (Test-CheckPass $browserCheck)
$guideOutputPath = if ($GuidePath) { $GuidePath } else { Join-Path $dataDir "first-run-guide.md" }
$samplePages = [ordered]@{
  mp4 = "$samplesUrl/mp4.html"
  hls = "$samplesUrl/hls.html"
  blob_iframe = "$samplesUrl/blob-iframe.html"
  post_play_api = "$samplesUrl/post-api.html"
  chaoxing_mock = "$samplesUrl/chaoxing-mock.html"
}

function New-FirstRunGuide {
  param(
    [string]$Path,
    [array]$Checks,
    [array]$Fails,
    [array]$Warns
  )

  $parent = Split-Path -Parent $Path
  if ($parent) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
  }
  $baseState = if ($Fails.Count -eq 0) { "ready" } else { "blocked" }
  $asrState = if ($localAsrReady) { "ready" } else { "optional warning" }
  $visionState = if ($visionReady) { "ready" } else { "optional warning" }
  $browserState = if ($browserReady) { "ready" } else { "check required" }
  $requiredFixes = @($Fails | ForEach-Object {
    $fix = if ($_.fix) { " | fix: $($_.fix)" } else { "" }
    "- $($_.name): $($_.detail)$fix"
  })
  if (-not $requiredFixes.Count) {
    $requiredFixes = @("- None. Base workflow can start.")
  }
  $optionalWarnings = @($Warns | ForEach-Object {
    $fix = if ($_.fix) { " | fix: $($_.fix)" } else { "" }
    "- $($_.name): $($_.detail)$fix"
  })
  if (-not $optionalWarnings.Count) {
    $optionalWarnings = @("- None.")
  }
  $tick = [char]96
  $fence = "$tick$tick$tick"
  $lines = @(
    "# LearnNote First-Run Guide",
    "",
    "Generated: $(Get-Date -Format s)",
    "",
    "## Local Paths",
    "",
    "- Project: $tick$projectRoot$tick",
    "- Data: $tick$dataDir$tick",
    "- Backend: $tick$backendUrl$tick",
    "- Backend origin: $tick$backendUrl$tick",
    "- Extension: $tick$extensionDir$tick",
    "- Sample site: $tick$samplesUrl$tick",
    "",
    "## Readiness",
    "",
    "- Base workflow: $baseState",
    "- Browser extension: $browserState",
    "- Local ASR: $asrState",
    "- Visual LLM: $visionState",
    "",
    "## Required Fixes",
    "",
    $requiredFixes,
    "",
    "## Optional Capability Warnings",
    "",
    $optionalWarnings,
    "",
    "## First Use",
    "",
    "1. Start backend and sample pages:",
    "",
    "$($fence)powershell",
    "cd $projectRoot",
    ".\start-learnnote.ps1 -WithSamples",
    $fence,
    "",
    "2. Load the browser extension:",
    "",
    "- Open ${tick}edge://extensions${tick} or ${tick}chrome://extensions${tick}.",
    "- Enable Developer Mode.",
    "- Click ${tick}Load unpacked${tick}.",
    "- Select $tick$extensionDir$tick.",
    "- Open the Side Panel and keep backend URL as $tick$backendUrl$tick.",
    "",
    "3. Verify the loop with a local page:",
    "",
    "- MP4: $($samplePages.mp4)",
    "- HLS: $($samplePages.hls)",
    "- POST play API: $($samplePages.post_play_api)",
    "- Blob iframe fallback: $($samplePages.blob_iframe)",
    "- Chaoxing-style mock: $($samplePages.chaoxing_mock)",
    "",
    "Play a sample for a few seconds, click the Side Panel summarize or preflight action, then check the generated note, transcript, slices, and diagnostics tabs.",
    "",
    "4. Run product verification after code changes:",
    "",
    "$($fence)powershell",
    ".\scripts\verify-product.ps1 -Browser $Browser",
    $fence,
    "",
    "## Optional Upgrades",
    "",
    "Install local ASR:",
    "",
    "$($fence)powershell",
    ".\start-learnnote.ps1 -InstallAsr",
    $fence,
    "",
    "Configure a visual summary API for the current PowerShell session:",
    "",
    "$($fence)powershell",
    '$env:LEARNNOTE_LLM_API_KEY="..."',
    '$env:LEARNNOTE_LLM_BASE_URL="https://api.openai.com/v1"',
    '$env:LEARNNOTE_LLM_MODEL="gpt-4.1-mini"',
    $fence,
    "",
    "## Real-Site Audit",
    "",
    "Use this for YouTube/Bilibili/Chaoxing or another live site after the extension is loaded:",
    "",
    "$($fence)powershell",
    ".\scripts\audit-real-site.ps1 `"<url>`" -Preflight -RequireReady",
    $fence,
    "",
    "For logged-in learning pages, use a D-drive browser profile:",
    "",
    "$($fence)powershell",
    ".\scripts\audit-real-site.ps1 `"https://mooc1.chaoxing.com/...`" -ProfileDir `"$dataDir\browser-profiles\chaoxing`" -InteractiveLogin -Preflight -RequireReady -RequireLearningProfile",
    $fence,
    "",
    "## Boundaries",
    "",
    "- Runtime files stay under the D-drive project data directory.",
    "- Current-page extraction directly downloads accessible media only.",
    "- The app does not record tabs, bypass DRM, spoof progress, answer questions automatically, or collect cookies in the background."
  )
  Set-Content -LiteralPath $Path -Encoding UTF8 -Value $lines
  return (Resolve-Path $Path).Path
}

$writtenGuidePath = ""
if ($WriteGuide) {
  $writtenGuidePath = New-FirstRunGuide -Path $guideOutputPath -Checks $checks -Fails $fails -Warns $warns
}

if ($Json) {
  [pscustomobject]@{
    project = $projectRoot
    data = $dataDir
    backend = $backendUrl
    backend_origin = $backendUrl
    samples = $samplesUrl
    extension = $extensionDir
    browser = $Browser
    guide_path = $writtenGuidePath
    runtime_paths = @{
      data = $dataDir
      data_drive = ([System.IO.DirectoryInfo]$dataDir).Root.FullName
      backend_origin = $backendUrl
      extension = $extensionDir
    }
    fail_count = $fails.Count
    warn_count = $warns.Count
    readiness = @{
      base_workflow = if ($baseReady) { "ready" } else { "blocked" }
      browser_extension = if ($browserReady) { "ready" } else { "check_required" }
      local_asr = if ($localAsrReady) { "ready" } else { "optional_warn" }
      visual_llm = if ($visionReady) { "ready" } else { "optional_warn" }
      d_drive_runtime = if (Test-CheckPass $runtimeCheck) { "ready" } else { "check_required" }
    }
    sample_pages = $samplePages
    checks = $checks
    commands = @{
      start = ".\start-learnnote.ps1"
      start_with_samples = ".\start-learnnote.ps1 -WithSamples"
      install_asr = ".\start-learnnote.ps1 -InstallAsr"
      verify = ".\scripts\verify-product.ps1 -Browser $Browser"
      audit_real_site = ".\scripts\audit-real-site.ps1 <url> -Preflight"
      write_guide = ".\scripts\first-run-checklist.ps1 -WriteGuide"
      set_visual_api = @(
        '$env:LEARNNOTE_LLM_API_KEY="..."',
        '$env:LEARNNOTE_LLM_BASE_URL="https://api.openai.com/v1"',
        '$env:LEARNNOTE_LLM_MODEL="gpt-4.1-mini"'
      )
    }
  } | ConvertTo-Json -Depth 6
  exit $doctor.ExitCode
}

Write-Host "LearnNote first-run checklist" -ForegroundColor Green
Write-Host "Project:   $projectRoot"
Write-Host "Data:      $dataDir"
Write-Host "Backend:   $backendUrl"
Write-Host "Origin:    $backendUrl"
Write-Host "Samples:   $samplesUrl"
Write-Host "Extension: $extensionDir"
if ($writtenGuidePath) {
  Write-Host "Guide:     $writtenGuidePath"
}
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
  Write-Host "Capability modes" -ForegroundColor Cyan
  Write-Host ("- Base workflow: {0}" -f $(if ($baseReady) { "ready; current-page direct download, local upload, deterministic notes can run" } else { "blocked by required failures" }))
  Write-Host ("- Browser extension: {0}" -f $(if ($browserReady) { "ready; load unpacked extension and use Side Panel" } else { "check browser path or extension manifest" }))
  Write-Host ("- Local ASR: {0}" -f $(if ($localAsrReady) { "ready; faster-whisper can transcribe locally" } else { "optional WARN; install with .\start-learnnote.ps1 -InstallAsr or use subtitle/remote ASR fallback" }))
  Write-Host ("- Visual LLM: {0}" -f $(if ($visionReady) { "ready; multimodal summaries can use configured API" } else { "optional WARN; without API key, notes use local deterministic fallback plus frame indexes" }))
  Write-Host ""
  Write-Host "Startup path" -ForegroundColor Cyan
  Write-Host "0. Optional: write this machine-specific guide to D-drive data:"
  Write-Host "   .\scripts\first-run-checklist.ps1 -WriteGuide"
  Write-Host "1. Start backend:"
  Write-Host "   .\start-learnnote.ps1"
  Write-Host "2. Load unpacked extension:"
  Write-Host "   $extensionDir"
  Write-Host "3. In Chrome/Edge extensions page, enable Developer Mode and Load unpacked."
  Write-Host "4. Put this backend URL in Side Panel settings if needed:"
  Write-Host "   $backendUrl"
  Write-Host "   The launcher also sets LEARNNOTE_BACKEND_ORIGIN to this URL for the current session."
  Write-Host "5. For local sample pages:"
  Write-Host "   .\start-learnnote.ps1 -WithSamples"
  Write-Host "   $samplesUrl"
  Write-Host "6. Product verification:"
  Write-Host "   .\scripts\verify-product.ps1 -Browser $Browser"
  Write-Host ""
  Write-Host "Local sample pages" -ForegroundColor Cyan
  Write-Host "Start both backend and samples:"
  Write-Host "   .\start-learnnote.ps1 -WithSamples"
  Write-Host "Then open one of:"
  Write-Host "   $($samplePages.mp4)          MP4"
  Write-Host "   $($samplePages.hls)          HLS"
  Write-Host "   $($samplePages.post_play_api)     POST play API"
  Write-Host "   $($samplePages.blob_iframe)  blob iframe"
  Write-Host "   $($samplePages.chaoxing_mock)  Chaoxing-style mock"
  Write-Host ""
  Write-Host "Optional upgrades" -ForegroundColor Cyan
  Write-Host "Local ASR:"
  Write-Host "   .\start-learnnote.ps1 -InstallAsr"
  Write-Host "Visual summary API for this PowerShell session:"
  Write-Host '   $env:LEARNNOTE_LLM_API_KEY="..."'
  Write-Host '   $env:LEARNNOTE_LLM_BASE_URL="https://api.openai.com/v1"'
  Write-Host '   $env:LEARNNOTE_LLM_MODEL="gpt-4.1-mini"'
  Write-Host "Real-site audit:"
  Write-Host "   .\scripts\audit-real-site.ps1 <url> -Preflight"
}

if ($writtenGuidePath) {
  Write-Host ""
  Write-Host "Guide written" -ForegroundColor Green
  Write-Host "  $writtenGuidePath"
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
