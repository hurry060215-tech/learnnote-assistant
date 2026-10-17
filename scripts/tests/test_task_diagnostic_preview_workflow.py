"""Keep the content-free diagnostic preview gate required and isolated."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TaskDiagnosticPreviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8")

    def test_both_events_cover_fixture_and_contracts(self):
        events = self.source.split("permissions:", 1)[0]
        for path in ("scripts/task-diagnostic-preview-*.cjs", "scripts/tests/test_task_diagnostic_preview*.py"):
            self.assertEqual(events.count(f'"{path}"'), 2, path)

    def test_independent_gate_preserves_required_failure(self):
        step = self.source.split("      - name: Safe diagnostic preview with actual Edge and synthetic API\n", 1)[1].split("      - name:", 1)[0]
        invocation = "node scripts/task-diagnostic-preview-acceptance.cjs build/task-diagnostic-preview"
        self.assertEqual(self.source.count(invocation + "\n"), 1)
        self.assertIn("!cancelled() && steps.visual_dependencies.outcome == 'success'", step)
        self.assertIn('if ($LASTEXITCODE -ne 0) { throw "Safe diagnostic preview and exact download gate failed" }', step)
        self.assertNotIn("continue-on-error", step)
        self.assertLess(self.source.index(invocation), self.source.index("      - name: Start isolated local backend"))
        self.assertIn("timeout-minutes: 20", self.source)

    def test_native_zoom_is_independently_required(self):
        step = self.source.split("      - name: Safe diagnostic preview with owned native Edge zoom\n", 1)[1].split("      - name:", 1)[0]
        invocation = "node scripts/task-diagnostic-preview-acceptance.cjs build/task-diagnostic-preview-native --native"
        self.assertEqual(self.source.count(invocation), 1)
        self.assertIn("!cancelled() && steps.visual_dependencies.outcome == 'success'", step)
        self.assertIn('if ($LASTEXITCODE -ne 0) { throw "Safe diagnostic native zoom and exact download gate failed" }', step)
        self.assertNotIn("continue-on-error", step)
        for suffix in ("json", "log", "png"):
            self.assertIn(f"            build/task-diagnostic-preview-native/*.{suffix}", self.source)
        self.assertNotIn("build/task-diagnostic-preview-native/**", self.source)

    def test_explicit_reports_retained_on_failure_without_download_content(self):
        upload = self.source.split("            build/task-diagnostic-preview/*.json", 1)[0]
        self.assertIn("if: always()", upload)
        for suffix in ("json", "log", "png"):
            self.assertIn(f"            build/task-diagnostic-preview/*.{suffix}", self.source)
        self.assertNotIn("build/task-diagnostic-preview/**", self.source)


if __name__ == "__main__":
    unittest.main()
