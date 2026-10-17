"""Offline fixture boundaries; actual rendering requires hosted Edge."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ClassicVisualStudyFixtureTests(unittest.TestCase):
    def test_fixture_boundaries_and_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="classic-visual-study-") as temporary:
            env = {**os.environ, "TMPDIR": temporary, "TMP": temporary, "TEMP": temporary}
            subprocess.run(["node", "--test", "scripts/tests/classic-visual-study-fixture.test.cjs"],
                           cwd=ROOT, env=env, check=True, timeout=30)

    def test_reuses_hosted_classic_browser_and_existing_artifacts(self):
        flow = (ROOT / "scripts/learning-workflow-acceptance.cjs").read_text(encoding="utf-8")
        self.assertEqual(flow.count('runClassicVisualStudy(browser, base, path.join(output, "visual-study"))'), 1)
        workflow = (ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8")
        for name in ("scripts/learning-workflow-acceptance.cjs", "scripts/classic-visual-study-fixture.cjs",
                     "scripts/tests/classic-visual-study-fixture.test.cjs", "scripts/tests/test_classic_visual_study_fixture.py"):
            self.assertEqual(workflow.count('"' + name + '"'), 2, name)
        self.assertIn("learning-workflow-acceptance.cjs http://127.0.0.1:8765/web/classic.html build/learning-ui", workflow)
        self.assertIn("Learning interaction gate failed", workflow)
        self.assertIn("build/learning-ui", workflow[workflow.index("actions/upload-artifact@"):])
