from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class PlatformWorkflowScopeTests(unittest.TestCase):
    def test_core_ci_keeps_full_pr_checks_and_main_release_pushes(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        events = workflow.get("on", workflow.get(True))
        self.assertEqual(events["push"]["branches"], ["main"])
        self.assertEqual(events["push"]["tags"], ["v*"])
        self.assertIn("pull_request", events)
        self.assertIsNone(events["pull_request"])
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertIn("checks", workflow["jobs"])
        self.assertIn("portable-asr", workflow["jobs"])
        self.assertIn("portable-ocr", workflow["jobs"])

    def test_feature_branches_keep_pr_matrix_without_duplicate_push_runs(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/platform-contracts.yml").read_text(encoding="utf-8"))
        events = workflow.get("on", workflow.get(True))
        self.assertEqual(events["push"]["branches"], ["main"])
        self.assertEqual(events["push"]["tags"], ["v*"])
        self.assertEqual(events["push"]["paths"], events["pull_request"]["paths"])
        self.assertNotIn("branches", events["pull_request"])
        self.assertIn("workflow_dispatch", events)
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        job = workflow["jobs"]["python-local-contract"]
        self.assertEqual(set(job["strategy"]["matrix"]["os"]), {"windows-latest", "ubuntu-latest", "macos-latest"})
        self.assertNotIn("continue-on-error", job)
