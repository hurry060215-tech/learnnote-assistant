"""Optional local OCR for scanned PDF pages."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


OCR_SCHEMA_VERSION = 1
OCR_ENGINE = "rapidocr-onnxruntime-1.4.4"


def ocr_available() -> bool:
    return bool(importlib.util.find_spec("fitz") and importlib.util.find_spec("rapidocr_onnxruntime"))


def ocr_pdf(path: Path, *, page_limit: int = 24, engine=None) -> dict[str, Any]:
    if not Path(path).is_file():
        raise ValueError("pdf_source_missing")
    if engine is None:
        if not ocr_available():
            return {"schema_version": OCR_SCHEMA_VERSION, "status": "unavailable", "engine": OCR_ENGINE, "pages": [], "warning": "扫描 PDF OCR 需要可选的 PyMuPDF 和 RapidOCR 组件。"}
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
    try:
        import fitz
        from PIL import Image
        import numpy as np
    except ImportError:
        return {"schema_version": OCR_SCHEMA_VERSION, "status": "unavailable", "engine": OCR_ENGINE, "pages": [], "warning": "扫描 PDF OCR 需要可选的 PyMuPDF、Pillow 和 NumPy 组件。"}
    pages = []
    with fitz.open(str(path)) as document:
        for page_index in range(min(max(1, int(page_limit)), len(document))):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            raw, _ = engine(np.asarray(image))
            lines = []
            for bbox, text, confidence in (raw or [])[:300]:
                value = str(text or "").strip()
                if not value:
                    continue
                score = round(float(confidence), 4)
                lines.append({"text": value[:2000], "confidence": score, "bbox": [[float(x), float(y)] for x, y in bbox], "verification": "unreviewed", "uncertain": score < 0.85})
            pages.append({"page": page_index + 1, "lines": lines, "text": "\n".join(line["text"] for line in lines)})
    return {"schema_version": OCR_SCHEMA_VERSION, "status": "ready", "engine": OCR_ENGINE, "pages": pages, "page_count": len(pages), "warning": "OCR 结果仅供核对，不等于 PDF 原始文字或已验证结论。"}


__all__ = ["OCR_ENGINE", "OCR_SCHEMA_VERSION", "ocr_available", "ocr_pdf"]
