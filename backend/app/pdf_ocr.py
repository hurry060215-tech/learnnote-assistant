"""Optional, bounded local OCR for scanned PDF pages."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import Any
from .ocr_runtime import create_ocr_engine


OCR_SCHEMA_VERSION = 1
OCR_ENGINE = "rapidocr-onnxruntime-1.4.4"
OCR_PAGE_LIMIT = 24
OCR_MAX_PAGES = 500


def ocr_available() -> bool:
    return bool(importlib.util.find_spec("fitz") and importlib.util.find_spec("rapidocr_onnxruntime"))


def _confidence(value):
    if value is None:
        return None
    score = float(value)
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("material_ocr_invalid_result")
    return round(score, 4)


def summarize_ocr(pages: list, page_count: int, *, engine: str = "", failed_pages=()) -> dict[str, Any]:
    """Normalize cache and batch results; missing pages are explicit, including holes."""
    total = int(page_count)
    if not 1 <= total <= OCR_MAX_PAGES or not isinstance(pages, list) or len(pages) > total:
        raise ValueError("material_ocr_invalid_result")
    normalized = {}
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("material_ocr_invalid_result")
        number = int(page.get("page") or 0)
        if not 1 <= number <= total or number in normalized:
            raise ValueError("material_ocr_invalid_result")
        lines = []
        raw_lines = page.get("lines") or []
        if not isinstance(raw_lines, list) or len(raw_lines) > 300:
            raise ValueError("material_ocr_invalid_result")
        for line in raw_lines:
            if not isinstance(line, dict):
                raise ValueError("material_ocr_invalid_result")
            text = str(line.get("text") or "").strip()
            if not text:
                continue
            score = _confidence(line.get("confidence"))
            lines.append({**line, "text": text[:2000], "confidence": score,
                          "verification": "unreviewed", "uncertain": score is None or score < 0.85})
        scores = [line["confidence"] for line in lines if line["confidence"] is not None]
        confidence = round(sum(scores) / len(scores), 4) if scores else _confidence(page.get("confidence"))
        normalized[number] = {"page": number, "text": str(page.get("text") or "\n".join(line["text"] for line in lines)).strip(),
                              "lines": lines, "confidence": confidence, "verification": "unreviewed"}
    missing = [number for number in range(1, total + 1) if number not in normalized]
    ranges = []
    for number in missing:
        if ranges and ranges[-1][1] == number - 1:
            ranges[-1][1] = number
        else:
            ranges.append([number, number])
    failed = sorted({int(number) for number in failed_pages if int(number) in missing})
    pages = [normalized[number] for number in sorted(normalized)]
    return {"schema_version": OCR_SCHEMA_VERSION, "status": "partial" if missing else "ready", "engine": str(engine),
            "pages": pages, "page_count": total, "processed_page_count": len(pages),
            "processed_page_range": [pages[0]["page"], pages[-1]["page"]] if pages else [],
            "missing_pages": missing, "missing_page_ranges": ranges,
            "missing_page_range": [missing[0], missing[-1]] if missing else [], "failed_pages": failed,
            "verification": "unreviewed", "batch_page_limit": OCR_PAGE_LIMIT,
            "warning": (f"已完成 {len(pages)} / {total} 页 OCR；其余页面可继续识别。" if missing else f"已完成 {total} 页 OCR。")
                       + (f"本次有 {len(failed)} 页未成功，可重试。" if failed else "")
                       + " OCR 结果未核验；置信度不等于准确率，请对照原始 PDF。"}


def ocr_pdf(path: Path, *, page_limit: int = OCR_PAGE_LIMIT, completed_pages=(), engine=None) -> dict[str, Any]:
    if not Path(path).is_file():
        raise ValueError("pdf_source_missing")
    if engine is None:
        if not ocr_available():
            return {"schema_version": OCR_SCHEMA_VERSION, "status": "unavailable", "engine": OCR_ENGINE, "pages": [], "warning": "扫描 PDF OCR 需要可选的 PyMuPDF 和 RapidOCR 组件。"}
        engine = create_ocr_engine()
    try:
        import fitz
        from PIL import Image
        import numpy as np
    except ImportError:
        return {"schema_version": OCR_SCHEMA_VERSION, "status": "unavailable", "engine": OCR_ENGINE, "pages": [], "warning": "扫描 PDF OCR 需要可选的 PyMuPDF、Pillow 和 NumPy 组件。"}
    pages, failed = [], []
    with fitz.open(str(path)) as document:
        total_pages = len(document)
        if not 1 <= total_pages <= OCR_MAX_PAGES:
            raise ValueError("pdf_page_limit_exceeded")
        completed = {int(number) for number in completed_pages}
        selected = [number for number in range(1, total_pages + 1) if number not in completed][:min(OCR_PAGE_LIMIT, max(1, int(page_limit)))]
        for number in selected:
            try:
                page = document.load_page(number - 1)
                # Bound raster memory even for unusually large PDF page dimensions.
                scale = min(1.6, 2400 / max(page.rect.width, page.rect.height, 1))
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                raw, _ = engine(np.asarray(image))
                lines = []
                for bbox, text, confidence in (raw or [])[:300]:
                    value = str(text or "").strip()
                    if value:
                        lines.append({"text": value[:2000], "confidence": _confidence(confidence),
                                      "bbox": [[float(x), float(y)] for x, y in bbox]})
                pages.append({"page": number, "lines": lines, "text": "\n".join(line["text"] for line in lines)})
            except Exception:
                # A failed page remains missing. Keep completed pages and let a
                # later explicit request retry without exposing runtime details.
                failed.append(number)
    return summarize_ocr(pages, total_pages, engine=OCR_ENGINE, failed_pages=failed)


__all__ = ["OCR_ENGINE", "OCR_SCHEMA_VERSION", "OCR_PAGE_LIMIT", "ocr_available", "ocr_pdf", "summarize_ocr"]
