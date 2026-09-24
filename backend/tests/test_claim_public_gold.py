from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1].parent
SCRIPT = ROOT / "scripts" / "claim-evidence-benchmark.py"
SPEC = importlib.util.spec_from_file_location("claim_evidence_benchmark", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("claim evidence benchmark could not be loaded")
BENCHMARK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BENCHMARK
SPEC.loader.exec_module(BENCHMARK)


class PublicClaimGoldTests(unittest.TestCase):
    def test_public_manual_gold_reports_confusion_without_calling_it_semantic_accuracy(self) -> None:
        report = BENCHMARK.evaluate()

        self.assertEqual(report["status"], "pass")
        self.assertGreaterEqual(report["case_count"], 50)
        self.assertEqual(report["language_counts"], {"en": 30, "zh": 30})
        self.assertFalse(report["network_attempted"])
        self.assertEqual(report["direct_support"]["false_direct_support_count"], 0)
        self.assertEqual(report["review_gate"]["recall"], 1.0)
        self.assertEqual(report["direct_support"]["precision"], 1.0)
        self.assertLess(report["direct_support"]["recall"], 1.0)
        self.assertIn("not general semantic accuracy", report["direct_support"]["contract"])
        self.assertEqual(report["confusion_matrix"]["direct"]["located_only"], 10)


if __name__ == "__main__":
    unittest.main()
