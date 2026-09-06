"""Optional, cached OCR quotations from local frames; not factual verification."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import threading

from .config import DATA_DIR
from .storage import atomic_write_text

ENGINE_VERSION = "rapidocr-onnxruntime-1.4.4-v1"
_engine = None
_lock = threading.RLock()


def ocr_available() -> bool:
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def recognize_frames(samples, *, limit: int = 12, cancel_check=lambda: None, engine=None, cache_dir: Path | None = None) -> dict:
    if engine is None and not ocr_available():
        return {"schema_version": 1, "status": "unavailable", "engine": ENGINE_VERSION, "frames": [], "warning": "本地OCR组件未安装；可按 backend/requirements.ocr.txt 安装，不影响字幕笔记。"}
    cap = max(1, min(limit, 24))
    ordered = sorted(samples, key=lambda sample: sample.timestamp)
    important = [sample for sample in ordered if sample.important]
    def spaced(values, count):
        return [values[round(index * (len(values)-1) / max(1,count-1))] for index in range(count)] if values and count else []
    candidates = spaced(important, min(len(important), cap // 2)) + spaced(ordered, min(len(ordered), cap)) + ordered
    selected, seen = [], set()
    for sample in candidates:
        if sample.path not in seen:
            selected.append(sample); seen.add(sample.path)
        if len(selected) >= cap:
            break
    results, cache_hits = [], 0
    with _lock:
        global _engine
        if engine is None:
            if _engine is None:
                from rapidocr_onnxruntime import RapidOCR
                _engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
            engine = _engine
        for sample in selected:
            cancel_check()
            path = Path(sample.path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            key = hashlib.sha256(f"{ENGINE_VERSION}:{digest}".encode()).hexdigest()
            cache = (cache_dir or DATA_DIR / "temp" / "ocr-cache") / f"{key}.json"
            try:
                lines = json.loads(cache.read_text(encoding="utf-8"))["lines"]
                cache_hits += 1
            except (OSError, ValueError, KeyError):
                raw, _ = engine(str(path))
                lines = []
                for bbox, text, confidence in (raw or [])[:200]:
                    lines.append({"text": str(text)[:2000], "confidence": round(float(confidence), 4), "bbox": [[float(x), float(y)] for x,y in bbox], "verification": "unreviewed", "uncertain": float(confidence) < .85})
                atomic_write_text(cache, json.dumps({"schema_version": 1, "engine": ENGINE_VERSION, "image_sha256": digest, "lines": lines}, ensure_ascii=False))
            results.append({"timestamp": sample.timestamp, "image_url": sample.url, "image_sha256": digest, "lines": lines})
    return {"schema_version": 1, "status": "ready", "engine": ENGINE_VERSION, "frames": sorted(results, key=lambda item:item["timestamp"]), "cache_hits": cache_hits, "remote_calls": 0, "warning": "自动识别文字仅供核对，不等于讲者原话或已验证结论。"}
