from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class WebAccessibilityContractTests(unittest.TestCase):
    def test_primary_document_has_language_and_focus_contract(self) -> None:
        html = (ROOT / "web" / "classic.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('<html lang="zh-CN">', html)
        self.assertIn('aria-label="设置"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn(":focus-visible", css)
        self.assertIn("forced-colors: active", css)

    def test_new_local_tools_are_keyboard_discoverable(self) -> None:
        html = (ROOT / "web" / "classic.html").read_text(encoding="utf-8")
        for element_id in ("knowledgeImportButton", "knowledgeSearchInput", "studyDueButton", "studyExportButton", "studyRestoreButton", "studyBackupInput", "supportPackageButton"):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('id="settingLocale"', html)
        self.assertIn('value="en-US"', html)
        self.assertIn('aria-label="本地资料库检索结果"', html)
        self.assertIn('aria-label="到期复习卡片"', html)
        self.assertIn('setAttribute("aria-label", "自我解释")', (ROOT / "web" / "learning.js").read_text(encoding="utf-8"))

    def test_stale_personal_note_anchors_have_an_explicit_repair_path(self) -> None:
        source = (ROOT / "web" / "personal-notes.js").read_text(encoding="utf-8")
        self.assertIn("Boolean(item.anchor_status?.stale)", source)
        self.assertIn("stale?'修复出处':'编辑'", source)
        self.assertIn("quoteReanchored&&selected", source)
        self.assertIn("item.anchor_status?.repairable", source)

    def test_default_workspace_acceptance_targets_the_named_annotation_submitter(self) -> None:
        source = (ROOT / "scripts" / "unified-workspace-acceptance.cjs").read_text(encoding="utf-8")
        self.assertIn('p.locator("#saveAnnotation")', source)
        self.assertNotIn('p.locator("#annotationForm button")', source)


if __name__ == "__main__":
    unittest.main()
