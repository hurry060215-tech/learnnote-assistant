"""Literal/source-only relation contracts, including misleading counterexamples."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from app.concept_identity import evidence_fingerprint
from app.concept_relations import assertions, build_relations, normalize_label
from app.graph_snapshot import digest

HISTORY = {"schema_version": 1, "course_id": "a" * 32, "events": []}


def evidence(key, text, owner=None, **changes):
    owner = owner or key
    item = {"evidence_id": key, "text": text, "title": owner, "source_uri": f"local://tasks/{owner}", "source_type": "video",
            "task_id": owner, "locator": "1-4s", "metadata": {"start": 1, "end": 4, "kind": "transcript"},
            "canonical_owner": {"kind": "task", "id": owner}, "source_identity": digest(["source", owner]), **changes}
    item["original_fingerprint"] = evidence_fingerprint(item)
    return item


class ConceptRelationTests(unittest.TestCase):
    def graph(self, *rows, **options):
        return build_relations(list(rows), HISTORY, **options)

    def test_same_assertion_is_attribution_not_truth_and_has_two_distinct_sources(self):
        graph = self.graph(evidence("a", "Gradient descent requires gradients."), evidence("b", "Gradient descent requires gradients."))
        self.assertEqual(len(graph["edges"]), 1)
        edge = graph["edges"][0]
        self.assertEqual((edge["kind"], edge["relation"]), ("source_assertion", "same_quoted_assertion"))
        self.assertFalse(edge["truth_verified"])
        self.assertEqual(edge["evidence_ids"], ["a", "b"])
        self.assertEqual(len(graph["nodes"]), 2)
        for citation in edge["citations"]:
            self.assertEqual(citation["quote"], "Gradient descent requires gradients.")
            self.assertEqual(citation["locator"], "1-4s")
            self.assertEqual(citation["anchors"]["start"], 1)
        self.assertIn("不证明内容真实", graph["warning"])

    def test_negation_difference_is_an_inference_with_both_opposite_quotes(self):
        graph = self.graph(evidence("a", "Gradient descent requires gradients."), evidence("b", "Gradient descent does not require gradients."))
        edge = graph["edges"][0]
        self.assertEqual((edge["kind"], edge["relation"]), ("inferred", "possible_negation_difference"))
        self.assertEqual({row["polarity"] for row in edge["citations"]}, {"positive", "negative"})
        self.assertTrue(graph["inference"])
        self.assertFalse(edge["truth_verified"])

    def test_chinese_explicit_statements_and_negation_keep_original_sentence(self):
        graph = self.graph(evidence("a", "梯度下降需要梯度。"), evidence("b", "梯度下降不需要梯度。"))
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual([row["quote"] for row in graph["edges"][0]["citations"]], ["梯度下降需要梯度。", "梯度下降不需要梯度。"])

    def test_orthographic_normalization_keeps_spelling_and_does_not_claim_synonyms(self):
        graph = self.graph(evidence("a", "  CAFÉ   contains caffeine.  "), evidence("b", "Cafe\u0301 contains caffeine."))
        self.assertEqual(len(graph["edges"]), 1)
        node = next(node for node in graph["nodes"] if node["label"] == "café")
        self.assertEqual(set(node["spellings"]), {"CAFÉ", "Cafe\u0301"})
        self.assertFalse(node["meaning_verified"])
        self.assertEqual(normalize_label("Ⅰ"), "ⅰ", "No NFKC compatibility conflation")
        self.assertEqual(self.graph(evidence("a", "Optimizer requires gradients."), evidence("b", "Gradient descent requires gradients."))["edges"], [])

    def test_no_false_corrobation_from_duplicates_or_registered_copies(self):
        a = evidence("a", "Gradient descent requires gradients.", owner="same")
        for b in (a, evidence("b", a["text"], owner="same"), evidence("b", a["text"], source_identity=a["source_identity"])):
            with self.subTest(b=b["evidence_id"]):
                self.assertEqual(self.graph(a, b)["edges"], [])
        self.assertEqual(self.graph(a, evidence("b", "Gradient descent does not require gradients.", owner="same"))["edges"], [])

    def test_no_cooccurrence_semantic_claim_and_no_partial_sentence_or_qualifier_loss(self):
        unsupported = [
            "Gradient descent and gradients are mentioned together.",
            "If conditions hold gradient descent requires gradients.",
            "Gradient descent requires gradients under smoothness assumptions.",
            "According to Alice gradient descent requires gradients.",
            "Alice says gradient descent requires gradients.",
            "Gradient descent may require gradients.",
            "Gradient descent does not always require gradients.",
            "Gradient descent requires gradients, but exceptions exist.",
            "Gradient descent requires gradients?", "Gradient descent requires gradients...", '"Gradient descent requires gradients."',
            "A. Gradient descent requires gradients.",
            "Gradient descent requires 1.5 derivatives.",
            "If conditions hold. Gradient descent requires gradients.",
            "It requires gradients.", "如果光滑则梯度下降需要梯度。", "梯度下降通常需要梯度。",
        ]
        for text in unsupported:
            with self.subTest(text=text):
                self.assertEqual(list(assertions(text)), [])
                self.assertEqual(self.graph(evidence("a", text), evidence("b", text))["edges"], [])

    def test_contextual_quotes_do_not_become_negation_conflicts(self):
        graph = self.graph(evidence("a", "If smooth:\nGradient descent requires gradients."), evidence("b", "Gradient descent does not require gradients."))
        self.assertEqual(graph["edges"], [])
        repeated = self.graph(evidence("a", "If smooth:\nGradient descent requires gradients."), evidence("b", "If smooth:\nGradient descent requires gradients."))
        self.assertEqual(repeated["edges"], [])
        for context in ("The following is false.", "If smooth:", "Unless smooth:"):
            self.assertEqual(self.graph(evidence("a", context + "\nGradient descent requires gradients."),
                                       evidence("b", "Gradient descent requires gradients."))["edges"], [])

    def test_source_time_filters_and_noncanonical_evidence_are_applied_before_edges(self):
        a, b = evidence("a", "Gradient descent requires gradients."), evidence("b", "Gradient descent requires gradients.")
        for options in ({"source_id": "a"}, {"source_kind": "material"}, {"start": 5}, {"end": 0}):
            self.assertEqual(self.graph(a, b, **options)["edges"], [])
        self.assertEqual(len(self.graph(a, b, start=2, end=3)["edges"]), 1)
        for changes in ({"source_type": "community"}, {"locator": "generated-note"}, {"metadata": {"review_required": True}}):
            self.assertEqual(self.graph(a, {**b, **changes})["edges"], [])

    def test_split_and_stale_user_identity_prevent_automatic_remerging(self):
        a, b = evidence("a", "Gradient descent requires gradients."), evidence("b", "Gradient descent requires gradients.")
        history = deepcopy(HISTORY)
        history["events"] = [{"id": "1" * 32, "request": {"term": "gradient descent", "label": "Specific use"}, "references": {"a": a["original_fingerprint"]}}]
        self.assertEqual(build_relations([a, b], history)["edges"], [])
        history["events"][0]["references"]["b"] = b["original_fingerprint"]
        self.assertEqual(len(build_relations([a, b], history)["edges"]), 1)
        history["events"][0]["references"]["b"] = "0" * 64
        self.assertEqual(build_relations([a, b], history)["edges"], [])

    def test_split_on_a_contained_keyword_is_preserved_for_longer_entity_labels(self):
        a, b = evidence("a", "Gradient descent requires gradients."), evidence("b", "Gradient descent requires gradients.")
        history = deepcopy(HISTORY)
        history["events"] = [{"id": "1" * 32, "request": {"term": "gradient", "label": "Specific use"}, "references": {"a": a["original_fingerprint"]}}]
        self.assertEqual(build_relations([a, b], history)["edges"], [])

    def test_inconsistent_identity_digest_cannot_create_two_sources_from_one_owner(self):
        a = evidence("a", "Gradient descent requires gradients.", owner="same")
        b = evidence("b", a["text"], owner="same", source_identity="f" * 64)
        self.assertEqual(self.graph(a, b)["edges"], [])

    def test_fail_closed_limits_and_stable_ordering(self):
        a, b = evidence("a", "Gradient descent requires gradients."), evidence("b", "Gradient descent requires gradients.")
        self.assertEqual(self.graph(a, b), self.graph(b, a))
        for constant in ("MAX_ROWS", "MAX_TEXT", "MAX_CHARACTERS", "MAX_RELATIONS"):
            with patch("app.concept_relations." + constant, 0), self.assertRaisesRegex(ValueError, "concept_relations_too_large"):
                self.graph(a, b)
        with self.assertRaisesRegex(ValueError, "invalid_comparison_filter"):
            self.graph(a, b, start=4, end=1)


if __name__ == "__main__":
    unittest.main()
