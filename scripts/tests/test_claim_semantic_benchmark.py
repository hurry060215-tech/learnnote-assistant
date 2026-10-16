"""Scoring/protocol tests use synthetic answers, never claim model quality."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("semantic_benchmark", ROOT / "scripts/claim-semantic-benchmark.py")
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


def response(label, sources, *, partial_quote=False):
    citations = [] if label == "insufficient" else [{"source_alias": source["source_alias"],
        "quote": source["text"][4:] if partial_quote else source["text"]} for source in sources]
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"judgments": [{
        "claim_alias": "C1", "verdict": label, "reason": "Synthetic protocol test only.", "citations": citations}]})}}]}


class SemanticBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.corpus = {"schema_version": 1, "corpus_id": "test-only", "provenance": "synthetic unit test",
            "cases": [{"case_id": label, "language": "en", "risk_tags": ["paraphrase"], "gold": label,
                "claim": "The device continues without power.", "evidence": [{"source_alias": "E1",
                "text": "The device cannot continue without power.", "locator": "fictional cue"}],
                "rationale": "Synthetic metric arithmetic, not gold adjudication.",
                "required_support_aliases": ["E1"] if label != "insufficient" else []}
                for label in BENCHMARK.LABELS]}

    def recordings(self, labels=None):
        return {"schema_version": 1, "corpus_sha256": BENCHMARK.digest(self.corpus),
            "run": {"kind": "synthetic_protocol_test", "model": "fixture", "recorded_at": "2026-10-16T00:00:00Z"},
            "results": [{"case_id": case["case_id"], "input_sha256": BENCHMARK.digest(BENCHMARK.request_for(case)),
                "response": response((labels or BENCHMARK.LABELS)[index], case["evidence"])}
                for index, case in enumerate(self.corpus["cases"])]}

    def read_recordings(self, value):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recorded.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return BENCHMARK.read_recordings(path, self.corpus)

    def test_gold_free_export_binds_complete_production_request(self):
        packet = BENCHMARK.export_requests(self.corpus)
        for case, item in zip(self.corpus["cases"], packet["requests"]):
            self.assertEqual(item["input_sha256"], BENCHMARK.digest(item["request"]))
            self.assertEqual(item["request"]["messages"], BENCHMARK.messages(BENCHMARK.inputs_for(case)))
            self.assertNotIn("rationale", json.dumps(item))
            self.assertNotIn('"gold"', json.dumps(item))
            self.assertNotIn("required_support_aliases", json.dumps(item))
        changed = deepcopy(self.corpus["cases"][0]); changed["evidence"][0]["text"] += " Changed."
        self.assertNotEqual(packet["requests"][0]["input_sha256"], BENCHMARK.digest(BENCHMARK.request_for(changed)))

    def test_unrun_is_explicit_and_zero_predictions_have_null_precision(self):
        result = BENCHMARK.evaluate(self.corpus)
        self.assertEqual(result["status"], "not_run")
        self.assertEqual(result["overall"]["assessed_count"], 0)
        self.assertIsNone(result["overall"]["supported"]["precision"])
        self.assertEqual(result["overall"]["supported"]["recall"], 0)
        self.assertEqual(result["overall"]["unsupported"]["recall"], 0)
        self.assertFalse(result["general_semantic_quality_verified"])
        self.assertFalse(result["network_attempted"])
        self.assertEqual(result["model_calls_performed"], 0)

    def test_all_insufficient_cannot_hide_paraphrase_false_negatives(self):
        result = BENCHMARK.evaluate(self.corpus, self.recordings(["insufficient"] * 3))
        self.assertEqual(result["overall"]["unsupported"]["precision"], 2 / 3)
        self.assertEqual(result["overall"]["unsupported"]["recall"], 1)
        self.assertEqual(result["overall"]["supported"]["recall"], 0)
        self.assertEqual(result["overall"]["contradicted"]["recall"], 0)
        self.assertEqual(result["by_language"]["en"]["case_count"], 3)

    def test_perfect_synthetic_responses_remain_fixture_measurements(self):
        result = BENCHMARK.evaluate(self.corpus, self.read_recordings(self.recordings()))
        self.assertEqual(result["overall"]["supported"]["precision"], 1)
        self.assertEqual(result["overall"]["supported"]["recall"], 1)
        self.assertEqual(result["overall"]["unsupported"]["precision"], 1)
        self.assertEqual(result["overall"]["unsupported"]["recall"], 1)
        self.assertEqual(result["evaluation_kind"], "synthetic_protocol_test")
        self.assertFalse(result["general_semantic_quality_verified"])
        self.assertNotEqual(result["status"], "pass")

    def test_missing_rejected_and_truncated_answers_remain_unassessed(self):
        recorded = self.recordings()
        recorded["results"][0]["response"] = response("supported", self.corpus["cases"][0]["evidence"], partial_quote=True)
        recorded["results"][1]["response"]["choices"][0]["finish_reason"] = "length"
        recorded["results"].pop()
        result = BENCHMARK.evaluate(self.corpus, recorded)
        self.assertEqual(result["outcomes"], {"rejected_protocol": 2, "missing_response": 1})
        self.assertEqual(result["overall"]["assessed_count"], 0)
        self.assertEqual(result["overall"]["unsupported"]["recall"], 0)

    def test_cross_source_attribution_is_separate_from_the_verdict(self):
        case = self.corpus["cases"][0]
        case["evidence"].append({"source_alias": "E2", "text": "A separate necessary condition.", "locator": "cue 2"})
        case["required_support_aliases"].append("E2")
        recorded = self.recordings()
        recorded["results"][0]["response"] = response("supported", case["evidence"][:1])
        result = BENCHMARK.evaluate(self.corpus, recorded)
        self.assertEqual(result["overall"]["supported"]["recall"], 1)
        self.assertFalse(result["results"][0]["attribution_complete"])
        self.assertEqual(result["overall"]["required_attribution"]["complete_count"], 1)

    def test_duplicates_unknown_cases_changed_prompt_and_corpus_are_rejected(self):
        base = self.recordings()
        mutations = [lambda value: value["results"].append(deepcopy(value["results"][0])),
            lambda value: value["results"][0].update(case_id="foreign"),
            lambda value: value["results"][0].update(input_sha256="0" * 64),
            lambda value: value.update(corpus_sha256="0" * 64),
            lambda value: value["run"].update(api_key="not-accepted")]
        for mutate in mutations:
            value = deepcopy(base); mutate(value)
            with self.assertRaises(ValueError): self.read_recordings(value)

    def test_literal_abstention_is_never_an_unsupported_prediction(self):
        result = BENCHMARK.evaluate(self.corpus, literal_baseline=True)
        self.assertEqual(result["evaluation_kind"], "literal_baseline")
        self.assertEqual(result["outcomes"], {"literal_abstention": 3})
        self.assertIsNone(result["overall"]["unsupported"]["precision"])
        self.assertEqual(result["overall"]["unsupported"]["recall"], 0)

    def test_independent_corpus_is_bounded_balanced_and_diverse(self):
        corpus = BENCHMARK.load_corpus()
        self.assertGreaterEqual(len(corpus["cases"]), 60)
        for language in ("en", "zh"):
            rows = [case for case in corpus["cases"] if case["language"] == language]
            self.assertGreaterEqual(len(rows), 25)
            self.assertEqual({case["gold"] for case in rows}, set(BENCHMARK.LABELS))
        tags = {tag for case in corpus["cases"] for tag in case["risk_tags"]}
        self.assertGreaterEqual(len(tags), 8)


if __name__ == "__main__":
    unittest.main()
