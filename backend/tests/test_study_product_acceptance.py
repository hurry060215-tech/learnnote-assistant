from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app
from app.models import SourceEvidence, StudyCard
from app.knowledge import add_evidence
from app.study import (clear_study_data, due_cards, export_study_data, propose_cards,
                       record_activity, review_card, save_cards, study_dashboard)


class StudyProductAcceptanceTests(unittest.TestCase):
    def test_note_only_and_community_sources_cannot_generate_or_save_quizzes(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            for module in ("study", "knowledge"):
                stack.enter_context(patch(f"app.{module}.DATA_DIR", Path(tmp)))
            sources = [SourceEvidence(evidence_id="generated", title="Note", locator="note", text="学习率决定每一步参数更新的步长，并影响收敛速度。", metadata={"kind":"note"}),
                       SourceEvidence(evidence_id="comment", title="Audience", text="学习率决定每一步参数更新的步长，并影响收敛速度。", metadata={"kind":"community"})]
            self.assertEqual(propose_cards(sources), [])
            client = TestClient(app)
            for source in sources:
                add_evidence(source)
                response = client.post("/api/study/cards", json={"cards":[{"front":"Question", "back":"Answer", "source_evidence_ids":[source.evidence_id]}]})
                self.assertEqual(response.status_code, 422)
            self.assertEqual(due_cards(), [])

    def test_course_filter_runs_before_pagination_and_counts_selected_due_cards(self):
        with tempfile.TemporaryDirectory() as tmp, patch("app.study.DATA_DIR", Path(tmp)):
            others = save_cards([StudyCard(front=f"Other {i}", back="Answer", source_evidence_ids=["other"]) for i in range(15)])
            selected = save_cards([StudyCard(front="Selected", back="Answer", source_evidence_ids=["selected"])])[0]
            dashboard = study_dashboard(limit=2, evidence_ids={"selected"})
            self.assertEqual(dashboard["today"]["due_count"], 1)
            self.assertEqual([item["card_id"] for item in dashboard["due_cards"]], [selected.card_id])
            self.assertEqual(dashboard["quiz_queue"][0]["source_evidence_ids"], ["selected"])
            review_card(selected.card_id, 1)
            for card in others:
                review_card(card.card_id, 1)
            dashboard = study_dashboard(limit=2, evidence_ids={"selected"})
            self.assertEqual([item["card_id"] for item in dashboard["mistakes"]], [selected.card_id])
            self.assertEqual(study_dashboard(evidence_ids=set())["today"]["due_count"], 0)

    def test_card_edit_preserves_anchors_schedule_and_exact_user_text_then_deletes_records(self):
        with tempfile.TemporaryDirectory() as tmp, patch("app.study.DATA_DIR", Path(tmp)):
            card = save_cards([StudyCard(front="Question", back="Answer", source_evidence_ids=["source"])])[0]
            reviewed = review_card(card.card_id, 1)
            record_activity("self_assessment", f"card:{card.card_id}")
            client = TestClient(app)
            response = client.put(f"/api/study/cards/{card.card_id}/content", json={"front":"我的 correction?", "back":"Original 英文\n  code spacing"})
            self.assertEqual(response.status_code, 200, response.text)
            edited = response.json()["card"]
            self.assertEqual(edited["source_evidence_ids"], ["source"])
            self.assertEqual(edited["due_at"], reviewed.due_at)
            self.assertEqual(edited["reps"], reviewed.reps)
            self.assertEqual(edited["back"], "Original 英文\n  code spacing")
            self.assertEqual(client.delete(f"/api/study/cards/{card.card_id}").status_code, 400)
            deleted = client.delete(f"/api/study/cards/{card.card_id}?confirm=delete_card")
            self.assertEqual(deleted.status_code, 200, deleted.text)
            backup = export_study_data()
            self.assertEqual(backup["cards"], [])
            self.assertEqual(backup["reviews"], [])
            self.assertEqual(backup["activity_events"], [])
            self.assertEqual(study_dashboard()["mistakes"], [])
            clear_study_data()
            self.assertTrue(all(not day["review_count"] for day in study_dashboard()["progress"]["activity"]))
