"""Keep the optional observer confined to the existing offline resource matrix."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class VisualProcessTreeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / ".github/workflows/reliability.yml").read_text()
        cls.offline = cls.source.split("  offline-reliability:", 1)[1].split("  public-sample-audit:", 1)[0]
        cls.public = cls.source.split("  public-sample-audit:", 1)[1]

    def test_dependency_is_pinned_optional_and_offline_job_only(self):
        requirements = (ROOT / "scripts/requirements.benchmark.txt").read_text()
        self.assertIn("psutil==7.2.2", requirements)
        self.assertIn("-r scripts/requirements.benchmark.txt", self.offline)
        self.assertNotIn("requirements.benchmark.txt", self.public)
        self.assertNotIn("--sample-process-tree", self.public)
        for path in (ROOT / "backend").glob("requirements*.txt"):
            self.assertNotIn("requirements.benchmark", path.read_text(), path.name)
            self.assertNotIn("psutil", path.read_text(), path.name)

    def test_cache_key_and_both_event_filters_include_observer_inputs(self):
        cache = self.offline.split("cache-dependency-path: |", 1)[1].split("      - name:", 1)[0]
        self.assertIn("backend/requirements.test.txt", cache)
        self.assertIn("scripts/requirements.benchmark.txt", cache)
        events = self.source.split("permissions:", 1)[0]
        for path in ("scripts/owned_process_tree_sample.py", "scripts/requirements.benchmark.txt",
                     "scripts/tests/test_owned_process_tree_sample.py",
                     "scripts/tests/test_visual_process_tree_workflow.py"):
            self.assertEqual(events.count('"' + path + '"'), 2, path)

    def test_only_existing_three_long_durations_opt_in(self):
        self.assertIn("$durations = @(300, 1800, 3600, 10800)", self.offline)
        selected = re.search(r"if \(\$duration -in @\(([^)]+)\)\) \{\s*"
                             r'\$processTreeArgs = @\("--sample-process-tree"\)\s*\}', self.offline)
        self.assertIsNotNone(selected)
        self.assertEqual([int(value) for value in selected.group(1).split(",")], [1800, 3600, 10800])
        self.assertIn("$processTreeArgs = @()", self.offline)
        self.assertIn("--keep-artifacts @processTreeArgs", self.offline)
        self.assertEqual(self.source.count('"--sample-process-tree"'), 1)

    def test_existing_budgets_artifact_and_nonzero_propagation_remain(self):
        self.assertIn("--max-frames 40", self.offline)
        self.assertEqual(self.offline.count("--memory-budget-mb 512"), 2)
        self.assertEqual(self.offline.count("--min-free-disk-mb 512"), 2)
        self.assertIn('if ($LASTEXITCODE -ne 0) { throw "Long-video matrix failed at ${duration}s" }', self.offline)
        self.assertIn("build/reliability/long-video-matrix/**/report.json", self.offline)
        self.assertIn("timeout-minutes: 45", self.offline)
        self.assertIn("if: always()", self.offline)
        self.assertIn('python -m unittest discover scripts/tests -p "test_*process_tree*.py"', self.offline)
        for script in ("scheduler-reliability.py", "cancel-reliability.py", "full-local-task-reliability.py",
                       "interrupted-task-reliability.py", "local-range-acceptance.py", "progressive-slo.py"):
            self.assertIn(script, self.offline)


if __name__ == "__main__":
    unittest.main()
