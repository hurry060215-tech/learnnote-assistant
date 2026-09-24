from __future__ import annotations

import unittest

from app.claims import build_claim_evidence_map, safe_claim_projection
from app.models import TranscriptResult, TranscriptSegment, VisualWindow


class ClaimEvidenceTests(unittest.TestCase):
    def test_document_evidence_supports_direct_claims_and_keeps_locator_metadata(self):
        document_source = {
            "evidence_id": "material-doc-001",
            "source_type": "markdown",
            "source_uri": "https://docs.example/reference?token=private",
            "locator": "page 12 · sorting",
            "text": "A list.sort call mutates the list in place and returns no new list.",
            "metadata": {"material_id": "doc-001"},
        }
        transcript = TranscriptResult(full_text="", segments=[])
        result = build_claim_evidence_map(
            "document-task",
            "Public reference",
            document_source["text"],
            transcript,
            document_evidence=[document_source],
        )

        claim = result["claims"][0]
        self.assertEqual(result["schema_version"], 5)
        self.assertEqual(claim["claim_type"], "document")
        self.assertEqual(claim["verification"], "direct")
        self.assertEqual(claim["evidence_ids"], ["material-doc-001"])
        self.assertEqual(result["counts"]["document"], 1)
        self.assertEqual(result["evidence"][0]["locator"], "page 12 · sorting")
        self.assertEqual(result["evidence"][0]["material_id"], "doc-001")
        self.assertIn("token=<redacted>", result["evidence"][0]["source_uri"])

    def test_source_supported_hedged_statement_is_not_mislabeled_as_author_inference(self):
        sentence = "压力变化可能与温度有关。"
        transcript = TranscriptResult(segments=[TranscriptSegment(start=0, end=5, text=sentence)], full_text=sentence)
        claim = build_claim_evidence_map("hedged", "fixture", sentence, transcript)["claims"][0]
        self.assertEqual(claim["verification"], "direct")
        self.assertEqual(claim["claim_type"], "transcript")
        self.assertFalse(claim["review_required"])

    def test_document_lexical_match_only_locates_a_conflict_and_v4_maps_migrate(self):
        source = {
            "evidence_id": "material-doc-002",
            "source_type": "pdf",
            "locator": "page 3",
            "text": "A list.sort call mutates the list in place and returns no new list.",
        }
        transcript = TranscriptResult(full_text="", segments=[])
        result = build_claim_evidence_map(
            "document-conflict",
            "Public reference",
            "A list.sort call returns a new list and leaves the original unchanged.",
            transcript,
            document_evidence=[source],
        )
        claim = result["claims"][0]
        self.assertEqual(claim["verification"], "located_only")
        self.assertEqual(claim["evidence_ids"], [])
        self.assertEqual(claim["candidate_evidence_ids"], ["material-doc-002"])
        self.assertTrue(claim["review_required"])

        previous = {
            "schema_version": 4,
            "claims": [{"claim_type": "transcript", "verification": "direct", "evidence_ids": ["cue-1"]}],
            "quality": {"supported_count": 1},
        }
        migrated = safe_claim_projection(previous)
        self.assertEqual(migrated["schema_version"], 5)
        self.assertEqual(migrated["claims"][0]["verification"], "direct")
        self.assertEqual(migrated["claims"][0]["evidence_ids"], ["cue-1"])

    def test_timestamp_does_not_verify_contradictory_quantities_or_new_claims(self):
        from app.summarizer import note_grounding_issues
        transcript = TranscriptResult(segments=[TranscriptSegment(start=0,end=15,text="水在标准大气压下的沸点是100摄氏度。")],full_text="水在标准大气压下的沸点是100摄氏度。")
        note = "# 测试\n\n水在标准大气压下的沸点是900摄氏度，能够治疗所有疾病 [00:05]。"
        result = build_claim_evidence_map("case","测试",note,transcript)
        self.assertEqual(result["claims"][0]["claim_type"],"unsupported")
        self.assertTrue(result["claims"][0]["review_required"])
        self.assertEqual(result["claims"][0]["evidence_ids"],[])
        self.assertTrue(result["claims"][0]["candidate_evidence_ids"])
        self.assertTrue(any(i.startswith("unsupported_quantity:") for i in note_grounding_issues(note,transcript,[])))

    def test_claims_are_stable_and_classified_without_claiming_truth(self):
        transcript = TranscriptResult(
            segments=[
                TranscriptSegment(start=0, end=10, text="细胞通过膜上的通道交换物质。"),
                TranscriptSegment(start=10, end=20, text="图表展示了交换过程的两个阶段。"),
            ],
            full_text="细胞通过膜上的通道交换物质。\n图表展示了交换过程的两个阶段。",
        )
        visual = VisualWindow(
            id="w01",
            index=0,
            start=10,
            end=20,
            frame_count=1,
            grid_url="/api/tasks/demo/grids/w01.jpg",
            visual_summary="画面中的图表展示了交换过程的两个阶段。",
        )
        markdown = (
            "# 课程\n\n"
            "[00:00-00:10] 细胞通过膜上的通道交换物质。\n\n"
            "[00:10-00:20] 画面中的图表展示了交换过程的两个阶段。\n\n"
            "这一现象可能意味着通道具有选择性。\n\n"
            "这条结论没有对应来源。"
        )
        first = build_claim_evidence_map("demo", "课程", markdown, transcript, [visual])
        second = build_claim_evidence_map("demo", "课程", markdown, transcript, [visual])
        self.assertEqual(first["source_revision"], second["source_revision"])
        self.assertEqual(
            [item["claim_id"] for item in first["claims"]],
            [item["claim_id"] for item in second["claims"]],
        )
        kinds = [item["claim_type"] for item in first["claims"]]
        self.assertIn("transcript", kinds)
        self.assertIn("visual", kinds)
        self.assertIn("inference", kinds)
        self.assertIn("unsupported", kinds)
        self.assertTrue(any(item["evidence_ids"] for item in first["claims"]))
        self.assertEqual(first["quality"]["contract"], "links are navigable evidence, not factual truth verification")


if __name__ == "__main__":
    unittest.main()
