param(
  [switch]$InstallAsr,
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

function Resolve-BootstrapPython {
  if ($env:LEARNNOTE_BOOTSTRAP_PYTHON) {
    return $env:LEARNNOTE_BOOTSTRAP_PYTHON
  }
  $pathPython = Get-Command python -ErrorAction SilentlyContinue
  if ($pathPython) {
    return $pathPython.Source
  }
  $anacondaPython = "D:\Anaconda3\python.exe"
  if (Test-Path $anacondaPython) {
    return $anacondaPython
  }
  return "python"
}

if (-not (Test-Path $venvPython)) {
  $bootstrapPython = Resolve-BootstrapPython
  Write-Host "Creating project venv: $venvDir"
  & $bootstrapPython -m venv $venvDir
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
  & $python -m pip install --upgrade pip
  if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip in $venvDir" }
  & $python -m pip install -r requirements.txt
  if ($LASTEXITCODE -ne 0) { throw "Failed to install backend dependencies in $venvDir" }
}

if ($InstallAsr) {
  if (-not (Test-PythonImports "import faster_whisper")) {
    Write-Host "Installing optional faster-whisper ASR dependency..."
    & $python -m pip install "faster-whisper>=1.1.1"
    if ($LASTEXITCODE -ne 0) { throw "Failed to install faster-whisper in $venvDir" }
  }
}

& $python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
