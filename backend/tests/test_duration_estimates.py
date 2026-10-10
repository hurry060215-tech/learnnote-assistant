"""Synthetic local evidence and clocks only. Never call a model or read user data."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import duration_estimates as estimates
from app.models import TaskOptions, TranscriptResult, TranscriptSegment
from app.pipeline_progress import finish_pipeline_attempt, record_stage_duration, start_pipeline_attempt
from app.storage import create_task, get_task, read_json, update_task, write_json


class DurationEstimatesTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())) / "tasks"
        for module in ("storage", "observability"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root))
        self.clock, self.wall = 100.0, 1791633600.0
        clock = SimpleNamespace(monotonic=lambda: self.clock, time=lambda: self.wall)
        self.stack.enter_context(patch.object(estimates, "time", clock))
        self.stack.enter_context(patch("app.pipeline_progress.time", clock))
        self.stack.enter_context(patch.object(estimates.config, "DEFAULT_WHISPER_DEVICE", "cpu"))
        self.stack.enter_context(patch.object(estimates.config, "DEFAULT_WHISPER_COMPUTE_TYPE", "int8"))
        estimates._active.clear()
        estimates._history_cache.clear()
        self.addCleanup(estimates._active.clear)
        self.addCleanup(estimates._history_cache.clear)
        self.options = TaskOptions(content_mode="text", llm_base_url="https://fixture.invalid/v1", llm_model="synthetic-model", llm_api_key="synthetic-key")
        self.transcript = TranscriptResult(source="browser-subtitle", full_text="Synthetic evidence only.",
            segments=[TranscriptSegment(start=0, end=300, text="Synthetic evidence only.")])

    def tick(self, seconds):
        self.clock += seconds
        self.wall += seconds

    def running(self, *, options=None, duration=300, source=None, route="transcript_to_note", begin=True):
        options = options or self.options
        task = create_task("local", "Synthetic private title", page_url="https://source.invalid/private", options=options)
        attempt = start_pipeline_attempt(task.id)
        update_task(task.id, status="running", phase="summarizing")
        if begin:
            transcript = self.transcript.model_copy(update={"source": source}) if source else self.transcript
            estimates.begin_remaining_measurement(task.id, attempt, options, transcript, duration, route=route)
        return get_task(task.id), attempt

    def complete(self, task, attempt, seconds=100, *, status="completed", task_status="success", stage_status="completed"):
        self.tick(seconds)
        for stage in ("summary", "verify"):
            record_stage_duration(task.id, stage, self.clock - seconds, stage_status, expected_attempt_id=attempt)
        update_task(task.id, status=task_status, phase="completed" if task_status == "success" else task_status)
        finish_pipeline_attempt(task.id, status, expected_attempt_id=attempt)

    def histories(self, count=5, **kwargs):
        tasks = []
        for index in range(count):
            task, attempt = self.running(**kwargs)
            self.complete(task, attempt, 100 + index * 10)
            tasks.append(task)
        return tasks

    def projection(self, task):
        return estimates.duration_estimate(get_task(task.id))

    def assert_unknown(self, task, reason=None):
        value = self.projection(task)
        self.assertEqual(value["status"], "unknown", value)
        self.assertIsNone(value["duration_seconds_range"])
        self.assertIsNone(value["remaining_seconds_range"])
        if reason:
            self.assertEqual(value["reason"], reason)
        return value

    def test_five_distinct_successes_supply_padded_empirical_range(self):
        self.histories()
        task, _ = self.running()
        value = self.projection(task)
        self.assertEqual(value["status"], "estimated")
        self.assertEqual(value["scope"], "after_transcript_ready")
        self.assertEqual(value["duration_seconds_range"], [75, 175])
        self.assertEqual(value["remaining_seconds_range"], [75, 175])
        self.assertEqual(value["sample_count"], 5)
        self.assertEqual(value["uncertainty"], "empirical_not_probability")

    def test_remaining_uses_monotonic_elapsed_not_progress_or_wall_time(self):
        self.histories()
        task, _ = self.running()
        self.tick(80)
        update_task(task.id, progress=99)
        self.assertEqual(self.projection(task)["remaining_seconds_range"], [0, 95])
        self.wall += 3600
        update_task(task.id, progress=1)
        self.assertEqual(self.projection(task)["remaining_seconds_range"], [0, 95])

    def test_upper_bound_overrun_never_sticks_at_zero_or_extends_deadline(self):
        self.histories()
        task, _ = self.running()
        self.tick(175)
        value = self.projection(task)
        self.assertEqual(value["status"], "overrun")
        self.assertIsNone(value["remaining_seconds_range"])
        self.assertEqual(value["duration_seconds_range"], [75, 175])
        self.tick(1000)
        self.assertEqual(self.projection(task)["status"], "overrun")

    def test_four_samples_are_insufficient(self):
        self.histories(4)
        task, _ = self.running()
        value = self.assert_unknown(task, "insufficient_compatible_history")
        self.assertEqual(value["sample_count"], 4)

    def test_no_context_before_transcript_and_legacy_metrics_not_backfilled(self):
        task, _ = self.running(begin=False)
        self.assert_unknown(task, "context_unavailable")
        legacy = {"schema_version": 1, "stages": {"summary": {"duration_ms": 100000}}}
        write_json(task.id, "pipeline_metrics.json", legacy)
        self.assert_unknown(task, "attempt_unavailable")
        self.assertEqual(read_json(task.id, "pipeline_metrics.json", {}), legacy)
        self.assertFalse((self.root / task.id / estimates.FILENAME).exists())

    def test_post_restart_has_no_live_clock_and_cannot_restart_boundary(self):
        self.histories()
        task, attempt = self.running()
        estimates._active.clear()
        estimates.begin_remaining_measurement(task.id, attempt, self.options, self.transcript, 300, route="transcript_to_note")
        self.assert_unknown(task, "live_clock_unavailable")

    def test_duplicate_start_does_not_reset_elapsed_or_add_sample(self):
        self.histories()
        task, attempt = self.running()
        self.tick(30)
        estimates.begin_remaining_measurement(task.id, attempt, self.options, self.transcript, 300, route="transcript_to_note")
        self.assertEqual(self.projection(task)["elapsed_seconds"], 30)
        self.assertEqual(len(read_json(task.id, estimates.FILENAME, {})["attempts"]), 1)

    def test_route_and_source_and_length_mismatch_remain_unknown(self):
        self.histories()
        for kwargs in ({"route": "media_to_note"}, {"source": "embedded-subtitle"}, {"duration": 100}, {"duration": 1000}):
            with self.subTest(kwargs=kwargs):
                task, _ = self.running(**kwargs)
                self.assert_unknown(task, "insufficient_compatible_history")

    def test_nearby_media_lengths_use_observed_times_without_linear_scaling(self):
        self.histories(duration=250)
        task, _ = self.running(duration=300)
        self.assertEqual(self.projection(task)["duration_seconds_range"], [75, 175])

    def test_model_endpoint_options_and_declared_device_are_exact_matches(self):
        self.histories()
        for changes in ({"llm_model": "different-model"}, {"llm_base_url": "https://second.invalid/v1"},
                        {"low_resource_mode": True}, {"summary_depth": "deep"}, {"whisper_model": "tiny"},
                        {"vision_concurrency": 1}):
            with self.subTest(changes=changes):
                task, _ = self.running(options=self.options.model_copy(update=changes))
                self.assert_unknown(task, "insufficient_compatible_history")
        with patch.object(estimates.config, "DEFAULT_WHISPER_DEVICE", "cuda"):
            task, _ = self.running()
            self.assert_unknown(task, "insufficient_compatible_history")
        with patch.object(estimates.config, "DEFAULT_WHISPER_COMPUTE_TYPE", "float32"):
            task, _ = self.running()
            self.assert_unknown(task, "insufficient_compatible_history")

    def test_in_flight_option_or_device_change_invalidates_estimate(self):
        self.histories()
        task, _ = self.running()
        update_task(task.id, options=self.options.model_copy(update={"llm_model": "changed"}))
        self.assert_unknown(task, "context_changed")
        task, _ = self.running()
        with patch.object(estimates.config, "DEFAULT_WHISPER_DEVICE", "cuda"):
            self.assert_unknown(task, "context_changed")

    def test_changed_live_media_or_selected_range_is_unknown(self):
        self.histories()
        task, _ = self.running()
        update_task(task.id, media_integrity=task.media_integrity.model_copy(update={"duration": 500}))
        self.assert_unknown(task, "context_changed")
        task, _ = self.running()
        update_task(task.id, learning_range={"start": 20, "end": 50})
        self.assert_unknown(task, "context_changed")

    def test_keys_do_not_partition_or_appear_in_evidence(self):
        self.histories()
        task, _ = self.running(options=self.options.model_copy(update={"llm_api_key": "another-secret", "use_saved_connection": True}))
        self.assertEqual(self.projection(task)["status"], "estimated")
        content = (self.root / task.id / estimates.FILENAME).read_text()
        for text in ("synthetic-key", "another-secret", "fixture.invalid", "synthetic-model", "private", "Synthetic evidence"):
            self.assertNotIn(text, content)

    def test_unresolved_model_defaults_cannot_masquerade_as_the_actual_route(self):
        self.histories()
        for changes in ({"llm_base_url": None}, {"llm_model": None},
                        {"llm_base_url": None, "llm_model": None, "llm_api_key": None, "use_saved_connection": True}):
            with self.subTest(changes=changes):
                task, _ = self.running(options=self.options.model_copy(update=changes))
                self.assert_unknown(task, "context_unavailable")
                self.assertFalse((self.root / task.id / estimates.FILENAME).exists())

    def test_aggregate_does_not_reveal_history_identifiers_or_context(self):
        histories = self.histories()
        task, _ = self.running()
        projection = json.dumps(self.projection(task))
        for value in [*(item.id for item in histories), "Synthetic private title", str(self.root), "fixture.invalid", "synthetic-model", "options_identity", "subtitle_source", "device_mode"]:
            self.assertNotIn(value, projection)

    def test_failed_cancelled_incomplete_and_bad_stage_attempts_are_not_samples(self):
        for status, task_status, stage_status in (("failed", "failed", "failed"), ("cancelled", "cancelled", "cancelled"),
                                                ("completed", "failed", "completed"), ("completed", "success", "failed")):
            for _ in range(5):
                task, attempt = self.running()
                self.complete(task, attempt, status=status, task_status=task_status, stage_status=stage_status)
        for _ in range(5):
            self.running()
        task, _ = self.running()
        self.assertEqual(self.assert_unknown(task)["sample_count"], 0)

    def test_cancel_request_immediately_suppresses_active_range(self):
        self.histories()
        task, _ = self.running()
        update_task(task.id, cancel_requested=True)
        self.assert_unknown(task, "inactive_attempt")
        for status in ("cancelling", "cancelled", "failed", "success", "queued"):
            update_task(task.id, status=status, cancel_requested=False)
            self.assert_unknown(task, "inactive_attempt")

    def test_cancelled_success_is_not_recorded_as_eligible(self):
        task, attempt = self.running()
        update_task(task.id, cancel_requested=True)
        self.complete(task, attempt)
        evidence = read_json(task.id, estimates.FILENAME, {})["attempts"][-1]
        self.assertEqual(evidence["status"], "unusable")
        self.assertNotIn("duration_seconds", evidence)

    def test_new_attempt_and_late_old_finish_cannot_publish_old_estimate(self):
        self.histories()
        task, first = self.running()
        second = start_pipeline_attempt(task.id)
        self.assert_unknown(task, "context_unavailable")
        finish_pipeline_attempt(task.id, expected_attempt_id=first)
        self.assert_unknown(task, "context_unavailable")
        estimates.begin_remaining_measurement(task.id, second, self.options, self.transcript, 300, route="transcript_to_note")
        self.assertEqual(self.projection(task)["attempt_id"], second)
        estimates.finish_remaining_measurement(task.id, first, "completed")
        self.assertEqual(self.projection(task)["attempt_id"], second)

    def test_many_successes_in_one_task_count_only_once_and_target_is_excluded(self):
        task, attempt = self.running()
        for _ in range(7):
            self.complete(task, attempt)
            attempt = start_pipeline_attempt(task.id)
            update_task(task.id, status="running", phase="summarizing")
            estimates.begin_remaining_measurement(task.id, attempt, self.options, self.transcript, 300, route="transcript_to_note")
        self.assertEqual(self.assert_unknown(task)["sample_count"], 0)
        other, _ = self.running()
        self.assertEqual(self.assert_unknown(other)["sample_count"], 1)

    def test_stale_future_missing_and_invalid_sample_timings_stay_unknown(self):
        histories = self.histories()
        task, _ = self.running()
        originals = {item.id: read_json(item.id, estimates.FILENAME, {}) for item in histories}
        changes = [{"finished_at_unix_ms": (self.wall - estimates.MAX_AGE_SECONDS - 1) * 1000},
                   {"finished_at_unix_ms": (self.wall + 1) * 1000}, {"duration_seconds": None},
                   {"duration_seconds": -1}, {"duration_seconds": float("nan")}, {"duration_seconds": True},
                   {"duration_seconds": "100"}, {"duration_seconds": estimates.MAX_DURATION_SECONDS + 1},
                   {"started_at_unix_ms": (self.wall + 1) * 1000}]
        for change in changes:
            with self.subTest(change=change):
                for item in histories:
                    value = copy.deepcopy(originals[item.id])
                    value["attempts"][-1].update(change)
                    write_json(item.id, estimates.FILENAME, value)
                estimates._history_cache.clear()
                self.assertEqual(self.assert_unknown(task)["sample_count"], 0)

    def test_stale_history_expires_even_while_reader_cache_is_hot(self):
        self.histories()
        task, _ = self.running()
        self.assertEqual(self.projection(task)["status"], "estimated")
        self.wall += estimates.MAX_AGE_SECONDS + 1
        self.assert_unknown(task, "insufficient_compatible_history")

    def test_invalid_media_or_unresolved_route_never_records_context(self):
        for kwargs in ({"duration": 0}, {"duration": -1}, {"duration": float("nan")}, {"duration": "300"},
                       {"duration": True}, {"source": "unknown"}, {"source": "faster-whisper-error"}, {"route": "guessed-route"}):
            with self.subTest(kwargs=kwargs):
                task, _ = self.running(**kwargs)
                self.assert_unknown(task, "context_unavailable")
        with patch.object(estimates.config, "DEFAULT_WHISPER_DEVICE", "auto"):
            task, _ = self.running()
            self.assert_unknown(task, "context_unavailable")

    def test_unknown_or_credential_bearing_endpoint_never_records_context(self):
        for endpoint in ("file:///private", "https://user:secret@fixture.invalid/v1", "https://fixture.invalid/v1?key=secret"):
            task, _ = self.running(options=self.options.model_copy(update={"llm_base_url": endpoint}))
            self.assert_unknown(task, "context_unavailable")

    def test_current_evidence_read_fault_is_optional_unknown(self):
        self.histories()
        task, _ = self.running()
        path = self.root / task.id / estimates.FILENAME
        for content in ("bad-json", "[]", "{}", "x" * (estimates.MAX_BYTES + 1)):
            path.write_text(content)
            self.assert_unknown(task, "evidence_unavailable")

    def test_faulty_history_files_do_not_invent_samples_or_change_processing(self):
        self.histories(4)
        path = self.root / "synthetic-corrupt"
        path.mkdir()
        (path / estimates.FILENAME).write_text("broken")
        task, _ = self.running()
        self.assertEqual(self.assert_unknown(task)["sample_count"], 4)
        with patch.object(estimates, "_history", side_effect=OSError("synthetic fault")):
            self.assert_unknown(task, "evidence_unavailable")

    def test_start_and_finish_write_faults_never_fail_the_pipeline(self):
        task, attempt = self.running(begin=False)
        with patch.object(estimates.storage, "write_json", side_effect=OSError("synthetic fault")):
            estimates.begin_remaining_measurement(task.id, attempt, self.options, self.transcript, 300, route="transcript_to_note")
        self.assert_unknown(task)
        estimates.begin_remaining_measurement(task.id, attempt, self.options, self.transcript, 300, route="transcript_to_note")
        self.tick(100)
        with patch.object(estimates.storage, "write_json", side_effect=OSError("synthetic fault")):
            estimates.finish_remaining_measurement(task.id, attempt, "completed")
        self.assertEqual(get_task(task.id).status, "running")

    def test_clock_reversal_or_extreme_elapsed_is_unknown(self):
        self.histories()
        task, _ = self.running()
        self.clock -= 1
        self.assert_unknown(task, "invalid_elapsed_time")
        self.clock += estimates.MAX_DURATION_SECONDS + 2
        self.assert_unknown(task, "invalid_elapsed_time")

    def test_reader_caps_directory_count_and_sample_count(self):
        self.histories(32)
        task, _ = self.running()
        self.assertEqual(self.projection(task)["sample_count"], 30)
        estimates._history_cache.clear()
        with patch.object(estimates, "MAX_TASKS", 4):
            value = self.assert_unknown(task)
            self.assertLessEqual(value["sample_count"], 4)

    def test_presentation_is_read_only_and_does_not_rewrite_history(self):
        histories = self.histories()
        task, _ = self.running()
        paths = [self.root / item.id / estimates.FILENAME for item in histories]
        before = [path.read_bytes() for path in paths]
        for _ in range(3):
            self.projection(task)
        self.assertEqual([path.read_bytes() for path in paths], before)

    def test_real_saved_transcript_pipeline_measures_only_remaining_work(self):
        from app import subtitle_notes
        from app.models import MediaIntegrity
        from app.processor import process_saved_transcript_task
        task = create_task("local", "Synthetic", options=self.options)
        path = write_json(task.id, "transcript.json", self.transcript.model_dump(mode="json"))
        update_task(task.id, transcript_path=str(path), media_integrity=MediaIntegrity(duration=300, status="ready"))
        normalize = subtitle_notes.normalize_note_markdown
        def summarize(*args, **kwargs):
            self.tick(20)
            return "# Synthetic\n\nSynthetic evidence only.", "text-llm", "", []
        def local_checks(*args, **kwargs):
            self.tick(5)
            return normalize(*args, **kwargs)
        with patch("app.processor.summarize_with_diagnostics", side_effect=summarize) as model, \
             patch("app.subtitle_notes.normalize_note_markdown", side_effect=local_checks), \
             patch("app.subtitle_notes.time", estimates.time), \
             patch("app.pipeline_timing.monotonic", side_effect=lambda: self.clock):
            process_saved_transcript_task(task.id, self.options)
        model.assert_called_once()
        self.assertEqual(get_task(task.id).status, "success")
        entry = read_json(task.id, estimates.FILENAME, {})["attempts"][-1]
        self.assertEqual(entry["status"], "completed")
        self.assertEqual(entry["duration_seconds"], 25)
        self.assertEqual(entry["context"]["route"], "transcript_to_note")
        self.assertEqual(entry["context"]["media_seconds"], 300)

    def test_task_api_projection_keeps_legacy_eta_unknown_and_schema_unchanged(self):
        from app.main import task_payload
        self.histories()
        task, _ = self.running()
        original = get_task(task.id).model_dump(mode="json")
        value = task_payload(get_task(task.id))
        self.assertIsNone(value["eta_seconds"])
        self.assertEqual(value["duration_estimate"]["status"], "estimated")
        self.assertNotIn("duration_estimate", get_task(task.id).model_dump(mode="json"))
        self.assertEqual(get_task(task.id).model_dump(mode="json"), original)

    def test_linked_current_evidence_is_unknown_without_following_it(self):
        task, _ = self.running()
        with patch.object(Path, "is_symlink", return_value=True):
            self.assert_unknown(task, "evidence_unavailable")

    def test_negative_stage_timing_and_missing_verification_are_not_success_samples(self):
        for invalid in ("duration", "missing_verify"):
            task, attempt = self.running()
            self.tick(100)
            record_stage_duration(task.id, "summary", self.clock - 100, expected_attempt_id=attempt)
            if invalid == "duration":
                record_stage_duration(task.id, "verify", self.clock, expected_attempt_id=attempt)
            metrics = read_json(task.id, "pipeline_metrics.json", {})
            if invalid == "duration":
                metrics["attempts"][-1]["stages"]["summary"]["duration_ms"] = -1
            write_json(task.id, "pipeline_metrics.json", metrics)
            update_task(task.id, status="success", phase="completed")
            finish_pipeline_attempt(task.id, expected_attempt_id=attempt)
            self.assertEqual(read_json(task.id, estimates.FILENAME, {})["attempts"][-1]["status"], "unusable")


if __name__ == "__main__":
    unittest.main()
