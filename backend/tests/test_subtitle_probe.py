import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks
from pydantic import ValidationError
from app import main, storage
from app.models import CurrentPageTaskRequest, ResourceCandidate, TaskRecord
from app.subtitle_probe import SubtitleProbe
from app.media_kinds import classify_resource, effective_resource_kind, _is_scannable_play_endpoint
from app.media_source_context import fallback_page_contexts, _is_scannable_play_endpoint as source_scannable
from app.media_json_discovery import extract_media_resources_from_json_text
from app.media_discovery import extract_media_resources_from_text


class SubtitleProbeTests(unittest.TestCase):
    def test_diagnostics_only_keep_bounded_safe_values(self):
        value = SubtitleProbe.model_validate({"status": "ready", "language": "zh-CN", "cue_count": 100000,
            "elapsed_ms": -1, "cache_hit": True, "url": "https://example.com/?token=dummy",
            "cookies": "dummy", "text": "private-looking synthetic cue"}).model_dump()
        self.assertEqual(value, {"status": "ready", "language": "zh-CN", "cue_count": 10000, "elapsed_ms": 0, "cache_hit": True})
        bad = SubtitleProbe.model_validate({"status": ["secret"], "language": "https://example.com/", "elapsed_ms": float("inf"), "cache_hit": "yes"})
        self.assertEqual(bad.status, "unknown")
        self.assertEqual(bad.language, "")
        self.assertEqual(bad.elapsed_ms, 0)
        self.assertFalse(bad.cache_hit)

    def test_malformed_and_extreme_metadata_cannot_break_handoff_validation(self):
        for number, expected in [(10 ** 400, 10000), (-10 ** 400, 0), (1.9, 1),
                                 (True, 0), ("50", 0), (None, 0), ({}, 0),
                                 (float("nan"), 0), (float("-inf"), 0)]:
            with self.subTest(number=number):
                request = CurrentPageTaskRequest(page_url="https://example.test/video", subtitle_probe={"cue_count": number})
                self.assertEqual(request.subtitle_probe.cue_count, expected)
        probe = SubtitleProbe.model_validate({"elapsed_ms": 10 ** 400, "cache_hit": 1})
        self.assertEqual(probe.elapsed_ms, 3600000)
        self.assertFalse(probe.cache_hit)
        for value in [[], "private-looking synthetic cue", 1]:
            self.assertEqual(SubtitleProbe.model_validate(value), SubtitleProbe())

    def test_extension_version_rejects_arbitrary_diagnostic_content(self):
        for value in ["0.2.14\nprivate", "https://example.test/", "1" * 33]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                CurrentPageTaskRequest(page_url="https://example.test/video", extension_version=value)

    def test_existing_tasks_and_requests_need_no_migration(self):
        task = TaskRecord(id="synthetic-old", title="Existing", source_type="local", created_at="t0", updated_at="t0")
        restored = TaskRecord.model_validate(task.model_dump())
        self.assertIsNone(restored.subtitle_probe)
        self.assertEqual(restored.extension_version, "")
        self.assertIsNone(CurrentPageTaskRequest(page_url="https://example.com/video").subtitle_probe)

    def test_deferred_handoff_retains_metadata_on_disk_after_memory_is_lost(self):
        request = CurrentPageTaskRequest(page_url="https://example.com/video", title="Synthetic probe",
            subtitle_probe={"status": "not_found", "cue_count": 0, "elapsed_ms": 80, "url": "dummy-private-url"}, extension_version="0.2.14")
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "TASK_DIR", Path(directory)), \
             patch.object(main, "resolve_model_options", side_effect=lambda value: value), \
             patch.object(main, "schedule_processing") as schedule:
            result = main.create_from_current_page(request, BackgroundTasks(), defer=True)
            task_id = result["task_id"]
            try:
                saved = json.loads((storage.task_dir(task_id) / "deferred_preflight.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["subtitle_probe"]["status"], "not_found")
                self.assertNotIn("dummy-private-url", json.dumps(saved))
                main._deferred_handoffs.pop(task_id, None)
                task = storage.get_task(task_id)
                self.assertEqual(task.subtitle_probe.elapsed_ms, 80)
                evidence = main.direct_extraction_evidence(task)
                self.assertEqual(evidence["browser_context"]["subtitle_probe"]["status"], "not_found")
                self.assertEqual(evidence["browser_context"]["extension_version"], "0.2.14")
                self.assertIn("记录的扩展版本：0.2.14", main.render_diagnostics_markdown(task))
                self.assertIn("任务运行版本：未知", main.render_diagnostics_markdown(task))
                schedule.assert_not_called()
            finally:
                main._deferred_handoffs.pop(task_id, None)

    def test_repeated_deferred_handoff_refreshes_probe_until_task_has_started(self):
        request = CurrentPageTaskRequest(
            page_url="https://example.test/video", handoff_id="probe-handoff-001",
            subtitle_probe={"status": "not_found"}, extension_version="0.2.13",
        )
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "TASK_DIR", Path(directory)), \
             patch.object(main, "resolve_model_options", side_effect=lambda value: value), \
             patch.object(main, "schedule_processing") as schedule:
            task_id = main.create_from_current_page(request, BackgroundTasks(), defer=True)["task_id"]
            try:
                request = CurrentPageTaskRequest.model_validate({
                    **request.model_dump(), "subtitle_probe": {"status": "ready", "cue_count": 3, "cache_hit": True},
                    "extension_version": "0.2.14",
                })
                result = main.create_from_current_page(request, BackgroundTasks(), defer=True)
                self.assertTrue(result["deduplicated"])
                self.assertEqual(result["task_id"], task_id)
                task = storage.get_task(task_id)
                self.assertEqual(task.subtitle_probe, request.subtitle_probe)
                self.assertEqual(task.extension_version, "0.2.14")
                saved = json.loads((storage.task_dir(task_id) / "deferred_preflight.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["subtitle_probe"], request.subtitle_probe.model_dump())
                storage.update_task(task_id, awaiting_confirmation=False)
                stale_request = request.model_copy(update={"subtitle_probe": None, "extension_version": ""})
                main.create_from_current_page(stale_request, BackgroundTasks(), defer=True)
                self.assertEqual(storage.get_task(task_id).subtitle_probe, request.subtitle_probe)
                schedule.assert_not_called()
            finally:
                main._deferred_handoffs.pop(task_id, None)
                main._handoff_task_ids.pop(request.handoff_id, None)

    def test_immediate_task_keeps_probe_and_passes_it_to_processing(self):
        request = CurrentPageTaskRequest(
            page_url="https://example.test/video", mode="download_only",
            subtitle_probe={"status": "auth_required", "elapsed_ms": 45}, extension_version="0.2.14",
        )
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "TASK_DIR", Path(directory)), \
             patch.object(main, "resolve_model_options", side_effect=lambda value: value), \
             patch.object(main, "schedule_processing") as schedule:
            result = main.create_from_current_page(request, BackgroundTasks())
            self.assertEqual(storage.get_task(result["task_id"]).subtitle_probe, request.subtitle_probe)
            self.assertEqual(schedule.call_args.args[-1].subtitle_probe, request.subtitle_probe)

    def test_telemetry_and_hostname_only_hints_are_not_playable(self):
        page = "https://example.com/watch"
        for url in ["https://api.bilibili.com/x/click-interface/web/heartbeat", "https://example.com/api/video/heartbeat?quality=80",
                    "https://example.com/api/telemetry", "https://api.example.com/session"]:
            candidate = ResourceCandidate(url=url, request_type="fetch", method="POST", request_body={"content": "dummy"})
            self.assertEqual(effective_resource_kind(candidate), "unknown", url)
            self.assertFalse(_is_scannable_play_endpoint(candidate), url)
            self.assertFalse(source_scannable(candidate), url)
            self.assertNotIn(url, [item[0] for item in fallback_page_contexts(page, [candidate])])

    def test_telemetry_cannot_be_promoted_by_media_mime_query_or_discovery_context(self):
        urls = ["https://example.test/api/video/heartbeat?source=lesson.m3u8",
                "https://example.test/api/beacon?source=lesson.mp4",
                "https://example.test/api/%74elemetry?quality=80",
                "https://api.bilibili.com/x/click-interface/click/web/h5"]
        for url in urls:
            with self.subTest(url=url):
                candidate = ResourceCandidate(url=url, kind="video", mime="video/mp4", source="pagehook")
                self.assertEqual(classify_resource(url, "video/mp4"), "unknown")
                self.assertEqual(effective_resource_kind(candidate), "unknown")
                self.assertFalse(source_scannable(candidate))
                self.assertEqual(extract_media_resources_from_json_text(json.dumps({"video_url": url}), "https://example.test/watch"), [])
                self.assertEqual(extract_media_resources_from_text(f'<meta property="og:video" content="{url}">', "https://example.test/watch"), [])

    def test_telemetry_declared_video_is_rejected_but_resolved_media_is_retained(self):
        heartbeat = ResourceCandidate(url="https://example.com/api/video/heartbeat", kind="video", source="pagehook")
        self.assertEqual(effective_resource_kind(heartbeat), "unknown")
        heartbeat.resolved_url = "https://cdn.example.com/lesson.mp4"
        self.assertEqual(effective_resource_kind(heartbeat), "video")
        self.assertEqual(effective_resource_kind(ResourceCandidate(url="https://cdn.example.com/telemetry.mp4")), "video")
        self.assertEqual(effective_resource_kind(ResourceCandidate(url="https://cdn.example.com/analytics/lesson.mp4")), "video")
        self.assertEqual(effective_resource_kind(ResourceCandidate(url="https://cdn.example.com/beacon/master.m3u8")), "hls")

    def test_play_api_and_real_manifest_remain_supported(self):
        for url, kind in [("https://example.com/api/play?quality=80", "video"),
                          ("https://api.bilibili.com/x/player/playurl?bvid=SYNTHETIC", "video"),
                          ("https://cdn.example.com/master.m3u8", "hls")]:
            candidate = ResourceCandidate(url=url, request_type="fetch")
            self.assertEqual(effective_resource_kind(candidate), kind)
