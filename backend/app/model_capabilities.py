"""Model-specific capabilities; successful image probes are endpoint-scoped."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from .config import DATA_DIR

_lock = threading.Lock()
_FLASH = {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}
CAPABILITY_SCHEMA_VERSION = 1
CAPABILITY_CATALOG_VERSION = 1


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
    return {"id": model, "catalog_version": CAPABILITY_CATALOG_VERSION,
            "vision": True if verified or official else None,
            "capability_source": "image_test" if verified else "official_catalog" if official else "unknown",
            "capability_label": "图片识别已实测" if verified else "支持图片 · 官方说明" if official else "视觉能力待测试"}


def route_capabilities(provider: str, base_url: str, model: str, *, configured: bool,
                       vision_allowed: bool, remote_asr: bool, local_asr_available: bool,
                       asr_configured: bool | None = None) -> dict:
    """Version metadata independently of task options; never probe a provider.

    Configuration, runtime compatibility rules and an explicit image test are
    different evidence. A configured compatible API is not a verified model.
    Unknown limits are intentionally not inferred from provider or model names.
    """
    description = model_description(provider, base_url, model)
    asr_configured = configured if asr_configured is None else asr_configured
    vision_status = ("verified" if description["capability_source"] == "image_test" else
                     "declared" if description["vision"] is True else
                     "unsupported" if not vision_allowed else "unknown")
    return {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "catalog_version": CAPABILITY_CATALOG_VERSION,
        "text": {"status": "configured" if configured else "not_configured",
                 "detail": "文字：已配置兼容接口；本次未验证模型响应。" if configured else "文字：未配置可用连接；可选择仅提取字幕。"},
        "vision": {"status": vision_status, "source": description["capability_source"],
                   "detail": {"verified": "视觉：此接口与型号的图片测试仍在有效期内。",
                              "declared": "视觉：现有能力目录标注支持图片，本次未测试。",
                              "unsupported": "视觉：现有兼容规则不支持此型号，请选文字路线。",
                              "unknown": "视觉：尚无此接口与型号的有效图片验证；文字连接不代表能读图。"}[vision_status]},
        "asr": {"status": ("unverified" if asr_configured else "not_configured") if remote_asr else
                          ("files_ready" if local_asr_available else "not_ready"),
                "detail": ("ASR：已选择兼容音频接口；尚未验证该服务和转写型号。" if asr_configured else "ASR：兼容音频接口需要 Key，本机地址也不会自动免除；当前未配置可用连接。") if remote_asr else
                          ("ASR：本地组件与权重已就绪；实际转写时仍需加载验证。" if local_asr_available else "ASR：本地组件或模型权重尚未准备完成。")},
        "context_limit": {"value": None, "unit": "tokens", "status": "unknown",
                          "detail": "上下文上限：未知；没有此接口与型号的已验证限制。"},
        "image_limit": {"value": None, "unit": "images_per_request", "status": "unknown",
                        "detail": "图片上限：未知；支持图片不代表已知数量、尺寸或请求体限制。"},
    }
