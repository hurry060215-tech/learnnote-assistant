function Import-LearnNoteModelProfile {
  param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [Parameter(Mandatory = $true)][string]$Name
  )

  if ($Name -notmatch "^[A-Za-z0-9_-]{1,40}$") {
    throw "Model profile names may contain only letters, numbers, underscores, and hyphens."
  }

  $profilePath = Join-Path $ProjectRoot "data\config\model-profiles\$Name.env"
  if (-not (Test-Path -LiteralPath $profilePath -PathType Leaf)) {
    throw "Model profile '$Name' was not found at $profilePath"
  }

  $allowedKeys = @(
    "LEARNNOTE_LLM_BASE_URL",
    "LEARNNOTE_LLM_API_KEY",
    "LEARNNOTE_LLM_MODEL"
  )
  $loadedKeys = @()
  foreach ($rawLine in Get-Content -LiteralPath $profilePath -Encoding UTF8) {
    $line = $rawLine.Trim()
    if (-not $line -or $line.StartsWith("#")) { continue }
    $separator = $line.IndexOf("=")
    if ($separator -lt 1) {
      throw "Invalid model profile line in ${profilePath}: expected KEY=VALUE."
    }
    $key = $line.Substring(0, $separator).Trim()
    $value = $line.Substring($separator + 1).Trim()
    if ($allowedKeys -notcontains $key) {
      throw "Unsupported model profile key '$key' in $profilePath"
    }
    Set-Item -Path "Env:$key" -Value $value
    $loadedKeys += $key
  }

  foreach ($requiredKey in $allowedKeys) {
    if ($loadedKeys -notcontains $requiredKey) {
      throw "Model profile '$Name' is missing $requiredKey"
    }
  }
  Write-Host "Model profile: $Name (credentials loaded without displaying them)"
  return $profilePath
}
