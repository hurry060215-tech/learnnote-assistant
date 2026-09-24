from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "claim-evidence-benchmark.py"
SPEC = importlib.util.spec_from_file_location("claim_evidence_benchmark_test", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("claim evidence benchmark could not be loaded")
BENCHMARK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BENCHMARK
SPEC.loader.exec_module(BENCHMARK)


class ClaimEvidenceBenchmarkTests(unittest.TestCase):
    def test_public_gold_confusion_matrix_is_offline_and_review_conservative(self) -> None:
        report = BENCHMARK.evaluate()

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["case_count"], 60)
        self.assertEqual(report["source_count"], 12)
        self.assertEqual(report["language_counts"], {"en": 30, "zh": 30})
        self.assertFalse(report["network_attempted"])
        self.assertEqual(report["direct_support"]["precision"], 1.0)
        self.assertEqual(report["direct_support"]["recall"], 0.5)
        self.assertEqual(report["direct_support"]["false_direct_support_count"], 0)
        self.assertEqual(report["review_gate"]["precision"], 0.75)
        self.assertEqual(report["review_gate"]["recall"], 1.0)
        self.assertEqual(report["confusion_matrix"]["direct"]["located_only"], 10)
        self.assertEqual(report["confusion_matrix"]["direct"]["inference"], 2)
        self.assertIn("not general semantic accuracy", report["direct_support"]["contract"])

    def test_user_interface_distinguishes_all_review_states_and_document_sources(self) -> None:
        source = (ROOT / "web" / "desk.js").read_text(encoding="utf-8")
        for label in ("直接支持", "仅定位", "推断", "待核对"):
            self.assertIn(label, source)
        self.assertIn('"document": "文档"', source)
        self.assertIn('candidate.kind === "document"', source)
        self.assertIn("source-evidence-target", source)
        self.assertIn("Number(quality.direct_count || 0)", source)
        self.assertNotIn("quality.direct_count || quality.supported_count", source)


if __name__ == "__main__":
    unittest.main()
