param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = "Stop"

choco install ffmpeg --version=8.1.0 --source=https://community.chocolatey.org/api/v2/ --yes --no-progress
if ($LASTEXITCODE -ne 0) { throw "Pinned visual media tools installation failed" }
$tools = @{}
foreach ($name in @('ffmpeg', 'ffprobe')) {
  $exe = (Get-Command $name -ErrorAction Stop).Source
  $version = & $exe -version
  if ($LASTEXITCODE -ne 0) { throw "$name version verification failed" }
  $first = [string]$version[0]
  if ($first -notmatch "^$name version 8\.1(?:\.0)?(?:-| )") { throw "Unexpected pinned media version: $first" }
  $tools[$name] = @{ path = $exe; version = $first }
}
New-Item -ItemType Directory -Force "$OutputDirectory" | Out-Null
@{ package = 'ffmpeg'; package_version = '8.1.0'; source = 'https://community.chocolatey.org/api/v2/'; tools = $tools } |
  ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $OutputDirectory "media-tools.json")
