param(
  [string]$InstallerPath = "LearnNote-Setup-x64.exe"
)

$ErrorActionPreference = "Stop"
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$smokeRoot = [System.IO.Path]::GetFullPath("D:\LearnNoteReleaseSmoke")
$runId = [guid]::NewGuid().ToString("N")
$installDir = Join-Path $smokeRoot "app-$runId"
$dataDir = Join-Path $smokeRoot "data-$runId"

if (-not $smokeRoot.StartsWith("D:\LearnNoteReleaseSmoke", [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "Unsafe release smoke root: $smokeRoot"
}

New-Item -ItemType Directory -Force -Path $installDir, $dataDir | Out-Null
$sentinel = Join-Path $dataDir "user-data-must-survive.txt"
Set-Content -LiteralPath $sentinel -Value "LearnNote release smoke" -Encoding UTF8

try {
  $install = Start-Process -FilePath $installer `
    -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=$installDir" `
    -WindowStyle Hidden -Wait -PassThru
  if ($install.ExitCode -ne 0) {
    throw "Installer exited with code $($install.ExitCode)."
  }

  $executable = Join-Path $installDir "LearnNote.exe"
  $manifest = Join-Path $installDir "extension\manifest.json"
  $releaseNotes = Join-Path $installDir "_internal\web\release-notes.json"
  $uninstaller = Join-Path $installDir "unins000.exe"
  foreach ($required in @($executable, $manifest, $releaseNotes, $uninstaller)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
      throw "Installed release is missing $required"
    }
  }

  $manifestData = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
  $releaseData = Get-Content -LiteralPath $releaseNotes -Raw -Encoding UTF8 | ConvertFrom-Json
  $version = [string]$manifestData.version
  if ([string]$releaseData.current -ne $version) {
    throw "Installed release notes version $($releaseData.current) does not match extension version $version."
  }
  $currentNote = @($releaseData.releases | Where-Object { [string]$_.version -eq $version }) | Select-Object -First 1
  if (-not $currentNote -or -not [string]$currentNote.title -or -not [string]$currentNote.summary) {
    throw "Installed release notes have no complete entry for v$version."
  }
  if (@($currentNote.highlights).Count -lt 1) {
    throw "Installed release notes for v$version must include at least one user-facing highlight."
  }

  Set-Content -LiteralPath (Join-Path $installDir "learnnote-config.json") `
    -Value (@{ data_dir = $dataDir } | ConvertTo-Json) -Encoding UTF8

  $help = Start-Process -FilePath $executable -ArgumentList "--help" `
    -WindowStyle Hidden -Wait -PassThru
  if ($help.ExitCode -ne 0) {
    throw "Installed LearnNote executable failed its startup check with code $($help.ExitCode)."
  }

  $uninstall = Start-Process -FilePath $uninstaller `
    -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" `
    -WindowStyle Hidden -Wait -PassThru
  if ($uninstall.ExitCode -ne 0) {
    throw "Uninstaller exited with code $($uninstall.ExitCode)."
  }
  if (-not (Test-Path -LiteralPath $sentinel -PathType Leaf)) {
    throw "Uninstall removed the configured user data directory."
  }

  Write-Host "PASS installer smoke: install, startup, extension, release notes, uninstall, data preservation"
}
finally {
  foreach ($target in @($installDir, $dataDir)) {
    $resolved = [System.IO.Path]::GetFullPath($target)
    if (-not $resolved.StartsWith("$smokeRoot\", [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing to clean unsafe path: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
      Remove-Item -LiteralPath $resolved -Recurse -Force
    }
  }
}
