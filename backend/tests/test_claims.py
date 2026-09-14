from __future__ import annotations

import unittest

from app.claims import build_claim_evidence_map
from app.models import TranscriptResult, TranscriptSegment, VisualWindow


class ClaimEvidenceTests(unittest.TestCase):
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
