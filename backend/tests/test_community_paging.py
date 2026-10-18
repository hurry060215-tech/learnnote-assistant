"""Saved-opinion pages are bounded, coherent, read-only and consent independent."""
import base64
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from app import community, community_paging, storage
from app.models import TaskRecord, SelectedOpinionPreviewRequest
from app.routers.knowledge_study import api_task_community_page, api_task_community_context, api_export_task_community_context


class CommunityPagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.addCleanup(patch.stopall)
        patch("app.community.DATA_DIR", self.root).start()
        patch("app.community.ensure_dirs").start()
        self.task = TaskRecord(id="test-page", source_type="current_page", title="Synthetic",
                               created_at="2026-01-01", updated_at="2026-01-01")
        self.serial = 0

    def seed(self, count):
        community.set_community_enabled(True)
        def identifier():
            self.serial += 1
            return SimpleNamespace(hex=f"{self.serial:032x}")
        with patch("app.community.uuid4", side_effect=identifier), patch("app.community.datetime") as clock:
            clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            for offset in range(0, count, 500):
                community.add_community_context(self.task.id, [{"text": f"Synthetic opinion {self.serial + index + 1}"}
                                                               for index in range(min(500, count - offset))])

    def page(self, **kwargs):
        return community_paging.list_community_page(self.task, **kwargs)

    def test_page_route_is_one_get_with_bounded_defaults_and_no_new_storage_schema(self):
        from app.main import app
        route = app.openapi()["paths"]["/api/tasks/{task_id}/community-context/page"]
        self.assertEqual(set(route), {"get"})
        params = route["get"]["parameters"]
        self.assertEqual([(item["name"], item["in"], item["required"]) for item in params],
                         [("task_id", "path", True), ("limit", "query", False), ("cursor", "query", False)])
        self.assertEqual(params[1]["schema"]["default"], 500)
        self.assertEqual(params[2]["schema"]["default"], "")
        self.assertEqual(community.COMMUNITY_CONTEXT_SCHEMA_VERSION, 1)

    def test_actual_http_page_status_and_query_contracts(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers.knowledge_study import task_study_router
        app = FastAPI()
        app.include_router(task_study_router)
        client = TestClient(app)
        path = f"/api/tasks/{self.task.id}/community-context/page"
        self.seed(501)
        with patch("app.routers.knowledge_study.get_task", return_value=self.task):
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            first = response.json()
            self.assertEqual((first["returned_count"], first["total_count"]), (500, 501))
            for params in ({"limit": 501}, {"limit": "invalid"}, {"cursor": "invalid"}):
                self.assertEqual(client.get(path, params=params).status_code, 422)
            self.seed(1)
            changed = client.get(path, params={"cursor": first["next_cursor"]})
            self.assertEqual(changed.status_code, 409)
            self.assertEqual(changed.json()["detail"]["code"], "community_page_changed")
            with patch.object(community_paging.sqlite3, "connect", side_effect=sqlite3.OperationalError("locked")):
                unavailable = client.get(path)
            self.assertEqual(unavailable.status_code, 503)
            self.assertEqual(unavailable.json()["detail"]["code"], "community_page_unavailable")
        with patch("app.routers.knowledge_study.get_task", side_effect=FileNotFoundError):
            self.assertEqual(client.get(path).status_code, 404)

    def test_absent_database_is_empty_read_only_and_has_no_task_lease(self):
        with patch("app.routers.knowledge_study.get_task", return_value=self.task), patch.object(storage, "task_state_transaction", side_effect=AssertionError("No read lease")):
            result = api_task_community_page(self.task.id)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["total_count"], 0)
        self.assertFalse(result["enabled"])
        self.assertFalse(result["has_more"])
        self.assertIsNone(result["next_cursor"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_500_501_2001_tied_rows_are_all_reachable_without_skip_or_duplicate(self):
        for count in (0, 500, 501, 2001):
            with self.subTest(count=count):
                community.clear_all_community_context()
                self.serial = 0
                self.seed(count)
                ids, page, revisions = [], self.page(), set()
                while True:
                    revisions.add(page["revision"])
                    self.assertLessEqual(len(page["items"]), 500)
                    self.assertEqual(page["total_count"], count)
                    self.assertEqual(page["offset"], len(ids))
                    self.assertEqual(page["returned_count"], len(page["items"]))
                    self.assertEqual(page["groups_scope"], "current_page_only")
                    self.assertFalse(page["evidence_eligible"])
                    ids.extend(row["item_id"] for row in page["items"])
                    self.assertEqual(page["has_more"], len(ids) < count)
                    if not page["has_more"]:
                        break
                    page = self.page(cursor=page["next_cursor"])
                self.assertEqual(ids, [f"{index:032x}" for index in range(1, count + 1)])
                self.assertEqual(len(revisions), 1)
                if count > 500:
                    previous = self.page(cursor=page["previous_cursor"])
                    self.assertEqual(previous["offset"], max(0, page["offset"] - 500))
                with patch("app.routers.knowledge_study.get_task", return_value=self.task):
                    self.assertEqual(len(api_task_community_context(self.task.id)["items"]), min(count, 500))
                    self.assertEqual(len(api_task_community_context(self.task.id, 2000)["items"]), min(count, 2000))
                    self.assertEqual(len(json.loads(api_export_task_community_context(self.task.id).body)["items"]), count)

    def test_new_page_tie_order_does_not_change_legacy_list_order(self):
        community.set_community_enabled(True)
        with patch("app.community.uuid4", side_effect=[SimpleNamespace(hex="b" * 32), SimpleNamespace(hex="a" * 32)]):
            community.add_community_context(self.task.id, [{"text": "First inserted opinion"}, {"text": "Second inserted opinion"}])
        self.assertEqual([row["text"] for row in community.list_community_context(self.task.id)["items"]],
                         ["First inserted opinion", "Second inserted opinion"])
        self.assertEqual([row["text"] for row in self.page()["items"]],
                         ["Second inserted opinion", "First inserted opinion"])

    def test_insert_delete_clear_disable_reenable_and_restart_reject_old_snapshot(self):
        actions = [lambda: self.seed(1), lambda: community.delete_community_item(self.task.id, f"{1:032x}"),
                   lambda: community.clear_community_context(self.task.id), lambda: community.clear_all_community_context(),
                   lambda: community.set_community_enabled(False),
                   lambda: (community.set_community_enabled(False), community.set_community_enabled(True))]
        for action in actions:
            community.clear_all_community_context(); self.seed(501)
            first = self.page(); action()
            with self.assertRaisesRegex(ValueError, "community_page_changed"):
                self.page(cursor=first["next_cursor"])
        self.seed(501); first = self.page()
        with patch.object(community_paging, "_PROCESS_NONCE", "new-process"):
            with self.assertRaisesRegex(ValueError, "community_page_changed"):
                self.page(cursor=first["next_cursor"])

    def test_task_source_revision_and_mutation_during_page_read_are_rejected(self):
        self.seed(501); first = self.page()
        for field, value in (("id", "other"), ("page_url", "https://example.org/new"), ("control_generation", "new"), ("updated_at", "new")):
            task = self.task.model_copy(update={field: value})
            with self.assertRaisesRegex(ValueError, "community_page_changed"):
                community_paging.list_community_page(task, cursor=first["next_cursor"])
        changed = self.task.model_copy(update={"control_generation": "changed-during-read"})
        with patch("app.routers.knowledge_study.get_task", side_effect=[self.task, changed]):
            with self.assertRaises(HTTPException) as caught:
                api_task_community_page(self.task.id)
        self.assertEqual(caught.exception.status_code, 409)

    def test_page501_remains_exactly_selectable_and_deletable_without_budget_expansion(self):
        self.seed(501); first = self.page(); last = self.page(cursor=first["next_cursor"])
        item = last["items"][0]
        self.assertEqual(community.selected_community_items(self.task.id, [item["item_id"]])[0]["text"], item["text"])
        self.assertTrue(community.delete_community_item(self.task.id, item["item_id"]))
        self.assertEqual(self.page()["total_count"], 500)
        with self.assertRaisesRegex(ValueError, "opinion_selection_changed"):
            community.selected_community_items(self.task.id, [item["item_id"]])
        with self.assertRaises(ValidationError):
            SelectedOpinionPreviewRequest(question="Question", selected_item_ids=[f"{n:032x}" for n in range(21)], base_url="http://127.0.0.1/v1", model="fixture")

    def test_cursor_and_page_limits_are_strict_and_cursor_contains_only_aggregate_identity(self):
        self.seed(501); first = self.page()
        decoded = json.loads(base64.urlsafe_b64decode(first["next_cursor"]))
        self.assertEqual(set(decoded), {"v", "task", "revision", "offset", "limit"})
        for limit in (0, 501, -1, True, "500"):
            with self.assertRaisesRegex(ValueError, "community_page_invalid"):
                self.page(limit=limit)
        for cursor in ("?", "a" * 1025, base64.urlsafe_b64encode(b"[]").decode()):
            with self.assertRaisesRegex(ValueError, "community_page_invalid"):
                self.page(cursor=cursor)
        for key, value in (("offset", True), ("offset", -1), ("offset", 10001), ("limit", 499), ("v", 2)):
            cursor = base64.urlsafe_b64encode(json.dumps({**decoded, key: value}).encode()).decode()
            with self.assertRaisesRegex(ValueError, "community_page_invalid"):
                self.page(cursor=cursor)

    def test_snapshot_stays_coherent_when_external_writer_commits_during_scan(self):
        self.seed(501)
        writer = sqlite3.connect(community._db_path())
        self.addCleanup(writer.close)
        writer.execute("PRAGMA journal_mode=WAL")
        original = community_paging._json
        changed = False
        def encode(value):
            nonlocal changed
            if isinstance(value, list) and len(value) == 7 and not changed:
                changed = True
                writer.execute("DELETE FROM community_context_items WHERE item_id=?", (f"{501:032x}",))
                writer.commit()
            return original(value)
        with patch.object(community_paging, "_json", side_effect=encode):
            page = self.page()
        self.assertTrue(changed)
        self.assertEqual(page["total_count"], 501)
        self.assertEqual(page["returned_count"], 500)
        with self.assertRaisesRegex(ValueError, "community_page_changed"):
            self.page(cursor=page["next_cursor"])
        self.assertEqual(self.page()["total_count"], 500)

    def test_locked_database_reports_unavailable_and_never_holds_task_lock(self):
        self.seed(1)
        writer = sqlite3.connect(community._db_path())
        writer.execute("BEGIN EXCLUSIVE")
        started, finished = threading.Event(), threading.Event()
        errors = []
        original = sqlite3.connect
        def connect(*args, **kwargs):
            self.assertFalse(storage._lock._is_owned())
            self.assertEqual(kwargs["timeout"], 0.25)
            started.set()
            return original(*args, **kwargs)
        def read():
            try:
                api_task_community_page(self.task.id)
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()
        try:
            with patch("app.routers.knowledge_study.get_task", return_value=self.task), patch.object(community_paging.sqlite3, "connect", side_effect=connect):
                thread = threading.Thread(target=read); thread.start()
                self.assertTrue(started.wait(2))
                self.assertTrue(storage._lock.acquire(timeout=0.1))
                storage._lock.release()
                self.assertTrue(finished.wait(3)); thread.join()
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], HTTPException)
            self.assertEqual(errors[0].status_code, 503)
            self.assertEqual(errors[0].detail["code"], "community_page_unavailable")
        finally:
            writer.rollback(); writer.close()
