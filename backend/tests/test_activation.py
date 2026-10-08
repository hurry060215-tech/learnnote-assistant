from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import activation
from app.routers import support


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_only_bounded_whitelisted_facts_are_saved(self):
        activation.record(self.root, "desktop_connected")
        activation.record_status(self.root, "running")
        activation.record_status(self.root, "success")
        activation.record_status(self.root, "failed", "download https://private.invalid/title Cookie=secret")
        result = activation.snapshot(self.root)
        self.assertEqual(set(result["fields"]), set(activation.FIELDS))
        self.assertEqual(result["fields"]["error_categories"], ["download"])
        self.assertFalse(result["remote_transport"])
        blob = (self.root / "activation.sqlite3").read_bytes()
        for value in (b"private.invalid", b"Cookie", b"secret"):
            self.assertNotIn(value, blob)
        with self.assertRaises(ValueError):
            activation.record(self.root, "arbitrary-url")

    def test_disable_and_clear_survive_restart_and_new_tasks(self):
        activation.record(self.root, "first_task_started")
        activation.set_enabled(self.root, False)
        activation.record(self.root, "first_task_succeeded")
        self.assertFalse(activation.snapshot(self.root)["fields"]["first_task_succeeded"])
        activation.clear(self.root)
        activation.record(self.root, "desktop_connected")
        state = activation.snapshot(self.root)
        self.assertFalse(state["enabled"])
        self.assertTrue(all(not state["fields"][key] for key in activation.MILESTONES))
        activation.set_enabled(self.root, True)
        self.assertTrue(activation.snapshot(self.root)["fields"]["installed"])

    def test_thirty_day_retention_expires_facts(self):
        activation.record(self.root, "first_task_succeeded")
        with sqlite3.connect(self.root / "activation.sqlite3") as db:
            db.execute("UPDATE facts SET recorded=?", (time.time() - 31 * 86400,))
        self.assertFalse(activation.snapshot(self.root)["fields"]["first_task_succeeded"])

    def test_concurrent_records_are_idempotent(self):
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda _: activation.record(self.root, "first_task_started"), range(20)))
        with sqlite3.connect(self.root / "activation.sqlite3") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM facts").fetchone()[0], 2)

    def test_full_disk_diagnostics_do_not_break_processing(self):
        with patch("app.activation.sqlite3.connect", side_effect=sqlite3.OperationalError("disk full")):
            activation.record_status(self.root, "success")

    def test_preview_export_field_allowlist_and_no_send_route(self):
        app = FastAPI(); app.include_router(support.router)
        client = TestClient(app)
        with patch.object(support, "DATA_DIR", self.root):
            activation.record(self.root, "installed")
            payload = {"fields": ["installed", "version"]}
            preview = client.post("/api/support/preview", json=payload)
            exported = client.post("/api/support/export", json=payload)
            self.assertEqual(preview.json(), exported.json())
            self.assertEqual(set(exported.json()), {"installed", "version"})
            self.assertIn("attachment", exported.headers["content-disposition"])
            for invalid in ({"fields": ["title"]}, {"fields": ["version", "version"]}, {"fields": [], "url": "https://example.com"}):
                self.assertEqual(client.post("/api/support/export", json=invalid).status_code, 422)
            self.assertEqual(client.post("/api/support/send", json={}).status_code, 404)
            self.assertFalse(client.delete("/api/support/activation").json()["enabled"])
