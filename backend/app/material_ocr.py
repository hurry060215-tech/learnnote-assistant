"""Continue only missing scanned PDF pages through the local OCR runtime."""
from __future__ import annotations

from . import library
from .pdf_ocr import OCR_PAGE_LIMIT
from .pdf_ocr_cache import read_ocr_cache


def get_material_ocr(material_id: str) -> dict:
    with library._lock:
        material = library.get_material(material_id)
        if material["source_type"] != "pdf":
            raise ValueError("material_ocr_requires_pdf")
        root = library.DATA_DIR / "materials" / material["material_id"]
        cached = read_ocr_cache(material, root)
        return cached or {"status": "not_started", "pages": [], "processed_page_count": 0,
                          "verification": "unreviewed", "batch_page_limit": OCR_PAGE_LIMIT,
                          "warning": "可选本地 OCR 每次最多识别 24 页，不调用在线模型；识别结果需要对照原始 PDF 核验。"}


def continue_material_ocr(material_id: str) -> dict:
    from .pdf_ocr import ocr_pdf

    material = library.get_material(material_id)
    if material["source_type"] != "pdf":
        raise ValueError("material_ocr_requires_pdf")
    if material["status"] != "ocr_required" and not (material.get("metadata") or {}).get("ocr_performed"):
        raise ValueError("material_ocr_not_required")
    cached = get_material_ocr(material_id)
    if cached["status"] == "ready":
        return {"ok": True, "material": material, "ocr": cached}
    source = library.material_source_path(material_id)
    if library._file_sha256(source) != material["sha256"]:
        raise ValueError("material_source_integrity_mismatch")
    batch = ocr_pdf(source, completed_pages=[page["page"] for page in cached["pages"]])
    if batch.get("status") == "unavailable":
        return {"ok": False, "material": material, "ocr": batch}
    if not batch.get("pages"):
        raise ValueError("material_ocr_batch_failed")
    updated = library.apply_material_ocr(material_id, batch)
    return {"ok": True, "material": updated, "ocr": get_material_ocr(material_id)}


