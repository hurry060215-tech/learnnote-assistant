"""Deterministic original #136 criteria, including legacy plan migration."""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.models import StudyCard
from app.study import (activity_summary, due_cards, export_study_data, get_study_plan,
                       initialize_study_timezone, list_cards, record_activity,
                       restore_study_data, review_card, save_cards, study_dashboard,
                       study_summary, update_study_plan)


class StudyTimezoneAcceptanceTests(unittest.TestCase):
    def test_legacy_non_utc_choice_survives_browser_suggestion(self):
        for zone, expected in (("Asia/Shanghai", "Asia/Shanghai"), ("UTC", "America/New_York")):
            with self.subTest(zone=zone), tempfile.TemporaryDirectory() as tmp, patch("app.study.DATA_DIR", Path(tmp)):
                with closing(sqlite3.connect(Path(tmp) / "study.sqlite3")) as db:
                    db.execute("CREATE TABLE study_plans (plan_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, title TEXT NOT NULL, daily_target INTEGER NOT NULL, paused INTEGER NOT NULL, timezone TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
                    db.execute("INSERT INTO study_plans VALUES ('default', 1, 'Original title', 8, 0, ?, '', '')", (zone,))
                    db.commit()
                plan = initialize_study_timezone("America/New_York")
                self.assertEqual(plan.timezone, expected)
                self.assertTrue(plan.timezone_initialized)
                self.assertEqual(plan.title, "Original title")
                self.assertEqual(initialize_study_timezone("Asia/Tokyo").timezone, expected)

    def test_manual_timezone_response_and_backup_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, patch("app.study.DATA_DIR", Path(tmp)):
            plan = update_study_plan("My local plan", 4, False, "Asia/Shanghai")
            self.assertTrue(plan.timezone_initialized)
            self.assertEqual(plan, get_study_plan())
            backup = export_study_data()
            with tempfile.TemporaryDirectory() as restored, patch("app.study.DATA_DIR", Path(restored)):
                restore_study_data(backup)
                self.assertEqual(initialize_study_timezone("America/New_York").timezone, "Asia/Shanghai")

    def test_shanghai_and_new_york_dst_days_count_exact_utc_boundaries(self):
        cases = [
            ("Asia/Shanghai", "2026-03-08T05:00:00+00:00", "2026-03-07T16:00:00+00:00", "2026-03-08T16:00:00+00:00"),
            # DST spring-forward is a 23-hour day; fall-back is 25 hours.
            ("America/New_York", "2026-03-08T12:00:00+00:00", "2026-03-08T05:00:00+00:00", "2026-03-09T04:00:00+00:00"),
            ("America/New_York", "2026-11-01T12:00:00+00:00", "2026-11-01T04:00:00+00:00", "2026-11-02T05:00:00+00:00"),
            ("UTC", "2026-03-08T12:00:00+00:00", "2026-03-08T00:00:00+00:00", "2026-03-09T00:00:00+00:00"),
        ]
        for zone, now, first, next_day in cases:
            with self.subTest(zone=zone, now=now), tempfile.TemporaryDirectory() as tmp, patch("app.study.DATA_DIR", Path(tmp)):
                update_study_plan("Local plan", 3, False, zone)
                card = save_cards([StudyCard(front="Question", back="Answer", source_evidence_ids=["fixture"])])[0]
                with closing(sqlite3.connect(Path(tmp) / "study.sqlite3")) as db:
                    db.executemany("INSERT INTO study_reviews(card_id,rating,reviewed_at,due_at,stability,difficulty) VALUES (?,3,?,'',1,1)", [(card.card_id, first), (card.card_id, next_day)])
                    db.commit()
                record_activity("reading", occurred_at=first)
                record_activity("reading", occurred_at=next_day)
                with patch("app.study.datetime", wraps=datetime) as clock:
                    clock.now.return_value = datetime.fromisoformat(now)
                    summary = study_summary()
                    dashboard = study_dashboard()
                    activity = activity_summary(1)
                self.assertEqual(summary["reviewed_today"], 1)
                self.assertEqual(dashboard["today"]["remaining_target"], 2)
                self.assertEqual(activity["by_kind"]["review"], 1)
                self.assertEqual(activity["by_kind"]["reading"], 1)

    def test_paused_plan_keeps_cards_and_blocks_review_until_resumed(self):
        with tempfile.TemporaryDirectory() as tmp, patch("app.study.DATA_DIR", Path(tmp)):
            card = save_cards([StudyCard(front="Question", back="Answer", source_evidence_ids=["fixture"])])[0]
            update_study_plan("Paused", 2, True, "Asia/Shanghai")
            self.assertEqual(due_cards(), [])
            self.assertEqual(study_dashboard()["quiz_queue"], [])
            self.assertEqual(study_summary()["due_count"], 0)
            with self.assertRaisesRegex(ValueError, "study_plan_paused"):
                review_card(card.card_id, 3)
            for kind in ("reading", "answer", "self_assessment"):
                with self.assertRaisesRegex(ValueError, "study_plan_paused"):
                    record_activity(kind, f"card:{card.card_id}")
            self.assertEqual(export_study_data()["activity_events"], [])
            self.assertEqual(list_cards()[0].reps, 0)
            self.assertEqual(study_summary()["reviewed_today"], 0)
            update_study_plan("Resume", 2, False)
            result = review_card(card.card_id, 3)
            self.assertTrue(result.due_at.endswith("+00:00"))
            self.assertEqual(len(export_study_data()["cards"]), 1)
