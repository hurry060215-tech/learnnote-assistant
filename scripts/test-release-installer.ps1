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
  $uninstaller = Join-Path $installDir "unins000.exe"
  foreach ($required in @($executable, $manifest, $uninstaller)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
      throw "Installed release is missing $required"
    }
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

  Write-Host "PASS installer smoke: install, executable startup, extension files, uninstall, data preservation"
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
