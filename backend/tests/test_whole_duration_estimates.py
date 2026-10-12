"""Whole-attempt contract from synthetic clocks, tasks and provider mocks only."""
from contextlib import ExitStack
import copy
import gc
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import weakref
from unittest.mock import patch

from app import duration_estimates as legacy
from app import whole_duration_estimates as whole
from app.models import ActiveVideoInfo, BrowserSubtitleCue, CurrentPageTaskRequest, MediaIntegrity, TaskOptions, TranscriptResult, TranscriptSegment
from app.pipeline_progress import finish_pipeline_attempt, record_stage_duration, start_pipeline_attempt
from app.pipeline_timing import queued_callback
from app.storage import create_task, get_task, read_json, update_task, write_json


class WholeDurationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())) / "tasks"
        for module in ("storage", "observability"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root))
        self.clock, self.wall = 100.0, 1791633600.0
        fake = SimpleNamespace(monotonic=lambda: self.clock, time=lambda: self.wall)
        for module in ("whole_duration_estimates", "duration_estimates", "pipeline_progress", "processor", "subtitle_notes"):
            self.stack.enter_context(patch(f"app.{module}.time", fake))
        self.stack.enter_context(patch("app.pipeline_timing.monotonic", side_effect=lambda: self.clock))
        self.stack.enter_context(patch.object(whole.config, "DEFAULT_WHISPER_DEVICE", "cpu"))
        self.stack.enter_context(patch.object(whole.config, "DEFAULT_WHISPER_COMPUTE_TYPE", "int8"))
        for state in (whole._active, whole._history_cache, whole._successful_tasks, legacy._active, legacy._history_cache):
            state.clear()
            self.addCleanup(state.clear)
        self.options = TaskOptions(content_mode="text", llm_base_url="https://synthetic.invalid/v1", llm_model="synthetic-model", llm_api_key="synthetic-secret")
        self.transcript = TranscriptResult(source="browser-subtitle", full_text="Synthetic evidence only.",
            segments=[TranscriptSegment(start=0, end=300, text="Synthetic evidence only.")])

    def tick(self, seconds):
        self.clock += seconds
        self.wall += seconds

    def running(self, *, queued=False, recovery=False, entry_route="subtitle_only", route="transcript_to_note",
                options=None, duration=300, source=None, transcript_reused=False, normalization_reused=False,
                begin=True, retry=False, prefix=None):
        options = options or self.options
        task = create_task("local", "Synthetic private title", page_url="https://source.invalid/private", options=options)
        if retry:
            start_pipeline_attempt(task.id)
        def start():
            self.tick(3)  # Callback prelude is included only with a proven enqueue.
            attempt = start_pipeline_attempt(task.id, entry_route=entry_route, options=options)
            update_task(task.id, status="running", phase="transcribing")
            self.tick(20)
            for name, status in (prefix or {"transcript": "completed"}).items():
                record_stage_duration(task.id, name, self.clock - 20, status, expected_attempt_id=attempt)
            if begin:
                transcript = self.transcript.model_copy(update={"source": source}) if source else self.transcript
                whole.bind_whole_measurement(task.id, attempt, options, transcript, duration, route=route,
                    transcript_reused=transcript_reused, normalization_reused=normalization_reused)
                legacy.begin_remaining_measurement(task.id, attempt, options, transcript, duration, route=route)
            return attempt
        if queued:
            callback = queued_callback(task.id, start, recovery=recovery)
            self.tick(10)
            attempt = callback()
        else:
            attempt = start()
        return get_task(task.id), attempt

    def complete(self, task, attempt, seconds=80, **changes):
        self.tick(seconds)
        # Deliberately overlapping stages: elapsed time must never be a sum.
        for stage in ("summary", "verify"):
            record_stage_duration(task.id, stage, self.clock - seconds, expected_attempt_id=attempt)
        fields = dict(status="success", phase="completed", summary_source="text-llm", summary_warning="")
        fields.update(changes)
        update_task(task.id, **fields)
        finish_pipeline_attempt(task.id, expected_attempt_id=attempt)

    def histories(self, count=5, **kwargs):
        result = []
        for index in range(count):
            task, attempt = self.running(**kwargs)
            self.complete(task, attempt, 80 + index * 10)
            result.append(task)
        return result

    def projection(self, task):
        return whole.whole_task_duration_estimate(get_task(task.id))

    def unknown(self, task, reason=None):
        result = self.projection(task)
        self.assertEqual(result["status"], "unknown", result)
        self.assertIsNone(result["duration_seconds_range"])
        self.assertIsNone(result["remaining_seconds_range"])
        if reason:
            self.assertEqual(result["reason"], reason)
        return result

    def test_whole_range_is_measured_from_attempt_not_transcript_or_overlapping_stages(self):
        tasks = self.histories()
        task, _ = self.running()
        result = self.projection(task)
        self.assertEqual(result["duration_seconds_range"], [75, 175])
        self.assertEqual(result["remaining_seconds_range"], [55, 155])
        self.assertEqual(result["elapsed_seconds"], 20)
        self.assertEqual(result["boundary"], "attempt_start")
        self.assertEqual(result["scope"], "current_processing_attempt")
        self.assertEqual(result["cohort"], "current_backend_process")
        self.assertEqual(read_json(tasks[0].id, whole.FILENAME, {})["attempts"][-1]["duration_seconds"], 100)
        self.assertEqual(legacy.duration_estimate(get_task(task.id))["duration_seconds_range"], [60, 150])
        self.tick(155)
        self.assertEqual(self.projection(task)["status"], "overrun")
        self.assertIsNone(self.projection(task)["remaining_seconds_range"])

    def test_current_enqueue_includes_wait_and_prelude_without_other_attempt_time(self):
        tasks = self.histories(queued=True)
        task, _ = self.running(queued=True)
        result = self.projection(task)
        self.assertEqual(result["boundary"], "accepted_enqueue")
        self.assertEqual(result["elapsed_seconds"], 33)
        self.assertEqual(result["duration_seconds_range"], [84, 192])
        self.assertEqual(read_json(tasks[0].id, whole.FILENAME, {})["attempts"][-1]["duration_seconds"], 113)
        direct, _ = self.running()
        self.assertEqual(self.unknown(direct)["sample_count"], 0)
        recovered, _ = self.running(queued=True, recovery=True)
        self.assertEqual(self.unknown(recovered)["sample_count"], 0)

    def test_distinct_routes_retries_prefixes_cache_and_source_cannot_mix(self):
        self.histories()
        cases = ({"entry_route": "saved_transcript"}, {"entry_route": "local_media", "route": "media_to_note"},
                 {"retry": True}, {"source": "faster-whisper"}, {"duration": 900},
                 {"prefix": {"transcript": "skipped"}}, {"transcript_reused": True}, {"normalization_reused": True})
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                task, _ = self.running(**kwargs)
                self.assertEqual(self.unknown(task)["sample_count"], 0)

    def test_minimum_five_other_tasks_and_same_process_cohort(self):
        self.histories(4)
        task, attempt = self.running()
        self.assertEqual(self.unknown(task)["sample_count"], 4)
        self.complete(task, attempt)
        target, _ = self.running()
        self.assertEqual(self.projection(target)["sample_count"], 5)
        with patch.object(whole, "PROCESS_COHORT", "new-process"):
            fresh, _ = self.running()
            self.assertEqual(self.unknown(fresh)["sample_count"], 0)
            self.unknown(target, "context_changed")

    def test_restart_or_eviction_and_duplicate_late_callbacks_cannot_rebuild_clock(self):
        self.histories()
        task, attempt = self.running()
        self.tick(10)
        whole.bind_whole_measurement(task.id, attempt, self.options, self.transcript, 300, route="transcript_to_note")
        self.assertEqual(self.projection(task)["elapsed_seconds"], 30)
        original = (self.root / task.id / whole.FILENAME).read_bytes()
        whole._active.clear()
        whole.begin_whole_measurement(task.id, attempt, started_at=self.clock, queue_interval=None, entry_route="subtitle_only", retry=False)
        whole.bind_whole_measurement(task.id, attempt, self.options, self.transcript, 300, route="transcript_to_note")
        self.unknown(task, "live_clock_unavailable")
        self.assertEqual((self.root / task.id / whole.FILENAME).read_bytes(), original)
        newer = start_pipeline_attempt(task.id, entry_route="subtitle_only")
        finish_pipeline_attempt(task.id, expected_attempt_id=attempt)
        self.unknown(task, "context_unavailable")
        self.assertNotEqual(newer, attempt)

    def test_duplicate_dispatched_callback_does_not_reuse_enqueue(self):
        task = create_task("local", "Synthetic", options=self.options)
        callback = queued_callback(task.id, lambda: start_pipeline_attempt(task.id, entry_route="subtitle_only"))
        self.tick(10)
        first = callback()
        self.tick(90)
        second = callback()
        entries = read_json(task.id, whole.FILENAME, {})["attempts"]
        self.assertEqual([entry["boundary"] for entry in entries], ["accepted_enqueue", "attempt_start"])
        self.assertNotEqual(first, second)

    def test_context_unknown_before_transcript_and_old_evidence_is_not_backfilled(self):
        tasks = self.histories()
        for task in tasks:
            (self.root / task.id / whole.FILENAME).unlink()
        whole._history_cache.clear()
        task, attempt = self.running(begin=False)
        self.unknown(task, "context_unavailable")
        whole.bind_whole_measurement(task.id, attempt, self.options, self.transcript, 300, route="transcript_to_note")
        self.assertEqual(self.unknown(task)["sample_count"], 0)

    def test_mutations_before_bind_and_after_bind_or_completion_stay_unknown(self):
        self.histories()
        for before_bind in (True, False):
            for change in ("options", "device", "input", "effective_options"):
                with self.subTest(before_bind=before_bind, change=change):
                    options = self.options.model_copy(deep=True)
                    task, attempt = self.running(options=options, begin=not before_bind)
                    with ExitStack() as stack:
                        if change == "options":
                            update_task(task.id, options=self.options.model_copy(update={"llm_model": "changed"}))
                        elif change == "device":
                            stack.enter_context(patch.object(whole.config, "DEFAULT_WHISPER_DEVICE", "cuda"))
                        elif change == "input":
                            update_task(task.id, learning_range={"start": 10, "end": 100})
                        else:
                            options.llm_model = "changed"
                        if before_bind:
                            whole.bind_whole_measurement(task.id, attempt, options, self.transcript, 300, route="transcript_to_note")
                        self.unknown(task)
                        self.complete(task, attempt)
                        entry = read_json(task.id, whole.FILENAME, {})["attempts"][-1]
                        self.assertEqual(entry["status"], "unusable")

    def test_optional_measurement_does_not_retain_key_bearing_options(self):
        self.histories()
        options = self.options.model_copy(deep=True)
        reference = weakref.ref(options)
        task, attempt = self.running(options=options)
        self.assertEqual(self.projection(task)["status"], "estimated")
        del options
        gc.collect()
        self.assertIsNone(reference(), "Optional telemetry must not extend the provider options lifetime")
        self.unknown(task, "context_changed")
        self.complete(task, attempt)
        self.assertEqual(read_json(task.id, whole.FILENAME, {})["attempts"][-1]["status"], "unusable")

    def test_auto_device_unresolved_options_duration_and_source_stay_unknown(self):
        for kwargs in ({"duration": 0}, {"duration": float("nan")}, {"source": "unknown"},
                       {"options": self.options.model_copy(update={"llm_model": None})},
                       {"options": self.options.model_copy(update={"llm_base_url": "https://user:secret@fixture.invalid"})}):
            task, _ = self.running(**kwargs)
            self.unknown(task, "context_unavailable")
        with patch.object(whole.config, "DEFAULT_WHISPER_DEVICE", "auto"):
            task, _ = self.running()
            self.unknown(task, "context_unavailable")

    def test_unknown_visual_capability_and_visual_cache_are_excluded(self):
        options = self.options.model_copy(update={"visual_understanding": True, "content_mode": "visual"})
        with patch("app.model_capabilities.model_description", return_value={"vision": None}):
            task, _ = self.running(options=options)
            self.unknown(task, "context_unavailable")
        with patch("app.model_capabilities.model_description", return_value={"vision": True, "capability_source": "image_test"}):
            task, attempt = self.running(options=options, begin=False)
            (self.root / task.id / "vision_cache").mkdir()
            whole.bind_whole_measurement(task.id, attempt, options, self.transcript, 300, route="media_to_note")
            self.unknown(task, "context_unavailable")
            task, attempt = self.running(options=options, begin=False)
            with patch("app.model_capabilities.model_description", return_value={"vision": True, "capability_source": "official_catalog"}):
                whole.bind_whole_measurement(task.id, attempt, options, self.transcript, 300, route="media_to_note")
            self.unknown(task, "context_unavailable")

    def test_fail_cancel_fallback_warning_incomplete_and_missing_stage_are_not_samples(self):
        for changes in ({"status": "failed"}, {"status": "cancelled"}, {"cancel_requested": True},
                        {"summary_source": "offline-fixture"}, {"summary_warning": "synthetic warning"},
                        {"summary_diagnostics": {"llm_events": [{"code": "partial_recovery"}]}}):
            task, attempt = self.running()
            self.complete(task, attempt, **changes)
            self.assertEqual(read_json(task.id, whole.FILENAME, {})["attempts"][-1]["status"], "unusable")
        task, attempt = self.running()
        update_task(task.id, status="success", summary_source="text-llm")
        finish_pipeline_attempt(task.id, expected_attempt_id=attempt)
        self.assertEqual(read_json(task.id, whole.FILENAME, {})["attempts"][-1]["status"], "unusable")
        target, _ = self.running()
        self.assertEqual(self.unknown(target)["sample_count"], 0)

    def test_bounded_malformed_future_unsupported_history_readonly_and_private(self):
        histories = self.histories()
        target, _ = self.running()
        originals = {task.id: read_json(task.id, whole.FILENAME, {}) for task in histories}
        for change in ({"finished_at_unix_ms": (self.wall + 1) * 1000}, {"duration_seconds": -1},
                       {"duration_seconds": float("nan")}, {"duration_seconds": True},
                       {"finished_at_unix_ms": (self.wall - legacy.MAX_AGE_SECONDS - 1) * 1000}):
            for task in histories:
                value = copy.deepcopy(originals[task.id])
                value["attempts"][-1].update(change)
                write_json(task.id, whole.FILENAME, value)
            whole._history_cache.clear()
            self.assertEqual(self.unknown(target)["sample_count"], 0)
        for content in ("broken", "[]", '{"schema_version":true,"attempts":[]}', '{"schema_version":99,"attempts":[]}', "x" * (legacy.MAX_BYTES + 1)):
            path = self.root / target.id / whole.FILENAME
            path.write_text(content)
            before = path.read_bytes()
            self.unknown(target, "evidence_unavailable")
            self.assertEqual(path.read_bytes(), before)
        value = json.dumps(originals)
        for secret in ("synthetic-secret", "synthetic-model", "synthetic.invalid", "private", "Synthetic evidence"):
            self.assertNotIn(secret, value)

    def test_projection_leaves_metrics_legacy_sidecar_and_task_bytes_unchanged(self):
        self.histories()
        task, _ = self.running()
        paths = list((self.root / task.id).glob("*.json"))
        before = {path: path.read_bytes() for path in paths}
        result = self.projection(task)
        self.assertEqual(result["status"], "estimated")
        self.assertEqual({path: path.read_bytes() for path in paths}, before)
        raw = json.dumps(result)
        for private in ("process_cohort", "options_identity", "subtitle_source", "synthetic-model", str(self.root)):
            self.assertNotIn(private, raw)
        self.clock -= 21
        self.unknown(task, "invalid_elapsed_time")

    def test_same_task_attempts_count_once_and_never_train_themselves(self):
        task, attempt = self.running()
        self.complete(task, attempt)
        for _ in range(6):
            attempt = start_pipeline_attempt(task.id, entry_route="subtitle_only", options=self.options)
            update_task(task.id, status="running")
            record_stage_duration(task.id, "transcript", self.clock, expected_attempt_id=attempt)
            whole.bind_whole_measurement(task.id, attempt, self.options, self.transcript, 300, route="transcript_to_note")
            self.assertEqual(self.unknown(task)["sample_count"], 0)
            self.complete(task, attempt)
        target, _ = self.running(retry=True)
        self.assertEqual(self.unknown(target)["sample_count"], 1)

    def test_live_sidecar_or_prefix_mutations_cannot_keep_a_reference(self):
        self.histories()
        for changed in ("sidecar", "prefix"):
            task, _ = self.running()
            if changed == "sidecar":
                evidence = read_json(task.id, whole.FILENAME, {})
                evidence["attempts"][-1]["started_at_unix_ms"] = (self.wall + 100) * 1000
                write_json(task.id, whole.FILENAME, evidence)
            else:
                metrics = read_json(task.id, "pipeline_metrics.json", {})
                metrics["attempts"][-1]["stages"]["transcript"]["status"] = "skipped"
                write_json(task.id, "pipeline_metrics.json", metrics)
            self.unknown(task, "context_changed")

    def test_old_large_stores_do_not_starve_current_process_samples(self):
        for index in range(4096):
            (self.root / f"old-{index}").mkdir(parents=True)
        histories = self.histories()
        target, _ = self.running()
        self.assertEqual(self.projection(target)["sample_count"], 5)
        for task in histories:
            (self.root / task.id / whole.FILENAME).unlink()
        whole._history_cache.clear()
        self.assertEqual(self.unknown(target)["sample_count"], 0)
        with patch.object(whole, "MAX_TASKS", 3):
            self.histories(5)
            self.assertEqual(len(whole._successful_tasks), 3)

    def test_selected_ranges_cannot_use_or_train_whole_history(self):
        self.histories(queued=True)
        for _ in range(5):
            task = create_task("local", "Synthetic range", options=self.options)
            update_task(task.id, learning_range={"start": 20, "end": 320})
            def start():
                attempt = start_pipeline_attempt(task.id, entry_route="local_media", options=self.options)
                update_task(task.id, status="running")
                record_stage_duration(task.id, "transcript", self.clock, expected_attempt_id=attempt)
                whole.bind_whole_measurement(task.id, attempt, self.options, self.transcript, 300, route="media_to_note")
                return attempt
            callback = queued_callback(task.id, start)
            self.tick(10)
            attempt = callback()
            self.unknown(task, "context_unavailable")
            self.complete(task, attempt)
            self.assertFalse((self.root / task.id / whole.FILENAME).exists())
        target, _ = self.running(queued=True, entry_route="local_media", route="media_to_note")
        self.assertEqual(self.unknown(target)["sample_count"], 0)

    def test_linked_sidecars_are_preserved_at_start_bind_and_projection(self):
        for module in (whole, legacy):
            for dangling in (True, False):
                with self.subTest(module=module.__name__, dangling=dangling):
                    task = create_task("local", "Synthetic", options=self.options)
                    outside = self.root.parent / ("missing" if dangling else "existing")
                    if not dangling:
                        outside.write_bytes(b"synthetic target preserved")
                    path = self.root / task.id / module.FILENAME
                    path.symlink_to(outside)
                    attempt = start_pipeline_attempt(task.id, entry_route="subtitle_only")
                    update_task(task.id, status="running")
                    if module is legacy:
                        module.begin_remaining_measurement(task.id, attempt, self.options, self.transcript, 300, route="transcript_to_note")
                    else:
                        module.bind_whole_measurement(task.id, attempt, self.options, self.transcript, 300, route="transcript_to_note")
                    self.assertTrue(path.is_symlink())
                    self.assertEqual(path.readlink(), outside)
                    if dangling:
                        self.assertFalse(outside.exists())
                    else:
                        self.assertEqual(outside.read_bytes(), b"synthetic target preserved")

    def test_optional_hook_faults_do_not_change_real_pipeline_or_provider_calls(self):
        from app.processor import process_saved_transcript_task
        task = create_task("local", "Synthetic", options=self.options)
        path = write_json(task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        update_task(task.id, transcript_path=str(path), media_integrity=MediaIntegrity(duration=300, status="ready"))
        with patch("app.processor.summarize_with_diagnostics", return_value=("# Synthetic\n\nSynthetic evidence only.", "text-llm", "", [])) as model, \
             patch.object(whole, "begin_whole_measurement", side_effect=OSError("synthetic fault")), \
             patch.object(whole, "bind_whole_measurement", side_effect=OSError("synthetic fault")), \
             patch.object(whole, "finish_whole_measurement", side_effect=OSError("synthetic fault")):
            process_saved_transcript_task(task.id, self.options)
        self.assertEqual(get_task(task.id).status, "success")
        model.assert_called_once()

    def test_real_media_pipeline_distinguishes_fresh_asr_from_reused_transcript(self):
        from app.models import EvidenceCoverage
        from app.processor import _process_video_file
        task = create_task("local", "Synthetic", options=self.options)
        source = self.root / task.id / "source.mp4"
        source.write_bytes(b"synthetic media never decoded")
        transcript = self.transcript.model_copy(update={"source": "faster-whisper"})
        def normalize(source, target):
            if source != target:
                self.tick(10)
                target.write_bytes(b"synthetic normalized media")
            return target
        def audio(source, target):
            self.tick(5)
            target.write_bytes(b"synthetic audio never decoded")
        def transcribe(*args):
            self.tick(40)
            return transcript
        def summarize(*args, **kwargs):
            self.tick(20)
            return "# Synthetic\n\nSynthetic evidence only.", "text-llm", "", []
        with patch("app.processor.probe_media_integrity", return_value=MediaIntegrity(status="ready", duration=300, sha256="synthetic-hash", has_audio=True, has_video=True)), \
             patch("app.processor.normalize_video", side_effect=normalize), \
             patch("app.processor.extract_embedded_subtitle", return_value=None), \
             patch("app.processor.extract_audio", side_effect=audio), \
             patch("app.processor.transcribe_with_task_progress", side_effect=transcribe) as asr, \
             patch("app.processor.calculate_evidence_coverage", return_value=EvidenceCoverage(status="ready", can_summarize=True)), \
             patch("app.processor.summarize_with_diagnostics", side_effect=summarize) as model:
            _process_video_file(task.id, source, "Synthetic", "", self.options)
            self.assertEqual(get_task(task.id).status, "success")
            first = read_json(task.id, whole.FILENAME, {})["attempts"][-1]
            self.assertEqual(first["status"], "completed", first)
            self.assertEqual(first["duration_seconds"], 75)
            self.assertFalse(first["context"]["transcript_reused"])
            _process_video_file(task.id, self.root / task.id / "media.mp4", "Synthetic", "", self.options)
            second = read_json(task.id, whole.FILENAME, {})["attempts"][-1]
            self.assertEqual(second["status"], "completed", second)
            self.assertEqual(second["duration_seconds"], 20)
            self.assertTrue(second["context"]["transcript_reused"])
            self.assertTrue(second["context"]["normalization_reused"])
            self.assertEqual(second["context"]["attempt_kind"], "retry")
        asr.assert_called_once()
        self.assertEqual(model.call_count, 2)

    def test_invalid_queue_chronology_and_absent_prefix_are_unknown(self):
        task = create_task("local", "Synthetic", options=self.options)
        attempt = start_pipeline_attempt(task.id)
        update_task(task.id, status="running")
        for interval in ((100, 90, "queued"), (90, 110, "queued"), (90, 99, "unknown")):
            whole.begin_whole_measurement(task.id, attempt, started_at=100, queue_interval=interval, entry_route="subtitle_only", retry=False)
            self.assertFalse((self.root / task.id / whole.FILENAME).exists())
        whole.begin_whole_measurement(task.id, attempt, started_at=100, queue_interval=None, entry_route="subtitle_only", retry=False)
        whole.bind_whole_measurement(task.id, attempt, self.options, self.transcript, 300, route="transcript_to_note")
        self.unknown(task, "context_unavailable")

    def test_capability_change_after_binding_invalidates_projection_and_success(self):
        options = self.options.model_copy(update={"content_mode": "visual", "visual_understanding": True})
        with patch("app.model_capabilities.model_description", return_value={"vision": True, "capability_source": "image_test"}):
            task, attempt = self.running(options=options, route="media_to_note", entry_route="local_media")
        with patch("app.model_capabilities.model_description", return_value={"vision": None, "capability_source": "unknown"}):
            self.unknown(task, "context_changed")
            self.complete(task, attempt, summary_source="vision-llm")
        self.assertEqual(read_json(task.id, whole.FILENAME, {})["attempts"][-1]["status"], "unusable")

    def test_real_subtitle_pipeline_and_http_projection_include_current_enqueue(self):
        from app import main, subtitle_notes
        from app.processor import process_subtitle_only_task
        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        self.addCleanup(client.close)
        self.stack.enter_context(patch.object(main, "TASK_DIR", self.root))
        observations = []
        normalize = subtitle_notes.normalize_note_markdown
        def summarize(*args, **kwargs):
            task = get_task(current[0])
            response = client.get(f"/api/tasks/{task.id}")
            self.assertEqual(response.status_code, 200)
            observations.append(response.json()["task"]["whole_task_duration_estimate"])
            self.tick(20)
            return "# Synthetic\n\nSynthetic evidence only.", "text-llm", "", []
        def checks(*args, **kwargs):
            self.tick(5)
            return normalize(*args, **kwargs)
        current = [None]
        with patch("app.processor.summarize_with_diagnostics", side_effect=summarize) as model, \
             patch("app.subtitle_notes.normalize_note_markdown", side_effect=checks):
            for _ in range(6):
                task = create_task("current_page", "Synthetic", options=self.options)
                current[0] = task.id
                request = CurrentPageTaskRequest(page_url="https://synthetic.invalid/video", title="Synthetic", mode="subtitle_only",
                    options=self.options, active_video=ActiveVideoInfo(duration=300),
                    browser_subtitles=[BrowserSubtitleCue(start=0, end=300, text="Synthetic evidence only.")])
                callback = queued_callback(task.id, lambda: process_subtitle_only_task(task.id, request))
                self.tick(10)
                callback()
                self.assertEqual(get_task(task.id).status, "success", get_task(task.id).error_detail)
                entry = read_json(task.id, whole.FILENAME, {})["attempts"][-1]
                self.assertEqual(entry["status"], "completed", entry)
                self.assertEqual(entry["duration_seconds"], 35)
        self.assertEqual(model.call_count, 6)
        self.assertEqual(observations[-1]["status"], "estimated")
        self.assertEqual(observations[-1]["duration_seconds_range"], [26, 44])
        self.assertEqual(observations[-1]["elapsed_seconds"], 10)
        self.assertEqual(observations[-1]["boundary"], "accepted_enqueue")


if __name__ == "__main__":
    unittest.main()
