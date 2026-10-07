from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, library


class ExistingMaterialRedecodeTests(unittest.TestCase):
    def test_redecode_updates_existing_material_from_preserved_raw_bytes(self) -> None:
        expected = "课程编码样本：学习率决定步长。"
        raw = expected.encode("gb18030")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_paths = {
                "DATA_DIR": root,
                "UPLOAD_DIR": root / "uploads",
                "TASK_DIR": root / "tasks",
                "STATIC_DIR": root / "static",
                "MODEL_CACHE_DIR": root / "models",
                "TEMP_DIR": root / "temp",
            }
            with patch.multiple(config, **config_paths), \
                 patch("app.library.DATA_DIR", root), \
                 patch("app.library.TASK_DIR", root / "tasks"), \
                 patch("app.library.TEMP_DIR", root / "temp"), \
                 patch("app.knowledge.DATA_DIR", root):
                material = library.import_document_material("lesson.txt", raw, "text/plain", encoding="big5")
                original_path = library.material_source_path(material["material_id"])
                original_sha = hashlib.sha256(original_path.read_bytes()).hexdigest()
                old_text = library.material_content(material["material_id"])
                old_ids = list(material["evidence_ids"])
                self.assertNotEqual(old_text, expected)

                updated = library.redecode_document_material(material["material_id"], "gb18030")
                refreshed = library.material_content(material["material_id"])
                anchors = library.material_anchors(material["material_id"])

                self.assertEqual(refreshed.strip(), expected)
                self.assertEqual(updated["metadata"]["encoding"], "gb18030")
                self.assertTrue(updated["metadata"]["redecoded"])
                self.assertEqual(updated["metadata"]["raw_sha256"], original_sha)
                self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(), original_sha)
                self.assertEqual(updated["evidence_ids"], old_ids)
                self.assertTrue(any(item["text"] == expected for item in anchors))


if __name__ == "__main__":
    unittest.main()
