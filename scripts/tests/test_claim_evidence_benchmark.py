from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "claim-evidence-benchmark.py"
SPEC = importlib.util.spec_from_file_location("claim_evidence_benchmark_test", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("claim evidence benchmark could not be loaded")
BENCHMARK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BENCHMARK
SPEC.loader.exec_module(BENCHMARK)


class ClaimEvidenceBenchmarkTests(unittest.TestCase):
    def test_candidate_source_recall_is_separate_from_semantic_support(self) -> None:
        report = BENCHMARK.evaluate()
        retrieval = report["candidate_retrieval"]
        self.assertEqual(retrieval["pooled_source_count"], 12)
        for mode in ("single_source", "pooled_sources"):
            supported = retrieval[mode]["supported_claims"]
            self.assertEqual(supported["case_count"], 24)
            self.assertEqual(supported["source_hit_count"], 23)
            self.assertEqual(supported["source_recall"], 23 / 24)
            self.assertEqual(supported["source_top1_count"], 23)
            self.assertEqual(supported["source_top3_count"], 23)
            self.assertEqual(supported["missed_case_ids"], ["410-paraphrase"])
            paraphrases = retrieval[mode]["supported_paraphrases"]
            self.assertEqual(paraphrases["case_count"], 12)
            self.assertEqual(paraphrases["source_recall"], 11 / 12)
        cases = {row["case_id"]: row for row in report["results"]}
        # Both receive the same inference status, but only one locates its source.
        for case_id, rank in (("concat-paraphrase", 1), ("410-paraphrase", None)):
            row = cases[case_id]
            self.assertEqual(row["predicted"], "inference")
            self.assertEqual(row["candidate_retrieval"]["pooled_sources"]["expected_source_rank"], rank)
        self.assertEqual(report["direct_support"]["recall"], 0.5)
        self.assertIn("not a candidate-retrieval or semantic-quality pass", report["status_scope"])

    def test_pooled_distractor_is_visible_without_becoming_a_support_match(self) -> None:
        report = BENCHMARK.evaluate()
        row = next(row for row in report["results"] if row["case_id"] == "python-sorted-unrelated")
        self.assertEqual(row["candidate_retrieval"]["single_source"]["candidate_count"], 0)
        pooled = row["candidate_retrieval"]["pooled_sources"]
        self.assertEqual(pooled["candidate_evidence_ids"], ["public-python-bool-int"])
        self.assertIsNone(pooled["expected_source_rank"])
        self.assertFalse(pooled["direct_source_linked"])
        self.assertEqual(pooled["predicted"], "located_only")
        self.assertEqual(report["candidate_retrieval"]["pooled_sources"]["gold_pending_review"]["cases_with_candidates"], [row["case_id"]])

    def test_wrong_source_ids_never_count_as_retrieval_hits(self) -> None:
        project = BENCHMARK.build_claim_evidence_map

        def wrong_candidates(*args, **kwargs):
            result = project(*args, **kwargs)
            for claim in result["claims"]:
                claim["candidate_evidence_ids"] = ["different-source"]
            return result

        with patch.object(BENCHMARK, "build_claim_evidence_map", side_effect=wrong_candidates):
            report = BENCHMARK.evaluate()
        for mode in ("single_source", "pooled_sources"):
            self.assertEqual(report["candidate_retrieval"][mode]["supported_claims"]["source_hit_count"], 0)
            self.assertEqual(report["candidate_retrieval"][mode]["supported_claims"]["source_recall"], 0.0)
        # Existing direct links/classification do not silently fill retrieval misses.
        self.assertEqual(report["direct_support"]["recall"], 0.5)

    def test_rank_cutoffs_do_not_count_every_hit_as_first(self) -> None:
        rows = []
        for rank in (2, 4):
            candidate = BENCHMARK._candidate_result({
                "candidate_evidence_ids": [f"other-{index}" for index in range(rank - 1)] + ["expected"],
                "evidence_ids": [], "verification": "located_only",
            }, "expected")
            self.assertEqual(candidate["expected_source_rank"], rank)
            rows.append({"case_id": f"rank-{rank}-paraphrase", "gold": "direct",
                         "candidate_retrieval": {"pooled_sources": candidate}})
        summary = BENCHMARK._candidate_summary(rows, "pooled_sources")["supported_claims"]
        self.assertEqual(summary["source_hit_count"], 2)
        self.assertEqual(summary["source_top1_count"], 0)
        self.assertEqual(summary["source_top3_count"], 1)
        self.assertEqual(summary["source_recall"], 1.0)

    def test_no_eligible_support_cases_reports_unknown_recall(self) -> None:
        corpus = json.loads(BENCHMARK.CORPUS.read_text(encoding="utf-8"))
        for source in corpus["sources"]:
            source["claims"] = [claim for claim in source["claims"] if claim["gold"] != "direct"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            path.write_text(json.dumps(corpus), encoding="utf-8")
            with patch.object(BENCHMARK, "CORPUS", path):
                report = BENCHMARK.evaluate()
        for mode in ("single_source", "pooled_sources"):
            for subset in ("supported_claims", "supported_paraphrases"):
                self.assertEqual(report["candidate_retrieval"][mode][subset]["case_count"], 0)
                self.assertIsNone(report["candidate_retrieval"][mode][subset]["source_recall"])

    def test_duplicate_source_identity_is_rejected(self) -> None:
        corpus = json.loads(BENCHMARK.CORPUS.read_text(encoding="utf-8"))
        corpus["sources"].append(corpus["sources"][0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            path.write_text(json.dumps(corpus), encoding="utf-8")
            with patch.object(BENCHMARK, "CORPUS", path):
                with self.assertRaisesRegex(ValueError, "invalid_public_source:python-list-sort"):
                    BENCHMARK.evaluate()

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
        timeline = (ROOT / "web" / "claim-timeline.js").read_text(encoding="utf-8")
        for label in ("直接支持", "仅定位", "推断", "待核对"):
            self.assertIn(label, source)
        self.assertIn('document: "文档"', timeline)
        self.assertIn("claimEvidenceStatus", source)
        anchor = (ROOT / "web" / "evidence-anchor.js").read_text(encoding="utf-8")
        self.assertIn('kind === "document"', anchor)
        self.assertIn("highlightMaterialSource", source)
        view = (ROOT / "web" / "evidence-source-view.js").read_text(encoding="utf-8")
        self.assertIn("source-evidence-target", view)
        self.assertIn("Number(quality.direct_count || 0)", source)
        self.assertNotIn("quality.direct_count || quality.supported_count", source)


if __name__ == "__main__":
    unittest.main()
