from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class UiVisualContractTests(unittest.TestCase):
    def test_visual_script_covers_locale_scale_viewports_and_overflow(self) -> None:
        script = (ROOT / "scripts" / "accessibility-visual-acceptance.cjs").read_text(encoding="utf-8")
        for marker in ("en-US", "zh-CN", "data-value=\"200\"", "1440", "768", "390", "horizontalOverflow", "keyboard"):
            self.assertIn(marker, script)

    def test_workflow_uses_isolated_backend_and_retains_artifacts(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ui-visual.yml").read_text(encoding="utf-8")
        self.assertIn("LEARNNOTE_DATA_DIR", workflow)
        self.assertIn("uvicorn", workflow)
        self.assertIn("accessibility-visual-acceptance.cjs", workflow)
        self.assertIn("actions/upload-artifact", workflow)

    def test_i18n_audit_script_is_present(self) -> None:
        script = (ROOT / "scripts" / "audit-i18n.py").read_text(encoding="utf-8")
        self.assertIn("missing_keys", script)
        self.assertIn("i18n_before_app", script)
        self.assertIn("extension_locale_mismatch", script)

    def test_home_video_shortcut_uses_normalized_source_url(self) -> None:
        script = (ROOT / "web" / "desk-product.js").read_text(encoding="utf-8")
        self.assertIn('$("url").value = result.source.normalized_url || result.source.url || "";', script)

    def test_local_document_import_is_not_presented_as_video_ai_generation(self) -> None:
        script = (ROOT / "web" / "desk.js").read_text(encoding="utf-8")
        self.assertIn(
            'state.input === "file" && file && /\\.(pdf|md|txt|html?)$/i.test(file.name)',
            script,
        )
        self.assertIn('$("createSubmit").disabled = needsFile;', script)
        self.assertIn(
            '$("createSubmit").textContent = "先选择文件";', script
        )
        self.assertIn(
            '$("createSubmit").textContent = "导入并阅读资料";', script
        )
        self.assertIn(
            '$("contentModeChoices").hidden = hideVideoOptions;', script
        )

    def test_first_run_assets_use_a_fresh_browser_cache_key(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        entry = (ROOT / "web" / "desk.js").read_text(encoding="utf-8")
        self.assertIn("desk.js?v=first-run-20260924b", html)
        self.assertIn("desk-product.js?v=first-run-20260923", entry)


if __name__ == "__main__":
    unittest.main()
