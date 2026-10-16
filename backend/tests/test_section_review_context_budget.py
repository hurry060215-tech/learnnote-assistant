"""Source selection keeps context bundles, without claiming semantic retrieval."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.section_review_sources import select_inputs


class ReviewContextBudgetTests(TestCase):
    def select(self, texts, ranked, **budgets):
        claims = [{"text": f"Claim number {index + 1} needs review.", "evidence_ids": [],
                   "candidate_evidence_ids": [f"source-{item}" for item in candidates],
                   "verification": "located_only"} for index, candidates in enumerate(ranked)]
        section = {"id": "section", "markdown": "\n\n".join(item["text"] for item in claims)}
        mapped = {"claims": claims, "evidence": [{"evidence_id": f"source-{index}", "text": text,
                  "locator": f"cue {index}"} for index, text in enumerate(texts)]}
        snapshot = {"task": SimpleNamespace(id="fixture"), "sections": [section]}
        with patch("app.section_review_sources.mapped_section", return_value=mapped), \
             patch.multiple("app.section_review_sources", **{"MAX_SOURCE_CHARACTERS": 12000, **budgets}):
            return select_inputs(snapshot, "section", 0, lambda text: text)

    def test_oversized_context_cannot_drop_neighbor_negation_and_send_positive_fragment(self):
        result = self.select(["The proposed rule is rejected: " + "x" * 11980,
                              "The device always succeeds.", "The statement above is false."], [[1]])
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["blocking_reason"], "review_source_insufficient")
        self.assertTrue(result["coverage"]["source_truncated"])
        self.assertEqual(result["coverage"]["claim_candidate_coverage"][0]["complete_context_candidates"], 0)

    def test_best_candidate_is_selected_before_earlier_low_rank_candidate(self):
        result = self.select(["Earlier low-rank cue.", "Its neighbor.", "Unrelated separator.",
                              "Relevant context.", "Best-ranked source.", "Important qualification."], [[4, 0]],
                             MAX_SOURCE_ITEMS=3)
        self.assertEqual([item["evidence_id"] for item in result["evidence"]], ["source-3", "source-4", "source-5"])
        self.assertEqual(result["coverage"]["claim_candidate_coverage"][0]["complete_context_candidates"], 1)
        self.assertTrue(result["coverage"]["source_truncated"])

    def test_claims_are_interleaved_before_one_claims_lower_ranked_candidates(self):
        result = self.select([f"Complete original cue {index}." for index in range(12)], [[1, 5], [9]],
                             MAX_SOURCE_ITEMS=6)
        self.assertEqual([item["evidence_id"] for item in result["evidence"]],
                         [f"source-{index}" for index in (0, 1, 2, 8, 9, 10)])
        self.assertEqual([item["complete_context_candidates"] for item in result["coverage"]["claim_candidate_coverage"]], [1, 1])
        self.assertLessEqual(result["coverage"]["source_characters"], 12000)
        self.assertEqual([item["source_alias"] for item in result["evidence"]], [f"E{i + 1}" for i in range(6)])

    def test_shared_adjacent_context_is_deduplicated_and_never_cut(self):
        texts = ["Leading condition.", "First candidate.", "Second candidate.", "Trailing exception."]
        result = self.select(texts, [[1], [2]], MAX_SOURCE_ITEMS=4)
        self.assertEqual([item["text"] for item in result["evidence"]], texts)
        self.assertEqual(result["coverage"]["source_characters"], sum(map(len, texts)))
        self.assertFalse(result["coverage"]["source_truncated"])
        self.assertIsNone(result["blocking_reason"])
