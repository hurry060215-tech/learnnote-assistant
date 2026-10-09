import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ProgressiveSloContractTests(unittest.TestCase):
    def test_p95_uses_nearest_rank_not_mean(self):
        spec = importlib.util.spec_from_file_location("progressive_slo", ROOT / "scripts/progressive-slo.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertEqual(module.percentile95(list(range(1, 21))), 19)
        self.assertEqual(module.percentile95([1, 100]), 100)

    def test_workflow_and_release_suite_enforce_full_reference_matrix(self):
        workflow = (ROOT / ".github/workflows/reliability.yml").read_text(encoding="utf-8")
        suite = (ROOT / "scripts/reliability-suite.py").read_text(encoding="utf-8")
        self.assertIn("progressive-slo.py --repetitions 20", workflow)
        self.assertIn("build/reliability/progressive-outline/report.json", workflow)
        self.assertIn("'progressive-slo.py', ['--repetitions', '20']", suite)
