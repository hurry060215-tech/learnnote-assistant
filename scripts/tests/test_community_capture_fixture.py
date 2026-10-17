"""Local lifecycle/selector contracts; actual rendering belongs to hosted Edge."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CommunityCaptureFixtureTests(unittest.TestCase):
    def test_cleanup_races_and_shipped_selectors(self):
        subprocess.run(["node", "--test", "scripts/tests/community-capture-fixture.test.cjs",
                        "scripts/tests/community-timestamp-fixture.test.cjs"],
                       cwd=ROOT, check=True, timeout=30)

    def test_community_gate_is_independent_required_and_uploaded(self):
        workflow = (ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8")
        start = workflow.index("      - name: Visible community preview with actual Edge")
        end = workflow.index("      - name: Start isolated local backend", start)
        step = workflow[start:end]
        guard = "if: ${{ !cancelled() && steps.visual_dependencies.outcome == 'success' }}"
        self.assertIn(guard, step)
        self.assertIn(guard, workflow[end:workflow.index("        run: |", end)])
        command = "node scripts/community-capture-visual-acceptance.cjs build/community-capture-ui"
        self.assertEqual(workflow.count(command), 1)
        self.assertIn(command, step)
        self.assertIn('if ($LASTEXITCODE -ne 0) { throw', step)
        self.assertNotIn("continue-on-error", step)
        upload = workflow[workflow.index("      - name: Upload"):] if "      - name: Upload" in workflow else workflow[end:]
        self.assertIn("always()", upload)
        self.assertIn("build/community-capture-ui", upload)
        for path in ("scripts/community-timestamp-fixture.cjs", "scripts/tests/community-timestamp-fixture.test.cjs"):
            self.assertEqual(workflow.count('"' + path + '"'), 2)
