"""Explicit, optional preparation of local speech models. No startup downloads."""
import threading
import re
from .config import MODEL_CACHE_DIR, configure_local_caches

MODELS = {"tiny", "base", "small", "medium", "large-v3"}
_lock = threading.RLock()
_states = {}


def _complete(folder):
    return all((folder / name).is_file() and (folder / name).stat().st_size > 0 for name in ("config.json", "model.bin", "tokenizer.json"))


def _ready(model):
    if _complete(MODEL_CACHE_DIR / f"faster-whisper-{model}"):
        return True
    # Recognize models downloaded by Whisper itself; status never contacts HF.
    hub = MODEL_CACHE_DIR / "huggingface" / "hub" / f"models--Systran--faster-whisper-{model}"
    ref = hub / "refs" / "main"
    if ref.is_file():
        revision = ref.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[a-f0-9]{40,64}", revision):
            return _complete(hub / "snapshots" / revision)
    return False


def model_status(model):
    if model not in MODELS:
        raise ValueError("unsupported_model")
    ready = _ready(model)
    with _lock:
        state = dict(_states.get(model, {}))
    if state.get("status") != "downloading" and ready:
        state = {"status": "ready", "message": "模型文件已就绪；实际转写时会检查能否加载。"}
    return {"model":model, "optional":True, **(state or {"status":"not_downloaded", "message":"尚未准备。已有字幕或使用远程转写时不需要本地模型。"})}


def prepare_model(model):
    with _lock:
        status = model_status(model)
        if status["status"] in {"ready", "downloading"}:
            return status
        if any(s.get("status") == "downloading" for s in _states.values()):
            raise RuntimeError("model_download_busy")
        _states[model] = {"status":"downloading", "message":"正在从模型仓库下载，耗时取决于网络。可以继续使用已有字幕。"}

    def work():
        try:
            configure_local_caches()
            from faster_whisper.utils import download_model
            download_model(model, output_dir=str(MODEL_CACHE_DIR / f"faster-whisper-{model}"))
            if not _ready(model):
                raise OSError("incomplete_model_download")
            with _lock:
                _states[model] = {"status":"ready", "message":"下载完成，可以使用本地转写。"}
        except Exception:
            with _lock:
                _states[model] = {"status":"failed", "message":"下载未完成，请检查网络和磁盘空间后重试；字幕与远程模型功能仍可使用。"}
    threading.Thread(target=work, name="learnnote-model-prepare", daemon=True).start()
    return model_status(model)
