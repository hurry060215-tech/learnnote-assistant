"""Validated local OCR cache revisions, independent of the library database."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .pdf_ocr import summarize_ocr


def _revision(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


def read_ocr_cache(material: dict, root: Path) -> dict | None:
    metadata = material.get("metadata") or {}
    if not metadata.get("ocr_performed"):
        return None
    # Use only a validated local basename so backups can be moved safely.
    name = str(metadata.get("ocr_path") or "ocr.json").replace("\\", "/").rsplit("/", 1)[-1]
    path = root / name
    try:
        if not re.fullmatch(r"ocr(?:-[a-f0-9]{64})?\.json", name) or path.resolve().parent != root.resolve() or path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("invalid_cache")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or _revision(value) != metadata.get("source_revision"):
            raise ValueError("invalid_cache")
        pages = value.get("pages")
        total = value.get("page_count") or metadata.get("ocr_page_count") or len(pages)
        return summarize_ocr(pages, total, engine=value.get("engine", ""), failed_pages=value.get("failed_pages") or [])
    except (OSError, TypeError, ValueError, KeyError, AttributeError) as exc:
        raise ValueError("material_ocr_cache_invalid") from exc


