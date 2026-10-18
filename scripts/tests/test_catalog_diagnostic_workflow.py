"""Keep the catalog profiler manual, bounded and separate from existing gates."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = "build/reliability/catalog-native-diagnostic"
SCRIPT = "scripts/progressive-slo-catalog-diagnostic.py"


class CatalogDiagnosticWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / ".github/workflows/reliability.yml").read_text(encoding="utf-8")
        cls.workflow = yaml.safe_load(cls.source)
        cls.events = cls.workflow.get("on", cls.workflow.get(True))
        cls.job = cls.workflow["jobs"]["offline-reliability"]
        cls.steps = cls.job["steps"]

    def test_manual_boolean_is_opt_in_and_diagnostic_only(self):
        inputs = self.events["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"catalog_profile"})
        option = inputs["catalog_profile"]
        self.assertEqual(option["type"], "boolean")
        self.assertIs(option["default"], False)
        self.assertIs(option["required"], False)
        self.assertIn("not browser timing or release acceptance", option["description"])

    def test_exact_new_inputs_trigger_both_existing_event_filters(self):
        for event in ("pull_request", "push"):
            for path in (SCRIPT, "scripts/tests/test_progressive_slo_catalog_diagnostic.py",
                         "scripts/tests/test_catalog_diagnostic_workflow.py"):
                self.assertEqual(self.events[event]["paths"].count(path), 1)
        self.assertEqual(self.events["push"]["branches"], ["main"])
        self.assertEqual(self.events["schedule"], [{"cron": "23 18 * * 1"}])

    def test_once_after_caption_gate_with_explicit_success_manual_input_guard(self):
        matches = [step for step in self.steps if SCRIPT in step.get("run", "")]
        self.assertEqual(len(matches), 1)
        step = matches[0]
        self.assertEqual(step["if"],
                         "${{ success() && github.event_name == 'workflow_dispatch' && inputs.catalog_profile }}")
        self.assertEqual(step["timeout-minutes"], 5)
        self.assertEqual(step["shell"], "pwsh")
        self.assertEqual(step["run"].splitlines(), [
            f"python {SCRIPT} --output-dir {OUTPUT}",
            'if ($LASTEXITCODE -ne 0) { throw "Synthetic catalog diagnostic failed" }',
        ])
        self.assertNotIn("continue-on-error", step)
        prior = self.steps[self.steps.index(step) - 1]
        self.assertEqual(prior["name"], "Caption-to-outline reference p95 gate")
        self.assertEqual(prior["run"].splitlines(), [
            "python scripts/progressive-slo.py --repetitions 20 --output-dir build/reliability/progressive-outline",
            'if ($LASTEXITCODE -ne 0) { throw "Caption outline p95 exceeded its reference budget" }',
        ])
        self.assertNotIn("if", prior)

    def test_always_upload_exact_top_level_report_without_seed_or_data(self):
        upload = next(step for step in self.steps
                      if step.get("name") == "Upload offline reliability evidence")
        self.assertEqual(upload["if"], "always()")
        paths = upload["with"]["path"].splitlines()
        self.assertEqual([path for path in paths if "catalog" in path], [f"{OUTPUT}/report.json"])
        self.assertFalse(any(path in ("build", "build/", "build/reliability", "build/reliability/")
                             or "seed" in path or "/data" in path for path in paths))
        self.assertEqual(upload["with"]["retention-days"], 14)
        self.assertEqual(upload["with"]["if-no-files-found"], "warn")

    def test_existing_windows_job_budget_permissions_and_public_audit_stay(self):
        self.assertEqual(self.job["runs-on"], "windows-latest")
        self.assertEqual(self.job["timeout-minutes"], 45)
        self.assertNotIn("continue-on-error", self.job)
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        public = self.workflow["jobs"]["public-sample-audit"]
        self.assertNotIn("catalog_profile", str(public))
        self.assertNotIn(SCRIPT, str(public))
        for script in ("long-video-reliability.py", "scheduler-reliability.py", "cancel-reliability.py",
                       "full-local-task-reliability.py", "interrupted-task-reliability.py",
                       "local-range-acceptance.py", "progressive-slo.py"):
            gate = next(step for step in self.steps if script in step.get("run", ""))
            self.assertNotIn("if", gate)
            self.assertNotIn("continue-on-error", gate)


if __name__ == "__main__":
    unittest.main()
