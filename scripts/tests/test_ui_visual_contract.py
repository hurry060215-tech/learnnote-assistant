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


if __name__ == "__main__":
    unittest.main()
