param(
  [Parameter(Mandatory = $true)]
  [string]$Url,
  [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "SilentlyContinue"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
  try {
    $health = Invoke-RestMethod -Uri "$Url/health" -TimeoutSec 2
    if ($health.ok -eq $true -and $health.service -eq "learnnote") {
      Start-Process $Url | Out-Null
      exit 0
    }
  } catch {
    # The backend may still be bootstrapping its environment.
  }
  Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)

exit 1
