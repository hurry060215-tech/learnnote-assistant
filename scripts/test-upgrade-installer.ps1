param(
  [Parameter(Mandatory = $true)]
  [string]$PreviousInstallerPath,
  [Parameter(Mandatory = $true)]
  [string]$CurrentInstallerPath,
  [string]$SmokeRoot = "D:\LearnNoteUpgradeSmoke"
)

$ErrorActionPreference = "Stop"
$safeBase = [System.IO.Path]::GetFullPath("D:\LearnNoteUpgradeSmoke")
$resolvedSmokeRoot = [System.IO.Path]::GetFullPath($SmokeRoot)

function Assert-SafeChildPath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$Description
  )

  $resolved = [System.IO.Path]::GetFullPath($Path)
  $prefix = $safeBase.TrimEnd("\") + "\"
  if (-not $resolved.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe $Description path outside $safeBase`: $resolved"
  }
  if ($resolved.Equals($safeBase, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use the smoke root itself as $Description."
  }
  return $resolved
}

function Resolve-Installer {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$Description
  )

  $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
  if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
    throw "$Description installer is not a file: $resolved"
  }
  if ([System.IO.Path]::GetExtension($resolved) -ne ".exe") {
    throw "$Description installer must be an .exe file: $resolved"
  }
  return $resolved
}

function Invoke-Installer {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,
    [Parameter(Mandatory = $true)]
    [string]$Description
  )

  $process = Start-Process -FilePath $Installer `
    -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=$InstallDir" `
    -WindowStyle Hidden -Wait -PassThru
  if ($process.ExitCode -ne 0) {
    throw "$Description installer exited with code $($process.ExitCode)."
  }
}

function Get-InstalledVersion {
  param([Parameter(Mandatory = $true)][string]$InstallDir)

  $manifestPath = Join-Path $InstallDir "extension\manifest.json"
  if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Installed extension manifest is missing: $manifestPath"
  }
  $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $versionText = [string]$manifest.version
  if (-not $versionText) {
    throw "Installed extension manifest has no version: $manifestPath"
  }
  try {
    return [version]$versionText
  } catch {
    throw "Installed extension version is invalid: $versionText"
  }
}

if (-not $resolvedSmokeRoot.Equals($safeBase, [System.StringComparison]::OrdinalIgnoreCase) -and
    -not $resolvedSmokeRoot.StartsWith($safeBase.TrimEnd("\") + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "SmokeRoot must be $safeBase or a child path: $resolvedSmokeRoot"
}
if ([System.IO.Path]::GetPathRoot($resolvedSmokeRoot) -ne "D:\") {
  throw "Upgrade smoke data must remain on the D drive: $resolvedSmokeRoot"
}

$previousInstaller = Resolve-Installer $PreviousInstallerPath "Previous"
$currentInstaller = Resolve-Installer $CurrentInstallerPath "Current"
$runId = [guid]::NewGuid().ToString("N")
$runRoot = Assert-SafeChildPath (Join-Path $resolvedSmokeRoot "run-$runId") "run root"
$installDir = Assert-SafeChildPath (Join-Path $runRoot "app") "install"
$dataDir = Assert-SafeChildPath (Join-Path $runRoot "external-data") "external data"
$configPath = Join-Path $installDir "learnnote-config.json"
$dataSentinel = Join-Path $dataDir "user-data-must-survive.txt"
$configSentinel = "upgrade-$runId"
$installed = $false

New-Item -ItemType Directory -Force -Path $installDir, $dataDir | Out-Null
Set-Content -LiteralPath $dataSentinel -Value $configSentinel -Encoding UTF8

try {
  Invoke-Installer $previousInstaller $installDir "Previous"
  $installed = $true

  foreach ($required in @(
    (Join-Path $installDir "LearnNote.exe"),
    (Join-Path $installDir "unins000.exe"),
    (Join-Path $installDir "extension\manifest.json")
  )) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
      throw "Previous installation is missing $required"
    }
  }

  $previousVersion = Get-InstalledVersion $installDir
  @{
    data_dir = $dataDir
    upgrade_sentinel = $configSentinel
    appearance = @{ theme = "teal"; density = "comfortable" }
  } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $configPath -Encoding UTF8
  $configBeforeUpgrade = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8

  Invoke-Installer $currentInstaller $installDir "Current"
  $currentVersion = Get-InstalledVersion $installDir
  if ($currentVersion -le $previousVersion) {
    throw "Current extension version $currentVersion must be newer than previous version $previousVersion."
  }

  if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw "Cover upgrade removed the local configuration file."
  }
  $configAfterUpgrade = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
  if ($configAfterUpgrade -ne $configBeforeUpgrade) {
    throw "Cover upgrade changed the local configuration file."
  }
  $parsedConfig = $configAfterUpgrade | ConvertFrom-Json
  if ([string]$parsedConfig.data_dir -ne $dataDir -or [string]$parsedConfig.upgrade_sentinel -ne $configSentinel) {
    throw "Cover upgrade did not preserve the configured external data path and sentinel."
  }
  if (-not (Test-Path -LiteralPath $dataSentinel -PathType Leaf)) {
    throw "Cover upgrade removed the external data sentinel."
  }

  $executable = Join-Path $installDir "LearnNote.exe"
  $startup = Start-Process -FilePath $executable -ArgumentList "--help" `
    -WindowStyle Hidden -Wait -PassThru
  if ($startup.ExitCode -ne 0) {
    throw "Upgraded LearnNote executable failed its startup check with code $($startup.ExitCode)."
  }

  $uninstaller = Join-Path $installDir "unins000.exe"
  $uninstall = Start-Process -FilePath $uninstaller `
    -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" `
    -WindowStyle Hidden -Wait -PassThru
  if ($uninstall.ExitCode -ne 0) {
    throw "Current uninstaller exited with code $($uninstall.ExitCode)."
  }
  $installed = $false
  if (-not (Test-Path -LiteralPath $dataSentinel -PathType Leaf)) {
    throw "Uninstall removed the configured external data directory."
  }
  if ((Get-Content -LiteralPath $dataSentinel -Raw -Encoding UTF8).Trim() -ne $configSentinel) {
    throw "External data sentinel contents changed during upgrade or uninstall."
  }

  Write-Host "PASS cover upgrade: $previousVersion -> $currentVersion; config, external data, extension update, startup, and uninstall verified"
}
finally {
  if ($installed) {
    $uninstaller = Join-Path $installDir "unins000.exe"
    if (Test-Path -LiteralPath $uninstaller -PathType Leaf) {
      $cleanupUninstall = Start-Process -FilePath $uninstaller `
        -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" `
        -WindowStyle Hidden -Wait -PassThru
      if ($cleanupUninstall.ExitCode -ne 0) {
        Write-Warning "Cleanup uninstaller exited with code $($cleanupUninstall.ExitCode)."
      }
    }
  }

  $safeRunRoot = Assert-SafeChildPath $runRoot "cleanup"
  if (Test-Path -LiteralPath $safeRunRoot) {
    Remove-Item -LiteralPath $safeRunRoot -Recurse -Force
  }
}
