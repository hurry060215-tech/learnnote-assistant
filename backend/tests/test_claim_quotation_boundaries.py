"""Literal matching must retain scope; these do not measure semantic recall."""
from copy import deepcopy
import unittest

from app.claims import CLAIM_SCHEMA_VERSION, build_claim_evidence_map, safe_claim_projection
from app.models import TranscriptResult, TranscriptSegment


class ClaimQuotationBoundaryTests(unittest.TestCase):
    def projection(self, claim, source):
        return build_claim_evidence_map("boundary", "Fixture", claim, TranscriptResult(
            segments=[TranscriptSegment(start=0, end=10, text=source)]))

    def test_fragments_cannot_discard_conditions_qualifiers_attribution_or_units(self):
        cases = [
            ("只有盖板锁紧后，电机才能运行。", "电机才能运行。"),
            ("不能认为所有配置都安全；这项设置适用于测试环境。", "这项设置适用于测试环境。"),
            ("有人声称，两个按钮的功能完全相同。", "两个按钮的功能完全相同。"),
            ("误差上限为 2，单位为毫米而非厘米。", "误差上限为 2。"),
            ("If the cover is closed, the motor can run.", "The motor can run."),
            ("In this simulation only; every packet arrives.", "Every packet arrives."),
            ("The author incorrectly claims, all sorting methods are stable.", "All sorting methods are stable."),
            ("The label says Dr. Smith; the sample owner is someone else.", "Smith."),
            ("下面的说法是错误的。药物有效。", "药物有效。"),
            ("药物有效。上一句是一个错误示例。", "药物有效。"),
            ("该方法有效？", "该方法有效。"),
            ("It is safe?", "It is safe."),
        ]
        for source, claim in cases:
            with self.subTest(source=source, claim=claim):
                result = self.projection(claim, source)["claims"][0]
                self.assertNotEqual(result["verification"], "direct")
                self.assertEqual(result["evidence_ids"], [])
                self.assertTrue(result["review_required"])

    def test_matching_preserves_case_word_boundaries_and_technical_punctuation(self):
        cases = [
            ("The variable is user_id.", "The variable is userid."),
            ("The identifier is no one.", "The identifier is noone."),
            ("The identifier is US.", "The identifier is us."),
            ("The value is [1:20].", "The value is [1:30]."),
            ('The instruction is "delete".', "The instruction is delete."),
        ]
        for source, claim in cases:
            with self.subTest(source=source):
                self.assertNotEqual(self.projection(claim, source)["claims"][0]["verification"], "direct")

    def test_complete_anchors_and_edge_citations_remain_literal(self):
        cases = [
            ("只有盖板锁紧后，电机才能运行。", "只有盖板锁紧后，电机才能运行。"),
            ("If the cover is closed, the motor can run.", "[00:02] If the cover is closed, the motor can run."),
            ("The identifier is user_id.", "The identifier is user_id [00:02]."),
            ("样品保持低温。", "[00:01-00:03] 样品保持低温。"),
        ]
        for source, claim in cases:
            with self.subTest(source=source):
                result = self.projection(claim, source)["claims"][0]
                self.assertEqual(result["verification"], "direct")
                self.assertFalse(result["review_required"])

    def test_legacy_and_future_contracts_downgrade_without_losing_candidate_links(self):
        original = self.projection("电机才能运行。", "只有盖板锁紧后，电机才能运行。")
        for version in (1, 3, 4, 5, 6, "7", 7.9, True, CLAIM_SCHEMA_VERSION + 1):
            value = deepcopy(original)
            value["schema_version"] = version
            value["claims"][0].update(verification="direct", claim_type="transcript", review_required=False,
                                      evidence_ids=["previous-direct"], candidate_evidence_ids=["candidate"])
            value["counts"] = {"transcript": 1}
            value["quality"].update(supported_count=1, direct_count=1, coverage_ratio=1)
            before = deepcopy(value)
            result = safe_claim_projection(value)
            with self.subTest(version=version):
                self.assertTrue(result["requires_rebuild"])
                self.assertEqual(result["claims"][0]["verification"], "pending_review")
                self.assertEqual(result["claims"][0]["candidate_evidence_ids"], ["candidate", "previous-direct"])
                self.assertEqual(result["quality"]["direct_count"], 0)
                self.assertEqual(result["quality"]["supported_count"], 0)
                self.assertEqual(result["counts"]["transcript"], 0)
                self.assertEqual(safe_claim_projection(result), result)
                self.assertEqual(value, before)


if __name__ == "__main__":
    unittest.main()
