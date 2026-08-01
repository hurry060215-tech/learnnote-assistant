param(
    [string]$OutputDirectory = "D:\LearnNote\releases\obsidian"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pluginRoot = Join-Path $repoRoot "integrations\obsidian-learnnote"
$manifest = Get-Content (Join-Path $pluginRoot "manifest.json") -Raw | ConvertFrom-Json
$version = [string]$manifest.version
$artifactName = "LearnNote-Obsidian-$version.zip"
$artifactPath = Join-Path $OutputDirectory $artifactName
$staging = Join-Path $OutputDirectory "learnnote-assistant"

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is required to build the Obsidian plugin."
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $staging | Out-Null
if (-not $env:npm_config_cache) {
    $env:npm_config_cache = Join-Path (Split-Path -Parent $OutputDirectory) "npm-cache"
}

Push-Location $pluginRoot
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    npm run verify
    if ($LASTEXITCODE -ne 0) { throw "Obsidian plugin verification failed" }
} finally {
    Pop-Location
}

$required = @("main.js", "manifest.json", "styles.css")
foreach ($file in $required) {
    $source = Join-Path $pluginRoot $file
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Missing Obsidian release file: $source"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $staging $file) -Force
}
Copy-Item -LiteralPath (Join-Path $pluginRoot "README.md") -Destination (Join-Path $staging "README.md") -Force
Copy-Item -LiteralPath (Join-Path $repoRoot "LICENSE") -Destination (Join-Path $staging "LICENSE") -Force

Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $artifactPath -Force
$hash = Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256
$checksumPath = Join-Path $OutputDirectory "SHA256SUMS.txt"
"$($hash.Hash.ToLowerInvariant())  $artifactName" | Set-Content -LiteralPath $checksumPath -Encoding ascii

Write-Host "Obsidian plugin package: $artifactPath"
Write-Host "SHA256: $($hash.Hash.ToLowerInvariant())"
