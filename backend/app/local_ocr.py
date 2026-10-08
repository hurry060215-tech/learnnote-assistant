"""Optional, cached OCR quotations from local frames; not factual verification."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import threading

from .config import DATA_DIR
from .storage import atomic_write_text
from .text_cleanup import canonicalize_unicode_text

ENGINE_VERSION = "rapidocr-onnxruntime-1.4.4-v2"
_engine = None
_lock = threading.RLock()


def ocr_available() -> bool:
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def create_ocr_engine():
    import onnxruntime
    # Local OCR must not opt the user's learning workflow into SDK telemetry.
    onnxruntime.disable_telemetry_events()
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)


def _language_hint(text: str) -> str:
    # Script hints are intentionally not claims of language identification.
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u3400-\u9fff]", text):
        return "und-Hani"
    return "und-Latn" if re.search(r"[A-Za-z]", text) else "und"


def _normalize_lines(raw) -> list[dict]:
    if not isinstance(raw, (list, tuple)):
        raise ValueError("invalid_ocr_lines")
    lines = []
    for entry in raw[:200]:
        if not isinstance(entry, (list, tuple)) or len(entry) != 3:
            raise ValueError("invalid_ocr_line")
        bbox, text, confidence = entry
        confidence = float(confidence)
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("invalid_ocr_confidence")
        if len(bbox) != 4 or any(len(point) != 2 for point in bbox):
            raise ValueError("invalid_ocr_box")
        box = [[float(x), float(y)] for x, y in bbox]
        if any(not math.isfinite(value) or abs(value) > 1e8 for point in box for value in point):
            raise ValueError("invalid_ocr_box")
        text = canonicalize_unicode_text(str(text)[:2000]).strip()
        if not text:
            continue
        lines.append({"text": text, "confidence": round(confidence, 4), "bbox": box,
                      "language": _language_hint(text), "language_source": "script_hint",
                      "verification": "unreviewed", "uncertain": confidence < .85})
    return lines


def _cached_lines(cache: Path, digest: str) -> list[dict]:
    if cache.stat().st_size > 2 * 1024**2:
        raise ValueError("oversized_ocr_cache")
    value = json.loads(cache.read_text(encoding="utf-8"))
    if value.get("schema_version") != 2 or value.get("engine") != ENGINE_VERSION or value.get("image_sha256") != digest or not isinstance(value.get("lines"), list):
        raise ValueError("stale_ocr_cache")
    return _normalize_lines([(line["bbox"], line["text"], line["confidence"]) for line in value["lines"]])


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
    results, failures, cache_hits = [], [], 0
    with _lock:
        global _engine
        if engine is None:
            if _engine is None:
                _engine = create_ocr_engine()
            engine = _engine
        for sample in selected:
            cancel_check()
            path = Path(sample.path)
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                key = hashlib.sha256(f"{ENGINE_VERSION}:{digest}".encode()).hexdigest()
                cache = (cache_dir or DATA_DIR / "temp" / "ocr-cache") / f"{key}.json"
                try:
                    lines = _cached_lines(cache, digest)
                    cache_hits += 1
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    raw, _ = engine(str(path))
                    lines = _normalize_lines(raw or [])
                    atomic_write_text(cache, json.dumps({"schema_version": 2, "engine": ENGINE_VERSION, "image_sha256": digest, "lines": lines}, ensure_ascii=False))
                results.append({"timestamp": sample.timestamp, "image_url": sample.url, "image_sha256": digest, "lines": lines,
                                "status": "text_detected" if lines else "no_text", "requires_review": True})
            except Exception as exc:
                cancel_check()
                # Keep earlier useful frames; never expose exception text or paths.
                failures.append({"timestamp": sample.timestamp, "error_type": type(exc).__name__})
    status = "partial" if failures and results else "failed" if failures else "ready"
    return {"schema_version": 2, "status": status, "engine": ENGINE_VERSION, "frames": sorted(results, key=lambda item:item["timestamp"]), "failed_frames": failures, "cache_hits": cache_hits, "remote_calls": 0, "warning": "自动识别文字仅供核对，不等于讲者原话或已验证结论。" + (" 部分画面未完成识别，可重新运行以恢复。" if failures else "")}
