$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectRoot "backend"
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if ($env:LEARNNOTE_PYTHON) {
  $python = $env:LEARNNOTE_PYTHON
} elseif (Test-Path $bundledPython) {
  $python = $bundledPython
} else {
  $python = "python"
}

Write-Host "Using Python: $python"
Set-Location $backendDir

try {
  & $python -c "import fastapi, uvicorn, requests, PIL, yt_dlp, openai, imageio_ffmpeg" | Out-Null
} catch {
  Write-Host "Installing backend dependencies..."
  & $python -m pip install -r requirements.txt
}

& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
