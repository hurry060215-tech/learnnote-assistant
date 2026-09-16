"""Model-specific capabilities; successful image probes are endpoint-scoped."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from .config import DATA_DIR

_lock = threading.Lock()
_FLASH = {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}


def _key(base_url: str, model: str) -> str:
    return hashlib.sha256((base_url.rstrip("/") + "\n" + model).encode()).hexdigest()


def _checks() -> dict:
    try:
        value = json.loads((DATA_DIR / "config" / "model-capability-checks.json").read_text(encoding="utf-8"))
        return {k:v for k,v in value.items() if isinstance(v,dict) and isinstance(v.get("checked_at"),(int,float))} if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def image_probe_verified(base_url: str, model: str) -> bool:
    item = _checks().get(_key(base_url, model), {})
    return isinstance(item, dict) and item.get("vision") is True and 0 <= time.time() - item.get("checked_at", 0) < 7 * 86400


def save_image_probe(base_url: str, model: str) -> None:
    from .storage import atomic_write_text
    with _lock:
        values = _checks()
        values[_key(base_url, model)] = {"vision": True, "checked_at": time.time()}
        values = dict(sorted(values.items(), key=lambda item: item[1].get("checked_at", 0), reverse=True)[:128])
        path = DATA_DIR / "config" / "model-capability-checks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(values))


def model_description(provider: str, base_url: str, model: str) -> dict:
    verified = image_probe_verified(base_url, model)
    official = provider == "deepseek" and model.lower() in _FLASH
    return {"id": model, "vision": True if verified or official else None,
            "capability_source": "image_test" if verified else "official_catalog" if official else "unknown",
            "capability_label": "图片识别已实测" if verified else "支持图片 · 官方说明" if official else "视觉能力待测试"}
