"""Keep optional opinion consent acceptance required, isolated and observable."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CommunityQuestionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8")

    def test_both_events_cover_fixture_and_contract_changes(self):
        events = self.source.split("permissions:", 1)[0]
        for path in ("scripts/community-question-api-acceptance.cjs",
                     "scripts/selected-opinion-qa-fixture.py",
                     "scripts/tests/test_community_question_workflow.py",
                     "scripts/tests/*community*question*"):
            self.assertEqual(events.count(f'"{path}"'), 2, path)

    def test_isolated_step_is_required_after_dependencies(self):
        step = self.source.split("      - name: Selected opinion consent with actual Edge and isolated API\n", 1)[1].split("      - name:", 1)[0]
        self.assertIn("!cancelled() && steps.visual_dependencies.outcome == 'success'", step)
        invocation = "node scripts/community-question-api-acceptance.cjs build/community-question-ui"
        self.assertEqual(self.source.count(invocation), 1)
        self.assertIn('if ($LASTEXITCODE -ne 0) { throw "Selected opinion consent API/Edge gate failed" }', step)
        self.assertNotIn("continue-on-error", step)
        self.assertLess(self.source.index(invocation), self.source.index("      - name: Start isolated local backend"))

    def test_only_explicit_output_files_are_retained_on_failure(self):
        upload = self.source.split("            build/community-capture-ui", 1)[0]
        self.assertIn("if: always()", upload)
        for suffix in ("json", "log", "png"):
            self.assertIn(f"            build/community-question-ui/*.{suffix}", self.source)
        self.assertNotIn("build/community-question-ui/**", self.source)
        self.assertNotIn("LEARNNOTE_ACCEPTANCE_BROWSER", self.source)


if __name__ == "__main__":
    unittest.main()
