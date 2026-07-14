from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("LEARNNOTE_DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser().resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
TASK_DIR = DATA_DIR / "tasks"
STATIC_DIR = DATA_DIR / "static"
MODEL_CACHE_DIR = DATA_DIR / "model-cache"
TEMP_DIR = DATA_DIR / "temp"
WEB_DIR = PROJECT_ROOT / "web"

DEPLOYMENT_MODE = os.getenv("LEARNNOTE_DEPLOYMENT_MODE", "local").strip().lower()
PUBLIC_DEPLOYMENT = DEPLOYMENT_MODE in {"server", "public", "cloud"}
PUBLIC_USERNAME = os.getenv("LEARNNOTE_PUBLIC_USERNAME", "ln").strip() or "ln"
PUBLIC_PASSWORD = os.getenv("LEARNNOTE_PUBLIC_PASSWORD", "")

if PUBLIC_DEPLOYMENT and len(PUBLIC_PASSWORD) < 12:
    raise RuntimeError("LEARNNOTE_PUBLIC_PASSWORD must contain at least 12 characters in public deployment mode.")

BACKEND_ORIGIN = os.getenv("LEARNNOTE_BACKEND_ORIGIN", "http://127.0.0.1:8765")
DEFAULT_FRAME_INTERVAL = int(os.getenv("LEARNNOTE_FRAME_INTERVAL", "20"))
DEFAULT_GRID_COLUMNS = int(os.getenv("LEARNNOTE_GRID_COLUMNS", "3"))
DEFAULT_GRID_ROWS = int(os.getenv("LEARNNOTE_GRID_ROWS", "3"))
DEFAULT_WHISPER_MODEL = os.getenv("LEARNNOTE_WHISPER_MODEL", "small")
DEFAULT_WHISPER_DEVICE = os.getenv("LEARNNOTE_WHISPER_DEVICE", "cpu")
DEFAULT_WHISPER_COMPUTE_TYPE = os.getenv("LEARNNOTE_WHISPER_COMPUTE_TYPE", "int8")

LLM_BASE_URL = os.getenv("LEARNNOTE_LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.getenv("LEARNNOTE_LLM_API_KEY", "")
LLM_MODEL = os.getenv("LEARNNOTE_LLM_MODEL", "gpt-4.1-mini")
LLM_REQUEST_TIMEOUT_SECONDS = max(10.0, float(os.getenv("LEARNNOTE_LLM_REQUEST_TIMEOUT_SECONDS", "120")))
LLM_MAX_RETRIES = max(0, min(3, int(os.getenv("LEARNNOTE_LLM_MAX_RETRIES", "1"))))


def configure_local_caches() -> None:
    os.environ.setdefault("HF_HOME", str(MODEL_CACHE_DIR / "huggingface"))
    os.environ.setdefault("XDG_CACHE_HOME", str(MODEL_CACHE_DIR / "xdg"))
    os.environ.setdefault("TORCH_HOME", str(MODEL_CACHE_DIR / "torch"))
    os.environ["TMP"] = str(TEMP_DIR)
    os.environ["TEMP"] = str(TEMP_DIR)
    os.environ["TMPDIR"] = str(TEMP_DIR)


configure_local_caches()


def ensure_dirs() -> None:
    for path in (DATA_DIR, UPLOAD_DIR, TASK_DIR, STATIC_DIR, MODEL_CACHE_DIR, TEMP_DIR):
        path.mkdir(parents=True, exist_ok=True)
