param(
    [Parameter(Mandatory)][string]$Tag,
    [Parameter(Mandatory)][string]$Repository,
    [string]$ChecksumFile = "SHA256SUMS.txt",
    [switch]$ValidateOnly
)
$ErrorActionPreference = "Stop"
if ($Tag -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9.-]+)?$') { throw "Invalid release tag" }
if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw "Invalid repository" }
$root = (Get-Location).Path
$expected = @{}
foreach ($line in Get-Content -LiteralPath $ChecksumFile) {
    if ($line -notmatch '^([a-fA-F0-9]{64})\s{2}([A-Za-z0-9_.-]+)$') { throw "Invalid checksum entry" }
    $name = $Matches[2]
    if ($expected.ContainsKey($name)) { throw "Duplicate asset: $name" }
    $expected[$name] = $Matches[1].ToLowerInvariant()
    $asset = Join-Path $root $name
    if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) { throw "Missing asset: $name" }
    if ((Get-FileHash -LiteralPath $asset -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected[$name]) { throw "Checksum mismatch: $name" }
}
if ($expected.Count -lt 3) { throw "Release manifest is incomplete" }
if ($ValidateOnly) { Write-Output "Validated $($expected.Count) release assets; no network calls"; return }

$lookup = & gh release view $Tag --repo $Repository --json isDraft,tagName 2>&1
if ($LASTEXITCODE -eq 0) {
    $release = ($lookup -join "`n") | ConvertFrom-Json
} elseif (($lookup -join " ") -match 'release not found|HTTP 404') {
    & gh release create $Tag --repo $Repository --draft --verify-tag --generate-notes --title "LearnNote $Tag"
    if ($LASTEXITCODE -ne 0) { throw "Could not create draft release" }
    $release = @{ isDraft = $true }
} else {
    throw "Could not inspect release; no publishing changes were made"
}
if ($release.isDraft) {
    foreach ($name in $expected.Keys) {
        & gh release upload $Tag (Join-Path $root $name) --repo $Repository --clobber
        if ($LASTEXITCODE -ne 0) { throw "Draft upload failed for $name; rerun to resume" }
    }
    & gh release upload $Tag $ChecksumFile --repo $Repository --clobber
    if ($LASTEXITCODE -ne 0) { throw "Draft checksum upload failed" }
}
$verifyDir = Join-Path ([IO.Path]::GetTempPath()) ("learnnote-release-verify-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $verifyDir | Out-Null
try {
    foreach ($name in $expected.Keys) {
        & gh release download $Tag --repo $Repository --pattern $name --dir $verifyDir
        if ($LASTEXITCODE -ne 0) { throw "Cannot verify uploaded asset $name" }
        $download = Join-Path $verifyDir $name
        if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected[$name]) { throw "Remote asset mismatch: $name; release left unchanged" }
    }
    & gh release download $Tag --repo $Repository --pattern ([IO.Path]::GetFileName($ChecksumFile)) --dir $verifyDir
    if ($LASTEXITCODE -ne 0) { throw "Cannot verify checksum manifest" }
    if ((Get-FileHash -LiteralPath (Join-Path $verifyDir ([IO.Path]::GetFileName($ChecksumFile)))).Hash -ne (Get-FileHash -LiteralPath $ChecksumFile).Hash) { throw "Remote checksum manifest mismatch" }
    if ($release.isDraft) {
        & gh release edit $Tag --repo $Repository --draft=false
        if ($LASTEXITCODE -ne 0) { throw "Verified draft remains available; publishing failed" }
    }
    Write-Output "Release $Tag verified; published assets were not replaced"
} finally {
    $resolved = [IO.Path]::GetFullPath($verifyDir)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    if ($resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and [IO.Path]::GetFileName($resolved).StartsWith('learnnote-release-verify-')) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
