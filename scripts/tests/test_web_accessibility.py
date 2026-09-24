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
        for filename in ("unified-workspace-acceptance.cjs", "redesign-acceptance.cjs"):
            source = (ROOT / "scripts" / filename).read_text(encoding="utf-8")
            with self.subTest(script=filename):
                self.assertIn('locator("#saveAnnotation")', source)
        self.assertNotIn('locator("#annotationForm button")', source)

    def test_learning_browser_acceptance_records_the_self_assessment_step(self) -> None:
        source = (ROOT / "scripts" / "learning-workflow-acceptance.cjs").read_text(encoding="utf-8")
        self.assertIn('const reflection = page.getByRole("textbox", { name: "自我解释", exact: true });', source)
        self.assertIn('await reflection.fill(', source)
        self.assertIn('name: "记录解释并显示出处答案"', source)
        self.assertIn("self_assessment_count > 0", source)


if __name__ == "__main__":
    unittest.main()
