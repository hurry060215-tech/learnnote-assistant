param(
  [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$extensionDir = Join-Path $root "extension"

if (-not $OutputPath) {
  $OutputPath = Join-Path $root "dist\LearnNote-Browser-Extension.zip"
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)

$files = @(
  "manifest.json",
  "background.js",
  "content.js",
  "page_hook.js",
  "sidepanel.html",
  "sidepanel.css",
  "sidepanel.js",
  "INSTALL.txt"
)
$directories = @(
  "icons"
)

$manifestPath = Join-Path $extensionDir "manifest.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.manifest_version -ne 3) {
  throw "Only a Manifest V3 extension can be packaged."
}

$packageFiles = foreach ($name in $files) {
  $path = Join-Path $extensionDir $name
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Missing extension package file: $path"
  }
  $path
}
$packageDirectories = foreach ($name in $directories) {
  $path = Join-Path $extensionDir $name
  if (-not (Test-Path -LiteralPath $path -PathType Container)) {
    throw "Missing extension package directory: $path"
  }
  $path
}

$requiredIconSizes = @(16, 32, 48, 128)
foreach ($size in $requiredIconSizes) {
  $iconPath = Join-Path $extensionDir "icons\icon$size.png"
  if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw "Missing extension icon: $iconPath"
  }
}

$outputDir = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
if (Test-Path -LiteralPath $OutputPath) {
  Remove-Item -LiteralPath $OutputPath -Force
}

Compress-Archive -LiteralPath ($packageFiles + $packageDirectories) -DestinationPath $OutputPath -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()

[pscustomobject]@{
  path = $OutputPath
  version = $manifest.version
  sha256 = $hash
  bytes = (Get-Item -LiteralPath $OutputPath).Length
} | ConvertTo-Json -Compress
