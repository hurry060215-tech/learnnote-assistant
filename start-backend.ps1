param(
  [switch]$InstallAsr,
  [switch]$BootstrapOnly,
  [int]$Port = 8765,
  [string]$ModelProfile = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectRoot "backend"
$venvDir = if ($env:LEARNNOTE_VENV_DIR) { $env:LEARNNOTE_VENV_DIR } else { Join-Path $projectRoot ".venv" }
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$dataDir = Join-Path $projectRoot "data"
$modelCacheDir = Join-Path $dataDir "model-cache"
$pipCacheDir = Join-Path $dataDir "pip-cache"
$tempDir = Join-Path $dataDir "temp"
$backendUrl = "http://127.0.0.1:$Port"

if ($ModelProfile) {
  . (Join-Path $projectRoot "scripts\model-profile.ps1")
  Import-LearnNoteModelProfile -ProjectRoot $projectRoot -Name $ModelProfile | Out-Null
}

New-Item -ItemType Directory -Force -Path $modelCacheDir, $pipCacheDir, $tempDir | Out-Null

if (-not $env:HF_HOME) { $env:HF_HOME = Join-Path $modelCacheDir "huggingface" }
if (-not $env:XDG_CACHE_HOME) { $env:XDG_CACHE_HOME = Join-Path $modelCacheDir "xdg" }
if (-not $env:TORCH_HOME) { $env:TORCH_HOME = Join-Path $modelCacheDir "torch" }
if (-not $env:PIP_CACHE_DIR) { $env:PIP_CACHE_DIR = $pipCacheDir }
$env:TMP = $tempDir
$env:TEMP = $tempDir
$env:TMPDIR = $tempDir
$previousBackendOrigin = $env:LEARNNOTE_BACKEND_ORIGIN
$env:LEARNNOTE_BACKEND_ORIGIN = $backendUrl

function Test-SupportedPython {
  param([string]$Command, [string[]]$PrefixArgs = @())

  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    & $Command @PrefixArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  } finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
}

if (-not (Test-Path $venvPython)) {
  Write-Host "Creating project venv: $venvDir"
  $pythonCandidates = @(
    $env:LEARNNOTE_BOOTSTRAP_PYTHON,
    "D:\Python312\python.exe",
    (Get-Command python -ErrorAction SilentlyContinue).Source,
    "D:\Anaconda3\python.exe"
  ) | Where-Object { $_ } | Select-Object -Unique
  $created = $false
  foreach ($candidate in $pythonCandidates) {
    if (Test-SupportedPython -Command $candidate) {
      Write-Host "Bootstrap Python: $candidate"
      & $candidate -m venv $venvDir
      if ($LASTEXITCODE -ne 0) { throw "Failed to create project venv with $candidate" }
      $created = $true
      break
    }
  }
  if (-not $created) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher -and (Test-SupportedPython -Command $pyLauncher.Source -PrefixArgs @("-3.12"))) {
      Write-Host "Bootstrap Python: py -3.12"
      & $pyLauncher.Source -3.12 -m venv $venvDir
      if ($LASTEXITCODE -ne 0) { throw "Failed to create project venv with py -3.12" }
      $created = $true
    }
  }
  if (-not $created) {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
      throw "LearnNote needs Python 3.11+ or uv. Install uv, or set LEARNNOTE_BOOTSTRAP_PYTHON to a supported python.exe."
    }
    Write-Host "No local Python 3.11+ found; uv will provision Python 3.12." -ForegroundColor Cyan
    & $uv.Source venv --python 3.12 --seed $venvDir
    if ($LASTEXITCODE -ne 0) { throw "Failed to create project venv with uv and Python 3.12" }
  }
}

$python = $venvPython
Write-Host "Using Python: $python"
Write-Host "Backend origin: $env:LEARNNOTE_BACKEND_ORIGIN"
if ($previousBackendOrigin -and $previousBackendOrigin -ne $backendUrl) {
  Write-Host "Origin note: replaced previous LEARNNOTE_BACKEND_ORIGIN=$previousBackendOrigin for this session." -ForegroundColor DarkYellow
}
Set-Location $backendDir

function Test-PythonImports {
  param([string]$Code)

  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    & $python -c $Code 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
  } finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
}

if (-not (Test-PythonImports "import fastapi, uvicorn, requests, PIL, yt_dlp, openai, imageio_ffmpeg")) {
  Write-Host "Installing backend dependencies..."
  Write-Host "Network retries are limited; a stalled package source will fail with a retryable error instead of waiting indefinitely." -ForegroundColor DarkYellow
  & $python -m pip install --timeout 30 --retries 2 --upgrade pip
  if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip in $venvDir" }
  & $python -m pip install --timeout 30 --retries 2 --progress-bar on -r requirements.txt
  if ($LASTEXITCODE -ne 0) { throw "Failed to install backend dependencies in $venvDir" }
}

if ($InstallAsr) {
  if (-not (Test-PythonImports "import faster_whisper")) {
    Write-Host "Installing optional faster-whisper ASR dependency." -ForegroundColor Cyan
    Write-Host "This is a large first-time download and may take several minutes; pip progress will remain visible." -ForegroundColor DarkYellow
    & $python -m pip install --timeout 30 --retries 2 --progress-bar on "faster-whisper>=1.1.1"
    if ($LASTEXITCODE -ne 0) { throw "Failed to install faster-whisper in $venvDir" }
  }
}

if ($BootstrapOnly) {
  Write-Host "LearnNote backend environment is ready." -ForegroundColor Green
  return
}

& $python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
