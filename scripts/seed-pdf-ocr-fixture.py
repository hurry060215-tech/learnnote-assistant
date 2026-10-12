"""Synthetic OCR cache only; guarded to this checkout's isolated build data."""
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
data = Path(os.environ.get("LEARNNOTE_DATA_DIR", "")).resolve()
if not os.environ.get("LEARNNOTE_DATA_DIR") or not data.is_relative_to(ROOT / "build"):
    raise SystemExit("OCR fixtures require an isolated checkout build data directory")
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from app.library import apply_material_ocr, get_material, import_document_material
from app.material_ocr import get_material_ocr

if len(sys.argv) == 3 and sys.argv[1] == "--complete":
    material = get_material(sys.argv[2])
    if not material["filename"].startswith("synthetic-ocr-"):
        raise SystemExit("Only this test's synthetic OCR material may be completed")
    pages = [{"page": 3, "text": "Synthetic continued page", "lines": [{"text": "Synthetic continued page", "confidence": 0.93}]}]
else:
    output = BytesIO()
    canvas = Canvas(output, pagesize=(100, 100))
    key = uuid4().hex[:12]
    canvas.setTitle("Synthetic OCR fixture " + key)
    for number in range(1, 4):
        canvas.drawImage(ImageReader(Image.new("RGB", (100, 100), (number, number, number))), 0, 0, 100, 100)
        canvas.showPage()
    canvas.save()
    material = import_document_material(f"synthetic-ocr-{key}.pdf", output.getvalue(), "application/pdf")
    pages = [{"page": 1, "text": "Synthetic confident line\nSynthetic uncertain line", "lines": [
        {"text": "Synthetic confident line", "confidence": 0.92}, {"text": "Synthetic uncertain line", "confidence": 0.72}]},
        {"page": 2, "text": "Synthetic unscored line", "lines": [{"text": "Synthetic unscored line", "confidence": None}]}]
material = apply_material_ocr(material["material_id"], {"engine": "synthetic-cache-no-model", "page_count": 3, "pages": pages})
print(json.dumps({"ok": True, "material": material, "ocr": get_material_ocr(material["material_id"])}))
