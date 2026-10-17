from __future__ import annotations

from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import community, community_capture as capture
from app.models import SourceIdentity, TaskRecord
from app.routers.knowledge_study import task_study_router, study_router


URL = "https://www.bilibili.com/video/BV1xx411c7mD?p=2"


class VisibleCommunityCaptureTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.tasks = self.root / "tasks"
        for module in ("community", "knowledge"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        self.stack.enter_context(patch("app.community.ensure_dirs"))
        self.stack.enter_context(patch("app.storage.TASK_DIR", self.tasks))
        self.stack.enter_context(patch.object(capture, "_previews", capture.OrderedDict()))
        self.task = TaskRecord(id="task1", source_type="current_page", title="Synthetic video", page_url=URL,
                               source_identity=SourceIdentity(page_url=URL, platform="bilibili", platform_id="BV1xx411c7mD"),
                               created_at="2026-10-16T12:00:00Z", updated_at="2026-10-16T12:00:00Z")
        self.write_task()
        app = FastAPI()
        app.include_router(task_study_router)
        app.include_router(study_router)
        self.client = TestClient(app)
        self.endpoint = "/api/tasks/task1/community-context"
        self.body = {"page_url": URL + "&token=synthetic-private-source#comment", "items": [
            {"kind": "comment", "text": "How does this step work?", "timestamp_seconds": None},
            {"kind": "danmaku", "text": "A useful example", "timestamp_seconds": 12.5},
        ]}
        community.set_community_enabled(True)

    def test_new_route_and_schema_contracts_are_independently_explicit(self):
        from app.routers.community_capture import community_capture_router
        app = FastAPI()
        app.include_router(community_capture_router, prefix="/api/tasks")
        schema = app.openapi()
        self.assertEqual(set(schema["paths"]), {"/api/tasks/{task_id}/community-context/preview", "/api/tasks/{task_id}/community-context/save"})
        for suffix, name in (("preview", "CommunityPreviewRequest"), ("save", "CommunitySaveRequest")):
            path = schema["paths"]["/api/tasks/{task_id}/community-context/" + suffix]
            self.assertEqual(set(path), {"post"})
            operation = path["post"]
            self.assertEqual(operation["operationId"], f"api_{suffix}_task_community_context_api_tasks__task_id__community_context_{suffix}_post")
            self.assertEqual(operation["requestBody"]["content"]["application/json"]["schema"], {"$ref": "#/components/schemas/" + name})
            self.assertTrue(operation["requestBody"]["required"])
        schemas = schema["components"]["schemas"]
        for name, properties in (("CommunityPreviewRequest", {"page_url", "items"}),
                                 ("CommunitySaveRequest", {"preview_id", "fingerprint", "selected_item_ids"}),
                                 ("VisibleCommunityItem", {"kind", "text", "timestamp_seconds"})):
            self.assertFalse(schemas[name]["additionalProperties"])
            self.assertEqual(set(schemas[name]["properties"]), properties)
            self.assertEqual(set(schemas[name]["required"]), properties - {"timestamp_seconds"})
        preview = schemas["CommunityPreviewRequest"]["properties"]
        self.assertEqual((preview["page_url"]["minLength"], preview["page_url"]["maxLength"]), (1, 2000))
        self.assertEqual((preview["items"]["minItems"], preview["items"]["maxItems"]), (1, 20))
        self.assertEqual(preview["items"]["items"], {"$ref": "#/components/schemas/VisibleCommunityItem"})
        item = schemas["VisibleCommunityItem"]["properties"]
        self.assertEqual(item["kind"]["enum"], ["comment", "danmaku"])
        self.assertEqual((item["text"]["minLength"], item["text"]["maxLength"]), (1, 2000))
        self.assertEqual(item["timestamp_seconds"]["anyOf"], [{"type": "number", "maximum": 604800, "minimum": 0}, {"type": "null"}])
        save = schemas["CommunitySaveRequest"]["properties"]
        self.assertEqual((save["selected_item_ids"]["minItems"], save["selected_item_ids"]["maxItems"]), (1, 20))
        for name in ("preview_id", "fingerprint"):
            self.assertEqual(save[name]["pattern"], r"^[a-f0-9]{64}$")

    def write_task(self):
        path = self.tasks / self.task.id / "task.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.task.model_dump_json(), encoding="utf-8")

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob("*") if path.is_file()}

    def preview(self, body=None):
        response = self.client.post(self.endpoint + "/preview", json=body or self.body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def save_body(self, preview, selected=None):
        return {"preview_id": preview["preview_id"], "fingerprint": preview["fingerprint"],
                "selected_item_ids": selected if selected is not None else [item["item_id"] for item in preview["items"]]}

    def test_preview_cancel_are_nonpersisting_and_save_keeps_only_reviewed_selection(self):
        before = self.snapshot()
        abandoned = self.preview()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(abandoned["persisted"])
        self.assertEqual(abandoned["storage"], "memory-only")
        self.assertEqual(abandoned["source_uri"], URL)
        self.assertFalse(abandoned["network_fetch_performed"])
        self.assertFalse(abandoned["model_request_performed"])
        capture.invalidate_community_previews("task1")  # Local cancellation/expiry writes nothing.
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(abandoned)).status_code, 409)
        preview = self.preview()
        selected = [preview["items"][1]["item_id"]]
        result = self.client.post(self.endpoint + "/save", json=self.save_body(preview, selected))
        self.assertEqual(result.status_code, 200, result.text)
        saved = result.json()
        self.assertEqual(saved["stored_count"], 1)
        self.assertEqual(saved["items"][0]["text"], "A useful example")
        self.assertEqual(saved["items"][0]["timestamp_seconds"], 12.5)
        self.assertEqual(saved["items"][0]["source_uri"], URL)
        self.assertEqual((self.tasks / "task1" / "task.json").read_bytes(), before["tasks/task1/task.json"][0])
        self.assertFalse((self.tasks / "task1" / "transcript.json").exists())
        from app.knowledge import search_evidence
        self.assertEqual(search_evidence("useful example"), [])
        self.assertFalse(saved["evidence_eligible"])
        exported = self.client.get(self.endpoint + "/export").json()
        self.assertEqual(len(exported["items"]), 1)
        self.assertEqual(exported["items"][0]["source_uri"], URL)
        item_id = exported["items"][0]["item_id"]
        self.assertEqual(self.client.delete(self.endpoint + "/" + item_id).status_code, 200)
        self.assertEqual(community.list_community_context("task1")["items"], [])

    def test_source_sanitizer_preserves_only_verified_part(self):
        for raw in (URL + "&auth=secret#anchor", URL.replace("www.", "") + "&tracking=x", URL.replace(".com/", ".com:443/")):
            self.assertEqual(community._safe_source_uri(raw), URL)
        first = "https://www.bilibili.com/video/BV1xx411c7mD"
        self.assertEqual(community.canonical_bilibili_source(first), first + "?p=1")
        self.assertEqual(community._safe_source_uri("https://example.com/?p=2&token=secret"), "https://example.com/")

    def test_unsupported_sources_fail_closed_without_fetching_or_persistence(self):
        before = self.snapshot()
        invalid = ["http://www.bilibili.com/video/BV1xx411c7mD?p=2", "file:///video/BV1xx411c7mD",
                   "https://b23.tv/BV1xx411c7mD", "https://m.bilibili.com/video/BV1xx411c7mD?p=2",
                   "https://www.bilibili.com.evil.example/video/BV1xx411c7mD?p=2",
                   "https://evil.example/bilibili.com/video/BV1xx411c7mD?p=2",
                   "https://user:pass@www.bilibili.com/video/BV1xx411c7mD?p=2",
                   URL.replace(".com/", ".com:444/"), URL.replace("/video/", "/other/"),
                   URL + "&p=2", URL.replace("p=2", "p=02"), URL.replace("p=2", "p=0"),
                   URL.replace("p=2", "p=-2"), URL.replace("p=2", "p=1000000"),
                   URL.replace("p=2", "p=2.0"), URL.replace("p=2", "p=%32%20"),
                   URL.replace("/video/", "/video/%2e%2e/"), URL + "\n"]
        for url in invalid:
            with self.subTest(url=url):
                response = self.client.post(self.endpoint + "/preview", json={**self.body, "page_url": url})
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(capture._previews)

    def test_video_part_and_task_identity_cannot_be_spoofed(self):
        for url in (URL.replace("p=2", "p=1"), URL.replace("BV1xx411c7mD", "BV1xx411c7mE")):
            response = self.client.post(self.endpoint + "/preview", json={**self.body, "page_url": url})
            self.assertEqual(response.status_code, 409)
        for field, value in (("page_url", URL.replace("p=2", "p=3")), ("platform", "youtube"), ("platform_id", "BV1xx411c7mE")):
            original = self.task.source_identity.model_copy(deep=True)
            setattr(self.task.source_identity, field, value)
            self.write_task()
            self.assertEqual(self.client.post(self.endpoint + "/preview", json=self.body).status_code, 409)
            self.task.source_identity = original
        self.task.mode = "page_text"
        self.write_task()
        self.assertEqual(self.client.post(self.endpoint + "/preview", json=self.body).status_code, 409)

    def test_missing_part_matches_explicit_one_and_empty_legacy_identity(self):
        first = URL.split("?")[0]
        self.task.page_url = first
        self.task.source_identity = SourceIdentity()
        self.write_task()
        preview = self.preview({**self.body, "page_url": first + "?p=1&token=secret"})
        self.assertEqual(preview["source_uri"], first + "?p=1")

    def test_strict_payload_limits_extra_fields_and_malformed_values(self):
        invalid = [[], {**self.body, "author": "someone"}, {**self.body, "items": []},
                   {**self.body, "items": self.body["items"] * 11},
                   {**self.body, "items": [{"kind": "comment", "text": "x" * 2001}]},
                   {**self.body, "items": [{"kind": "comment", "text": "x" * 2000}] * 11}]
        for field, value in (("kind", "author"), ("text", 123), ("text", None), ("timestamp_seconds", "12"),
                             ("timestamp_seconds", True), ("timestamp_seconds", -1), ("timestamp_seconds", 604801),
                             ("author_label", "Real Person"), ("source_uri", "https://evil.example")):
            item = {**self.body["items"][0], field: value}
            invalid.append({**self.body, "items": [item]})
        before = self.snapshot()
        for body in invalid:
            with self.subTest(body=body):
                response = self.client.post(self.endpoint + "/preview", json=body)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"]["code"], "community_capture_payload_invalid")
                self.assertNotIn("input", response.json()["detail"])
        for constant in ("NaN", "Infinity", "-Infinity"):
            raw = json.dumps({**self.body, "items": [{"kind": "comment", "text": "example", "timestamp_seconds": 0}]}).replace('"timestamp_seconds": 0', '"timestamp_seconds": ' + constant)
            response = self.client.post(self.endpoint + "/preview", content=raw, headers={"content-type": "application/json"})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(constant, response.text)
        self.assertEqual(self.snapshot(), before)
        boundary = {**self.body, "items": [{"kind": "comment", "text": str(index) + "x" * 1999} for index in range(10)]}
        self.assertEqual(len(self.preview(boundary)["items"]), 10)

    def test_privacy_filtering_before_memory_storage_and_deduplication(self):
        body = {**self.body, "items": [
            {"kind": "comment", "text": "Email learner@example.com or +1 (415) 555-0123 @realperson https://example.com/?token=private"},
            {"kind": "comment", "text": "credential sk-syntheticSecret123"},
            {"kind": "comment", "text": "Authorization: Bearer privateBearerValue"},
            {"kind": "comment", "text": "Cookie: SESSDATA=privateCookieValue"},
            {"kind": "comment", "text": "Why this example?"},
            {"kind": "comment", "text": "ＷＨＹ this example?", "timestamp_seconds": 70},
            {"kind": "comment", "text": "暂停"}, {"kind": "danmaku", "text": "加群领取优惠券"},
        ]}
        before = self.snapshot()
        preview = self.preview(body)
        self.assertEqual(preview["filtered_count"], 2)
        self.assertEqual(preview["deduplicated_count"], 1)
        self.assertEqual(len(preview["items"]), 5)
        self.assertEqual(self.snapshot(), before)
        cached = repr(capture._previews)
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(preview)).status_code, 200)
        disk = (self.root / "community.sqlite3").read_bytes()
        for secret in ("learner@example.com", "+1 (415) 555-0123", "@realperson", "token=private", "sk-syntheticSecret123", "privateBearerValue", "privateCookieValue", "synthetic-private-source"):
            self.assertNotIn(secret, json.dumps(preview))
            self.assertNotIn(secret, cached)
            self.assertNotIn(secret.encode(), disk)
        self.assertTrue(all(set(item) == {"item_id", "kind", "text", "timestamp_seconds", "source_uri"} for item in preview["items"]))
        repeated = self.preview(body)
        self.assertEqual(repeated["items"], [])
        self.assertEqual(repeated["deduplicated_count"], 6)

    def test_disabled_missing_expired_and_replayed_preview(self):
        preview = self.preview()
        saved = self.client.post(self.endpoint + "/save", json=self.save_body(preview))
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(preview)).status_code, 409)
        preview = self.preview()
        with patch.object(capture.time, "monotonic", return_value=capture.time.monotonic() + 301):
            self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(preview, ["0" * 32])).status_code, 409)
        preview = self.preview()
        community.set_community_enabled(False)
        before = self.snapshot()
        self.assertEqual(self.client.post(self.endpoint + "/preview", json=self.body).status_code, 409)
        self.assertEqual(self.snapshot(), before)
        community.set_community_enabled(True)
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(preview, ["0" * 32])).status_code, 409)
        self.assertEqual(self.client.post("/api/tasks/missing/community-context/preview", json=self.body).status_code, 404)

    def test_save_only_accepts_selected_immutable_preview_items(self):
        for update in ({"selected_item_ids": []}, {"selected_item_ids": [123]}, {"text": "replacement"}, {"items": self.body["items"]}):
            preview = self.preview()
            self.assertEqual(self.client.post(self.endpoint + "/save", json={**self.save_body(preview), **update}).status_code, 422)
        preview = self.preview()
        duplicate = [preview["items"][0]["item_id"]] * 2
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(preview, duplicate)).status_code, 422)
        preview = self.preview()
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(preview, ["0" * 32])).status_code, 422)
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(preview)).status_code, 409)
        preview = self.preview()
        tampered = {**self.save_body(preview), "fingerprint": "0" * 64}
        self.assertEqual(self.client.post(self.endpoint + "/save", json=tampered).status_code, 409)
        self.assertEqual(community.list_community_context("task1")["items"], [])

    def test_task_deleted_source_changed_and_replaced_task_invalidate_save(self):
        preview = self.preview()
        (self.tasks / "task1" / "task.json").unlink()
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(preview)).status_code, 404)
        self.write_task()
        preview = self.preview()
        self.task.page_url = URL.replace("p=2", "p=3")
        self.write_task()
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(preview)).status_code, 409)
        self.task.page_url = URL
        self.write_task()
        preview = self.preview()
        self.task.created_at = "2026-10-16T13:00:00Z"
        self.write_task()
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(preview)).status_code, 409)
        self.assertEqual(community.list_community_context("task1")["items"], [])

    def test_data_directory_task_and_preview_supersession_scopes(self):
        first = self.preview()
        second = self.preview()
        self.assertNotEqual(first["preview_id"], second["preview_id"])
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(first)).status_code, 409)
        self.assertEqual(self.client.post("/api/tasks/task2/community-context/save", json=self.save_body(second)).status_code, 409)
        with patch("app.storage.TASK_DIR", self.root / "other-tasks"):
            self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(second)).status_code, 409)
        with patch("app.community.DATA_DIR", self.root / "other-data"):
            self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(second)).status_code, 409)
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(second)).status_code, 200)

    def test_cache_bounded_clear_invalidation_and_single_use_concurrency(self):
        preview = self.preview()
        with patch.object(capture, "MAX_PENDING_PREVIEWS", 0):
            self.assertEqual(self.client.post(self.endpoint + "/preview", json=self.body).status_code, 429)
        preview = self.preview()
        community.clear_community_context("task1")
        self.assertEqual(self.client.post(self.endpoint + "/save", json=self.save_body(preview)).status_code, 409)
        preview = self.preview()
        request = capture.CommunitySaveRequest.model_validate(self.save_body(preview))
        def save_once(_):
            try:
                return capture.save_visible_community("task1", request)["stored_count"]
            except ValueError as exc:
                return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save_once, range(2)))
        self.assertEqual(results.count(2), 1)
        self.assertEqual(results.count("community_preview_unavailable"), 1)
        self.assertEqual(len(community.list_community_context("task1")["items"]), 2)

    def test_initial_disabled_preview_and_settings_do_not_create_store(self):
        (self.root / "community.sqlite3").unlink()
        before = self.snapshot()
        self.assertFalse(community.community_settings()["enabled"])
        self.assertEqual(self.client.post(self.endpoint + "/preview", json=self.body).status_code, 409)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
