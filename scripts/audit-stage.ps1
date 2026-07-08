param(
  [string]$Base = "HEAD",
  [switch]$LastCommit,
  [switch]$All
)

$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repo

function Get-ChangedFiles {
  if ($All) {
    return @(git ls-files)
  }
  if ($LastCommit) {
    return @(git diff --name-only HEAD~1 HEAD)
  }

  $files = @()
  $files += git diff --name-only $Base --
  $files += git diff --name-only --cached
  $files += git ls-files --others --exclude-standard
  $files = @($files | Where-Object { $_ } | Sort-Object -Unique)
  if ($files.Count -gt 0) {
    return $files
  }

  Write-Host "No working tree changes found; auditing the last commit." -ForegroundColor DarkGray
  return @(git diff --name-only HEAD~1 HEAD)
}

function Resolve-Python {
  if ($env:LEARNNOTE_AUDIT_PYTHON -and (Test-Path $env:LEARNNOTE_AUDIT_PYTHON)) {
    return $env:LEARNNOTE_AUDIT_PYTHON
  }
  foreach ($candidate in @(
    (Join-Path $repo ".venv\Scripts\python.exe"),
    (Join-Path $repo "backend\.venv\Scripts\python.exe")
  )) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }
  return "python"
}

function Invoke-Step {
  param(
    [string]$Name,
    [scriptblock]$Command
  )
  Write-Host "==> $Name" -ForegroundColor Cyan
  $global:LASTEXITCODE = 0
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "Step failed with exit code ${LASTEXITCODE}: $Name"
  }
}

function Test-Any {
  param([string[]]$Patterns)
  foreach ($file in $changed) {
    foreach ($pattern in $Patterns) {
      if ($file -like $pattern) {
        return $true
      }
    }
  }
  return $false
}

$changed = @(Get-ChangedFiles)
if ($changed.Count -eq 0) {
  Write-Host "No files to audit." -ForegroundColor Yellow
  exit 0
}

Write-Host "Auditing files:" -ForegroundColor DarkGray
$changed | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }

$python = Resolve-Python
$env:PYTHONPATH = "backend"
$ran = $false

if (Test-Any @("backend/app/*.py", "backend/tests/*.py")) {
  $ran = $true
  Invoke-Step "Python compile check" { & $python -m compileall -q backend\app }
}

if (Test-Any @("backend/app/downloader.py", "backend/app/models.py", "backend/tests/test_core.py")) {
  $ran = $true
  Invoke-Step "Core downloader/resource tests" { & $python -m unittest backend.tests.test_core }
}

if (Test-Any @("backend/app/downloader.py", "backend/tests/test_downloader_priority.py")) {
  $ran = $true
  Invoke-Step "Downloader priority tests" { & $python -m unittest backend.tests.test_downloader_priority }
}

if (Test-Any @("backend/app/main.py", "backend/app/processor.py", "backend/tests/test_api_pipeline.py")) {
  $ran = $true
  Invoke-Step "API pipeline tests" { & $python -m unittest backend.tests.test_api_pipeline }
}

if (Test-Any @("extension/background.js", "extension/tests/background_*.test.mjs")) {
  $ran = $true
  Invoke-Step "Background syntax" { node --check extension\background.js }
  foreach ($test in @(
    "extension\tests\background_request_headers.test.mjs",
    "extension\tests\background_target_tab.test.mjs",
    "extension\tests\background_mediasource_rank.test.mjs",
    "extension\tests\background_context_update_notify.test.mjs",
    "extension\tests\background_download_export.test.mjs",
    "extension\tests\background_action_intent.test.mjs"
  )) {
    Invoke-Step $test { node $test }
  }
}

if (Test-Any @("extension/manifest.json", "extension/tests/manifest_*.test.mjs")) {
  $ran = $true
  Invoke-Step "Extension manifest permissions" { node extension\tests\manifest_permissions.test.mjs }
}

if (Test-Any @("extension/sidepanel.js", "extension/sidepanel.css", "extension/sidepanel.html", "extension/tests/sidepanel_*.test.mjs")) {
  $ran = $true
  Invoke-Step "Side Panel syntax" { node --check extension\sidepanel.js }
  foreach ($test in @(
    "extension\tests\sidepanel_preflight_start.test.mjs",
    "extension\tests\sidepanel_preflight_fallback.test.mjs",
    "extension\tests\sidepanel_page_preflight_continues_queue.test.mjs",
    "extension\tests\sidepanel_start_page_preflight_report.test.mjs",
    "extension\tests\sidepanel_direct_response_preflight.test.mjs",
    "extension\tests\sidepanel_download_only.test.mjs",
    "extension\tests\sidepanel_failed_fallback_result.test.mjs",
    "extension\tests\sidepanel_local_upload.test.mjs",
    "extension\tests\sidepanel_run_preflight_blob_fallback.test.mjs",
    "extension\tests\sidepanel_source_switcher.test.mjs",
    "extension\tests\sidepanel_slices_tab.test.mjs",
    "extension\tests\sidepanel_markdown.test.mjs"
  )) {
    Invoke-Step $test { node $test }
  }
}

if (Test-Any @("extension/content.js", "extension/page_hook.js", "extension/tests/content_*.test.mjs", "extension/tests/page_hook_*.test.mjs")) {
  $ran = $true
  Invoke-Step "Content script syntax" { node --check extension\content.js }
  Invoke-Step "Page hook syntax" { node --check extension\page_hook.js }
  foreach ($test in @(
    "extension\tests\content_static_hints.test.mjs",
    "extension\tests\content_shadow_dom.test.mjs",
    "extension\tests\page_hook_arraybuffer_text.test.mjs",
    "extension\tests\page_hook_late_global_config.test.mjs",
    "extension\tests\page_hook_websocket_eventsource.test.mjs",
    "extension\tests\page_hook_response_json.test.mjs",
    "extension\tests\page_hook_mediasource.test.mjs",
    "extension\tests\page_hook_media_element.test.mjs"
  )) {
    Invoke-Step $test { node $test }
  }
}

if (Test-Any @("web/*.js", "web/*.css", "web/*.html")) {
  $ran = $true
  Invoke-Step "Web UI syntax" { node --check web\app.js }
  Invoke-Step "Web UI render tests" { node web\tests\markdown_render.test.mjs }
}

Invoke-Step "Whitespace check" { git diff --check }

if (-not $ran) {
  Write-Host "Only docs or unsupported file types changed; whitespace check completed." -ForegroundColor Green
} else {
  Write-Host "Stage audit passed." -ForegroundColor Green
}
