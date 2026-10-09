from contextlib import ExitStack, closing
import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import SourceEvidence, StudyCard
from app.knowledge import add_evidence
from app.study import (clear_study_data, delete_study_card, edit_card_content, export_study_data,
                       list_cards, record_activity, remove_cards_for_evidence, restore_study_data,
                       review_card, save_cards, set_card_status, study_dashboard, update_study_plan)
from app.study import question_for_card, submit_answer


QUOTE = "Word vectors are numerical representations of words in a learned vector space."


class ObjectiveStudyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in ("study", "knowledge"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        add_evidence(SourceEvidence(evidence_id="original", text=QUOTE, title="Synthetic definition"))
        self.card = save_cards([StudyCard(front="What are word vectors?", back=QUOTE, source_evidence_ids=["original"])])[0]
        self.client = TestClient(app)

    def submit(self, answer="Word vectors", key="one", revision=None):
        return submit_answer(self.card.card_id, revision or question_for_card(self.card.card_id)["question_revision"], answer, key)

    def test_reading_getting_question_answering_and_self_rating_are_independent(self):
        question = question_for_card(self.card.card_id)
        self.assertTrue(question["available"])
        self.assertNotIn("expected_answer", question)
        self.assertNotIn("Word vectors", question["question"])
        self.assertEqual(export_study_data()["quiz_attempts"], [])
        record_activity("reading", f"card:{self.card.card_id}", idempotency_key="view")
        record_activity("reading", f"card:{self.card.card_id}", idempotency_key="view")
        record_activity("answer", f"card:{self.card.card_id}")  # Unscored legacy event.
        record_activity("self_assessment", f"card:{self.card.card_id}")
        review_card(self.card.card_id, 4)
        before = list_cards()[0]
        result = self.submit("  WORD  vectors  ")
        self.assertTrue(result["correct"])
        self.assertEqual(result["source_evidence_ids"], ["original"])
        self.assertEqual(list_cards()[0], before, "Objective attempts must not alter FSRS self-ratings")
        measures = study_dashboard()["progress"]["measures"]
        self.assertEqual({key: measures[key] for key in ("reading_events", "objective_attempts", "correct_answers", "unscored_answer_events", "self_explanations", "self_ratings")},
                         dict.fromkeys(("reading_events", "objective_attempts", "correct_answers", "unscored_answer_events", "self_explanations", "self_ratings"), 1))
        self.assertEqual(measures["legacy_correctness"], "unknown")

    def test_incorrect_and_self_assessed_mistakes_remain_distinct_and_scoped(self):
        self.assertFalse(self.submit("similar meaning")["correct"])
        review_card(self.card.card_id, 1)
        dashboard = study_dashboard(evidence_ids={"original"})
        objective = dashboard["objective_mistakes"][0]
        self.assertEqual(objective["answer"], "Word vectors")
        self.assertEqual(objective["basis"], "objective_answer")
        self.assertEqual(objective["source_evidence_ids"], ["original"])
        self.assertEqual(dashboard["mistakes"][0]["basis"], "self_assessment")
        self.assertIsNone(dashboard["mistakes"][0]["correct"])
        self.assertEqual(study_dashboard(evidence_ids={"another"})["objective_mistakes"], [])
        self.assertEqual(dashboard["progress"]["measures"]["incorrect_answers"], 1)

    def test_repeat_submission_replays_result_but_cannot_change_answer(self):
        first = self.submit()
        self.assertEqual(first, self.submit())
        with self.assertRaisesRegex(ValueError, "quiz_submission_conflict"):
            self.submit("wrong")
        self.assertEqual(len(export_study_data()["quiz_attempts"]), 1)
        with self.assertRaisesRegex(ValueError, "idempotency"):
            self.submit(key="")

    def test_concurrent_duplicate_submissions_create_one_attempt(self):
        from concurrent.futures import ThreadPoolExecutor
        revision = question_for_card(self.card.card_id)["question_revision"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.submit(revision=revision), range(4)))
        self.assertEqual(len({item["attempt_id"] for item in results}), 1)
        self.assertEqual(len(export_study_data()["quiz_attempts"]), 1)

    def test_edit_rejects_stale_submission_preserves_snapshot_and_schedule(self):
        first = self.submit("wrong")
        before = review_card(self.card.card_id, 3)
        edit_card_content(self.card.card_id, "Changed question", QUOTE)
        with self.assertRaisesRegex(ValueError, "quiz_question_changed"):
            self.submit(key="stale", revision=first["question_revision"])
        self.assertEqual(self.submit("wrong", revision=first["question_revision"]), first)
        self.assertEqual(export_study_data()["quiz_attempts"][0], first)
        self.assertEqual(list_cards()[0].due_at, before.due_at)
        edit_card_content(self.card.card_id, "Changed question", "My own ungrounded explanation.")
        self.assertFalse(question_for_card(self.card.card_id)["available"])

    def test_changed_or_deleted_source_rejects_stale_questions(self):
        question = question_for_card(self.card.card_id)
        add_evidence(SourceEvidence(evidence_id="original", text="A source correction, no longer supporting the old answer."))
        self.assertFalse(question_for_card(self.card.card_id)["available"])
        with self.assertRaisesRegex(ValueError, "quiz_question_changed"):
            self.submit(revision=question["question_revision"])

    def test_current_owner_review_gate_blocks_existing_objective_question(self):
        from types import SimpleNamespace
        add_evidence(SourceEvidence(evidence_id="original", task_id="owner", text=QUOTE))
        with patch("app.study.get_task", return_value=SimpleNamespace(summary_source="transcript", summary_diagnostics={})):
            question = question_for_card(self.card.card_id)
            self.assertTrue(question["available"])
        for source, diagnostics in (("transcript-draft", {}), ("transcript", {"review_required": True})):
            with self.subTest(source=source), patch("app.study.get_task", return_value=SimpleNamespace(summary_source=source, summary_diagnostics=diagnostics)):
                self.assertFalse(question_for_card(self.card.card_id)["available"])
                with self.assertRaisesRegex(ValueError, "quiz_question_changed"):
                    self.submit(revision=question["question_revision"])
        self.assertEqual(export_study_data()["quiz_attempts"], [])

    def test_no_questions_for_missing_generated_community_corrupt_or_incomplete_evidence(self):
        for kind in ("note", "generated-note", "community"):
            add_evidence(SourceEvidence(evidence_id="original", text=QUOTE, metadata={"kind": kind}))
            self.assertFalse(question_for_card(self.card.card_id)["available"])
        for text in ("Word vectors are", "A vague unsupported answer", "Word vectors are numerical representations without an ending"):
            add_evidence(SourceEvidence(evidence_id="original", text=text))
            edit_card_content(self.card.card_id, "Prompt", text)
            self.assertFalse(question_for_card(self.card.card_id)["available"])
        card = save_cards([StudyCard(front="Missing", back=QUOTE, source_evidence_ids=["missing"])])[0]
        self.assertFalse(question_for_card(card.card_id)["available"])

    def test_chinese_cloze_has_deterministic_exact_scoring(self):
        quote = "学习率决定每一步参数更新的步长，并影响收敛速度。"
        add_evidence(SourceEvidence(evidence_id="original", text=quote))
        edit_card_content(self.card.card_id, "学习率是什么？", quote)
        question = question_for_card(self.card.card_id)
        self.assertTrue(question["question"].startswith("____决定"))
        self.assertTrue(self.submit("学习率")["correct"])
        self.assertFalse(self.submit("步长", key="second")["correct"])

    def test_matching_is_not_semantic_or_punctuation_insensitive(self):
        self.assertFalse(self.submit("Word vectors.")["correct"])
        self.assertFalse(self.submit("word embeddings", key="paraphrase")["correct"])
        self.assertTrue(self.submit("Word\n vectors", key="whitespace")["correct"])

    def test_paused_suspended_deleted_and_unknown_cards_cannot_create_attempts(self):
        revision = question_for_card(self.card.card_id)["question_revision"]
        update_study_plan("Paused", 10, True)
        with self.assertRaisesRegex(ValueError, "study_plan_paused"):
            self.submit()
        update_study_plan("Active", 10, False)
        set_card_status(self.card.card_id, "suspended")
        with self.assertRaisesRegex(ValueError, "card_not_active"):
            self.submit()
        delete_study_card(self.card.card_id)
        with self.assertRaisesRegex(ValueError, "card_not_found"):
            self.submit(revision=revision)
        with self.assertRaisesRegex(ValueError, "card_not_found"):
            record_activity("reading", f"card:{self.card.card_id}")

    def test_backup_roundtrip_and_legacy_restore_never_invent_correctness(self):
        self.submit()
        record_activity("reading", f"card:{self.card.card_id}", idempotency_key="view")
        review_card(self.card.card_id, 4)
        backup = export_study_data()
        clear_study_data()
        restored = restore_study_data(backup)
        self.assertEqual(restored["restored_quiz_attempts"], 1)
        self.assertEqual(export_study_data()["quiz_attempts"][0]["correct"], True)
        self.assertEqual(restore_study_data(backup)["restored_quiz_attempts"], 0)
        clear_study_data()
        legacy = copy.deepcopy(backup)
        legacy["schema_version"] = 3
        legacy.pop("quiz_attempts")
        legacy["activity_events"][0].pop("idempotency_key")
        restore_study_data(legacy)
        measures = study_dashboard()["progress"]["measures"]
        self.assertEqual(measures["correct_answers"], 0)
        self.assertEqual(measures["self_ratings"], 1)
        self.assertEqual(measures["legacy_correctness"], "unknown")

    def test_invalid_attempt_backup_is_rejected_before_writing(self):
        self.submit()
        backup = export_study_data()
        clear_study_data()
        backup["quiz_attempts"][0]["correct"] = False
        with self.assertRaisesRegex(ValueError, "study_backup_quiz_invalid"):
            restore_study_data(backup)
        backup["quiz_attempts"][0]["card_id"] = []
        with self.assertRaisesRegex(ValueError, "study_backup_quiz_invalid"):
            restore_study_data(backup)
        self.assertEqual(list_cards(), [])

    def test_additive_migration_retains_legacy_rows_without_scoring_them(self):
        legacy_root = self.root / "legacy"
        legacy_root.mkdir()
        with closing(sqlite3.connect(legacy_root / "study.sqlite3")) as db:
            db.executescript("""
                CREATE TABLE study_cards (card_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                front TEXT NOT NULL, back TEXT NOT NULL, source_evidence_ids TEXT NOT NULL,
                status TEXT NOT NULL, due_at TEXT NOT NULL, stability REAL NOT NULL, difficulty REAL NOT NULL,
                reps INTEGER NOT NULL, lapses INTEGER NOT NULL, last_reviewed_at TEXT NOT NULL);
                INSERT INTO study_cards VALUES ('old',3,'Old question','Old answer','["original"]','active',
                '2026-09-01T00:00:00+00:00',31,2,1,0,'2026-08-01T00:00:00+00:00');
                CREATE TABLE study_reviews (review_id INTEGER PRIMARY KEY AUTOINCREMENT, card_id TEXT NOT NULL,
                rating INTEGER NOT NULL, reviewed_at TEXT NOT NULL, due_at TEXT NOT NULL, stability REAL NOT NULL, difficulty REAL NOT NULL);
                INSERT INTO study_reviews VALUES (1,'old',4,'2026-08-01T00:00:00+00:00','2026-09-01T00:00:00+00:00',31,2);
                CREATE TABLE study_activity (activity_id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                source_id TEXT NOT NULL, occurred_at TEXT NOT NULL);
                INSERT INTO study_activity VALUES (1,'answer','card:old','2026-08-01T00:00:00+00:00');
            """)
            db.commit()
        with patch("app.study.DATA_DIR", legacy_root):
            from concurrent.futures import ThreadPoolExecutor
            from app.study import _connect
            with ThreadPoolExecutor(max_workers=16) as pool:
                list(pool.map(lambda _: _connect().close(), range(16)))
            snapshot = export_study_data()
            self.assertEqual(snapshot["cards"][0]["front"], "Old question")
            self.assertEqual(snapshot["reviews"][0]["rating"], 4)
            self.assertEqual(snapshot["activity_events"][0]["kind"], "answer")
            self.assertEqual(snapshot["quiz_attempts"], [])
            measures = study_dashboard()["progress"]["measures"]
            self.assertEqual(measures["unscored_answer_events"], 1)
            self.assertEqual(measures["self_ratings"], 1)
            self.assertEqual(measures["correct_answers"], 0)

    def test_card_source_and_all_data_deletion_include_attempts(self):
        for remove in (lambda: delete_study_card(self.card.card_id), lambda: remove_cards_for_evidence(["original"]), clear_study_data):
            if not list_cards():
                self.card = save_cards([StudyCard(front="Question", back=QUOTE, source_evidence_ids=["original"])])[0]
            self.submit()
            record_activity("reading", f"card:{self.card.card_id}")
            remove()
            self.assertEqual(export_study_data()["quiz_attempts"], [])
            self.assertEqual(export_study_data()["activity_events"], [])
            with closing(sqlite3.connect(self.root / "study.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM study_quiz_attempts").fetchone()[0], 0)

    def test_api_is_strict_local_and_rejects_stale_or_blank_answers(self):
        base = f"/api/study/cards/{self.card.card_id}"
        question = self.client.get(base + "/quiz").json()
        self.assertNotIn("expected_answer", question)
        payload = {"question_revision": question["question_revision"], "answer": "Word vectors", "idempotency_key": "api"}
        response = self.client.post(base + "/answer", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["attempt"]["correct"])
        self.assertEqual(self.client.post(base + "/answer", json={**payload, "answer": ""}).status_code, 422)
        self.assertEqual(self.client.post(base + "/answer", json={**payload, "correct": True}).status_code, 422)
        edit_card_content(self.card.card_id, "new", QUOTE)
        self.assertEqual(self.client.post(base + "/answer", json={**payload, "idempotency_key": "stale"}).status_code, 409)

    def test_quiz_api_errors_never_expose_private_exception_details(self):
        base = f"/api/study/cards/{self.card.card_id}"
        revision = question_for_card(self.card.card_id)["question_revision"]
        private_detail = "/private/synthetic/notes.md: source body includes PRIVATE_FIXTURE_TEXT"
        for function, suffix, method, payload in (
            ("question_for_card", "/quiz", "GET", None),
            ("submit_answer", "/answer", "POST", {"question_revision": revision, "answer": "Word vectors", "idempotency_key": "safe-error"}),
        ):
            with self.subTest(endpoint=suffix), patch(f"app.routers.knowledge_study.{function}", side_effect=ValueError(private_detail)):
                response = self.client.request(method, base + suffix, json=payload)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"]["code"], "quiz_unavailable")
                self.assertNotIn("/private/", response.text)
                self.assertNotIn("PRIVATE_FIXTURE_TEXT", response.text)
        self.assertEqual(export_study_data()["quiz_attempts"], [])

    def test_known_quiz_errors_have_literal_public_codes(self):
        base = f"/api/study/cards/{self.card.card_id}"
        payload = {"question_revision": question_for_card(self.card.card_id)["question_revision"], "answer": "Word vectors", "idempotency_key": "known-error"}
        for code, expected_status in (("card_not_found", 404), ("study_plan_paused", 409), ("quiz_question_changed", 409), ("invalid_quiz_answer", 422)):
            with self.subTest(code=code), patch("app.routers.knowledge_study.submit_answer", side_effect=ValueError(code)):
                response = self.client.post(base + "/answer", json=payload)
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.json()["detail"]["code"], code)


if __name__ == "__main__":
    unittest.main()
