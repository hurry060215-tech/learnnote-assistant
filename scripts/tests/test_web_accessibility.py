from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class WebAccessibilityContractTests(unittest.TestCase):
    def test_primary_document_has_language_and_focus_contract(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('<html lang="zh-CN">', html)
        self.assertIn('aria-label="设置"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn(":focus-visible", css)
        self.assertIn("forced-colors: active", css)

    def test_new_local_tools_are_keyboard_discoverable(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for element_id in ("knowledgeImportButton", "knowledgeSearchInput", "studyDueButton", "supportPackageButton"):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('aria-label="本地资料库检索结果"', html)
        self.assertIn('aria-label="到期复习卡片"', html)


if __name__ == "__main__":
    unittest.main()
