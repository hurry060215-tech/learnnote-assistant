param(
  [switch]$InstallAsr,
  [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectRoot "backend"
$venvDir = Join-Path $backendDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$dataDir = Join-Path $projectRoot "data"
$modelCacheDir = Join-Path $dataDir "model-cache"
$pipCacheDir = Join-Path $dataDir "pip-cache"
$tempDir = Join-Path $dataDir "temp"

New-Item -ItemType Directory -Force -Path $modelCacheDir, $pipCacheDir, $tempDir | Out-Null

if (-not $env:HF_HOME) { $env:HF_HOME = Join-Path $modelCacheDir "huggingface" }
if (-not $env:XDG_CACHE_HOME) { $env:XDG_CACHE_HOME = Join-Path $modelCacheDir "xdg" }
if (-not $env:TORCH_HOME) { $env:TORCH_HOME = Join-Path $modelCacheDir "torch" }
if (-not $env:PIP_CACHE_DIR) { $env:PIP_CACHE_DIR = $pipCacheDir }
$env:TMP = $tempDir
$env:TEMP = $tempDir
$env:TMPDIR = $tempDir

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
Set-Location $backendDir

try {
  & $python -c "import fastapi, uvicorn, requests, PIL, yt_dlp, openai, imageio_ffmpeg" | Out-Null
} catch {
  Write-Host "Installing backend dependencies..."
  & $python -m pip install --upgrade pip
  & $python -m pip install -r requirements.txt
}

if ($InstallAsr) {
  try {
    & $python -c "import faster_whisper" | Out-Null
  } catch {
    Write-Host "Installing optional faster-whisper ASR dependency..."
    & $python -m pip install "faster-whisper>=1.1.1"
  }
}

& $python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
