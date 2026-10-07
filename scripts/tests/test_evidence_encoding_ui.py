from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class EvidenceEncodingUiTests(unittest.TestCase):
    def test_default_workspace_offers_encoding_choice_only_for_document_inputs(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "desk.js").read_text(encoding="utf-8")
        stylesheet = (ROOT / "web" / "desk.css").read_text(encoding="utf-8")

        self.assertIn('id="materialEncodingChoice"', html)
        self.assertIn('id="materialEncoding"', html)
        self.assertIn('value="gb18030"', html)
        self.assertIn('value="shift_jis"', html)
        self.assertIn('value="utf-16-le"', html)
        self.assertIn('value="utf-16-be"', html)
        self.assertIn('data.append("encoding", requestedEncoding)', script)
        self.assertIn("updateMaterialEncodingChoice", script)
        self.assertIn("encoding-provenance-note", script)
        self.assertIn("encoding_confidence", script)
        self.assertIn("未覆盖原资料", (ROOT / "web" / "app.js").read_text(encoding="utf-8"))
        self.assertIn("encoding-provenance-note", stylesheet)

    def test_classic_import_uses_the_same_encoding_form_field(self) -> None:
        html = (ROOT / "web" / "classic.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="knowledgeImportEncoding"', html)
        self.assertIn('form.append("encoding", requestedEncoding)', script)

    def test_browser_smoke_exercises_the_default_workspace_import_and_provenance(self) -> None:
        script = (ROOT / "scripts" / "e2e-document-import-smoke.py").read_text(encoding="utf-8")
        self.assertIn('os.getenv("LEARNNOTE_DATA_DIR"', script)
        self.assertIn("DOM.setFileInputFiles", script)
        self.assertIn("materialEncoding", script)
        self.assertIn("encoding-provenance-note", script)
        self.assertIn("shutil.rmtree(profile_dir", script)


if __name__ == "__main__":
    unittest.main()
