from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("real_course_claim_audit", ROOT / "scripts" / "real-course-claim-audit.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RealCourseClaimAuditTests(unittest.TestCase):
    def test_local_timed_transcript_projects_claims_without_copying_transcript_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captions = root / "sample.vtt"
            captions.write_text(
                "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n"
                "A one-hot code assigns one coordinate per token.\n\n"
                "00:00:03.000 --> 00:00:05.000\n"
                "The green robot walks through the garden.\n",
                encoding="utf-8",
            )
            claims = root / "claims.json"
            claims.write_text(json.dumps({
                "schema_version": 1,
                "corpus_id": "local-vtt-contract",
                "source": {"title": "Fixture", "course_url": "https://example.org/course", "video_url": "https://youtube.com/watch?v=fixture"},
                "label_order": list(MODULE.LABELS),
                "cases": [
                    {"id": "direct", "start_seconds": 1, "end_seconds": 3, "text": "A one-hot code assigns one coordinate per token.", "gold": "direct"},
                    {"id": "unsupported", "start_seconds": 3, "end_seconds": 5, "text": "The garden is on the moon.", "gold": "pending_review"},
                ],
            }), encoding="utf-8")
            report = MODULE.audit(captions, claims)

        self.assertEqual(report["case_count"], 2)
        self.assertEqual(report["confusion_matrix"]["direct"]["direct"], 1)
        self.assertTrue(report["results"][0]["candidate_locators"])
        self.assertNotIn("transcript_text", report)
        self.assertNotIn("A one-hot code assigns", json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
