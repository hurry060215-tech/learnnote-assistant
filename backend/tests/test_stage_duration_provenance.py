"""Synthetic clocks prove stage boundaries without provider or media access."""
from contextlib import ExitStack, closing
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from types import SimpleNamespace
import copy
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app.models import FrameGrid, TaskOptions, TranscriptResult, TranscriptSegment
from app.observability import read_task_events
from app.pipeline_progress import current_pipeline_attempt, finish_pipeline_attempt, record_stage_duration, stage_duration_recorder, start_pipeline_attempt, write_progressive_draft
from app.pipeline_timing import measured_stage, queued_callback, take_queue_wait
from app.processor_state import TaskCancelled
from app.storage import create_task, get_task, read_json, task_dir, update_task, write_json
from app.summarizer import SummarizationCancelled, summarize_with_llm
from app.task_queue import LocalTaskQueue, _recover_processing
from app.worker_lease import worker_lease


class TimingFixtures(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in ("storage", "observability"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        self.clock = 0.0
        self.stack.enter_context(patch("app.pipeline_timing.monotonic", side_effect=lambda: self.clock))
        self.stack.enter_context(patch("app.pipeline_progress.time", SimpleNamespace(monotonic=lambda: self.clock, time=time.time)))
        self.options = TaskOptions(llm_base_url="http://127.0.0.1:1/v1", llm_model="fixture-vision",
                                   llm_api_key="dummy", use_saved_connection=False, vision_batch_size=1,
                                   vision_concurrency=1)

    def metrics(self, task_id):
        return read_json(task_id, "pipeline_metrics.json", {})

    def stage(self, task_id, name):
        return self.metrics(task_id)["stages"][name]

    def queue(self):
        queue = LocalTaskQueue(self.root)
        queue.concurrency = {"heavy": 1, "light": 1, "download": 1}
        self.addCleanup(queue.stop)
        return queue


class QueueTimingTests(TimingFixtures):
    def test_accepted_enqueue_to_dispatch_excludes_confirmation_and_callback_prelude(self):
        queue = self.queue()
        task = create_task("local", "Synthetic task")
        # A saved task may await user confirmation for any length of time.
        self.clock = 100
        with worker_lease(self.root, lane="heavy", slot=0) as acquired:
            self.assertTrue(acquired)
            def work():
                self.clock = 500  # Validation/snapshot work before pipeline startup.
                start_pipeline_attempt(task.id)
            first = queue.enqueue(task.id, "local", work)
            self.clock = 150
            self.assertIs(queue.enqueue(task.id, "local", lambda: self.fail("duplicate ran")), first)
            self.clock = 207
        first.result(5)
        self.assertEqual(self.stage(task.id, "queue")["duration_ms"], 107000)
        self.assertEqual(sum(e["event"] == "task_enqueued" for e in read_task_events(task.id)), 1)
        self.assertIsNone(take_queue_wait("unrelated"))

    def test_retries_and_later_tasks_do_not_reuse_an_earlier_wait(self):
        queue = self.queue()
        for name, enqueue_at, dispatch_at in (("retry", 10, 13), ("retry", 50, 55), ("other", 90, 91)):
            self.clock = enqueue_at
            with worker_lease(self.root, lane="heavy", slot=0):
                future = queue.enqueue(name, "local", lambda name=name: start_pipeline_attempt(name))
                self.clock = dispatch_at
            future.result(5)
            self.assertEqual(self.stage(name, "queue")["duration_ms"], (dispatch_at - enqueue_at) * 1000)
        attempts = self.metrics("retry")["attempts"]
        self.assertEqual([a["stages"]["queue"]["duration_ms"] for a in attempts], [3000, 5000])
        self.assertNotEqual(attempts[0]["attempt_id"], attempts[1]["attempt_id"])
        self.assertEqual(sum(e["event"] == "task_enqueued" for e in read_task_events("retry")), 2)

    def test_observer_keeps_original_enqueue_and_never_creates_a_second_attempt(self):
        queue, observer = self.queue(), LocalTaskQueue(self.root)
        self.addCleanup(observer.stop)
        self.clock = 10
        with worker_lease(self.root, lane="heavy", slot=0):
            actual = queue.enqueue("owned", "local", lambda: start_pipeline_attempt("owned"))
            self.clock = 30
            duplicate = observer.enqueue("owned", "local", lambda: self.fail("observer ran"))
            self.clock = 40
        actual.result(5)
        duplicate.result(5)
        self.assertEqual(self.stage("owned", "queue")["duration_ms"], 30000)
        self.assertEqual(len(self.metrics("owned")["attempts"]), 1)
        self.assertEqual(sum(e["event"] == "task_enqueued" for e in read_task_events("owned")), 1)

    def test_restart_times_only_fresh_reenqueue_and_context_wait_has_no_measurement(self):
        queue = self.queue()
        local = create_task("local", "Synthetic local", options=self.options)
        private = create_task("current_page", "Synthetic context", options=self.options)
        media = self.root / "synthetic.mp4"
        media.write_bytes(b"not decoded")
        update_task(local.id, status="running", source_media_path=str(media))
        update_task(private.id, status="running")
        start_pipeline_attempt(local.id)
        record_stage_duration(local.id, "download", 0, ended_at=4)
        with closing(queue.connect()) as db, db:
            for task, requires_context in ((local, 0), (private, 1)):
                db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at) VALUES (?,?,?,'running',1)",
                           (task.id, "local" if not requires_context else "page", requires_context))
        self.clock = 900
        with patch("app.task_queue.queue_for", return_value=queue), \
             patch("app.processor.process_local_video_task", side_effect=lambda task_id, *_a, **_k: start_pipeline_attempt(task_id)):
            with worker_lease(self.root, lane="heavy", slot=0):
                result = _recover_processing(self.root)
                self.clock = 905
            queue.stop()
        self.assertEqual(result, {"recovered": 1, "waiting_for_context": 1})
        self.assertEqual(self.stage(local.id, "queue")["duration_ms"], 5000)
        self.assertNotIn("queue", self.metrics(local.id)["attempts"][0]["stages"])
        self.assertNotIn("download", self.metrics(local.id)["stages"])
        self.assertEqual(self.metrics(private.id), {})
        self.assertEqual(get_task(private.id).error_code, "resume_context_required")

    def test_pending_cancellation_has_no_executed_attempt_and_no_leaked_context(self):
        queue = self.queue()
        with worker_lease(self.root, lane="heavy", slot=0):
            future = queue.enqueue("cancelled", "local", lambda: self.fail("cancelled callback ran"))
            self.clock = 80
            self.assertTrue(queue.cancel_pending("cancelled"))
        future.result(5)
        self.assertEqual(self.metrics("cancelled"), {})
        self.assertFalse(any(e["event"] == "stage_timing" for e in read_task_events("cancelled")))
        self.assertIsNone(take_queue_wait("unrelated"))

    def test_failed_callback_resets_context_and_multiple_attempts_consume_once(self):
        def work():
            start_pipeline_attempt("failure")
            start_pipeline_attempt("failure")
            raise RuntimeError("synthetic failure")
        callback = queued_callback("failure", work)
        self.clock = 7
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            callback()
        attempts = self.metrics("failure")["attempts"]
        self.assertEqual(attempts[0]["stages"]["queue"]["duration_ms"], 7000)
        self.assertNotIn("queue", attempts[1]["stages"])
        start_pipeline_attempt("unrelated")
        self.assertNotIn("queue", self.metrics("unrelated")["stages"])


    def test_foreign_and_nested_tasks_cannot_consume_another_tasks_queue_interval(self):
        def outer():
            start_pipeline_attempt("foreign")
            self.clock = 8
            inner = queued_callback("inner", lambda: start_pipeline_attempt("inner"))
            self.clock = 9
            inner()
            self.clock = 20
            start_pipeline_attempt("outer")
        callback = queued_callback("outer", outer)
        self.clock = 7
        callback()
        self.assertNotIn("queue", self.metrics("foreign")["stages"])
        self.assertEqual(self.stage("outer", "queue")["duration_ms"], 7000)
        self.assertEqual(self.stage("inner", "queue")["duration_ms"], 1000)
        self.assertIsNone(take_queue_wait("outer"))
        self.assertIsNone(take_queue_wait("inner"))

    def test_optional_admission_event_failure_keeps_committed_job_dispatchable(self):
        queue = self.queue()
        with patch("app.task_queue.record_task_event", side_effect=OSError("synthetic log full")):
            future = queue.enqueue("logging-failure", "local", lambda: start_pipeline_attempt("logging-failure"))
        future.result(5)
        self.assertEqual(queue.entries()[0]["state"], "done")
        self.assertEqual(len(self.metrics("logging-failure")["attempts"]), 1)
        self.assertNotIn("logging-failure", queue.jobs)

    def test_optional_queue_measurement_failure_does_not_skip_work(self):
        queue = self.queue()
        completed = []
        def work():
            start_pipeline_attempt("timing-failure")
            completed.append(True)
        with patch("app.pipeline_progress.record_stage_duration", side_effect=OSError("synthetic metrics full")):
            queue.enqueue("timing-failure", "local", work).result(5)
        self.assertEqual(completed, [True])
        self.assertNotIn("queue", self.metrics("timing-failure")["stages"])
        self.assertEqual(queue.entries()[0]["state"], "done")


class SummaryStageTimingTests(TimingFixtures):
    def setUp(self):
        super().setUp()
        self.grids = []
        for index in range(2):
            image = self.root / f"grid-{index}.jpg"
            image.write_bytes(b"synthetic image")
            self.grids.append(FrameGrid(path=str(image), url=f"http://127.0.0.1/grid-{index}",
                                        start=index * 10, end=(index + 1) * 10, frame_count=1))
        self.transcript = TranscriptResult(full_text="Original source.")
        self.stack.enter_context(patch("openai.OpenAI", return_value=SimpleNamespace()))

    def run_summary(self, task_id, *, enabled=True, fail=None, cancel=False, cached=False, parallel=False, observer=None):
        self.clock = 0
        calls = []
        barrier = threading.Barrier(2) if parallel else None
        def complete(_client, *, events, stage, cancel_check, **kwargs):
            calls.append((stage, copy.deepcopy(kwargs)))
            if stage == "vision_batch":
                if barrier:
                    barrier.wait(3)
                    self.clock = 9
                else:
                    self.clock += 7
            else:
                self.clock += 5
            if fail == stage:
                raise RuntimeError("synthetic failure")
            text = "Partial source." if stage == "vision_batch" else "# Source\n\nOriginal source."
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
        def validate(*args, **kwargs):
            self.clock += 11  # Existing validation/repair is outside the merge interval.
            return args[3]
        def cache(*_args):
            self.clock += 2
            return "Partial source."
        attempt_id = start_pipeline_attempt(task_id)
        with ExitStack() as stack:
            stack.enter_context(patch("app.summarizer._compatible_completion", side_effect=complete))
            stack.enter_context(patch("app.summarizer._validated_generated_note", side_effect=validate))
            if cached:
                stack.enter_context(patch("app.summarizer._read_vision_cache", side_effect=cache))
            result = summarize_with_llm("Source", self.transcript, self.grids,
                self.options.model_copy(update={"vision_concurrency": 2 if parallel else 1}),
                cancel_check=lambda: cancel and bool(calls),
                timing_callback=observer or (stage_duration_recorder(task_id, attempt_id) if enabled else None))
        return result, calls

    def test_vision_and_merge_are_direct_intervals_with_identical_requests_and_output(self):
        baseline, baseline_calls = self.run_summary("baseline", enabled=False)
        actual, actual_calls = self.run_summary("measured")
        self.assertEqual(actual, baseline)
        self.assertEqual(actual_calls, baseline_calls)
        self.assertEqual([stage for stage, _ in actual_calls], ["vision_batch", "vision_batch", "vision_merge"])
        self.assertEqual(self.stage("measured", "vision")["duration_ms"], 14000)
        self.assertEqual(self.stage("measured", "merge")["duration_ms"], 5000)
        self.assertNotIn("verify", self.metrics("measured")["stages"])

    def test_parallel_batch_wall_time_is_not_sum_of_request_durations(self):
        _result, calls = self.run_summary("parallel", parallel=True)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.stage("parallel", "vision")["duration_ms"], 9000)
        self.assertEqual(self.stage("parallel", "merge")["duration_ms"], 5000)

    def test_cache_hit_wall_time_is_measured_without_extra_model_requests(self):
        _result, calls = self.run_summary("cached", cached=True)
        self.assertEqual([stage for stage, _ in calls], ["vision_merge"])
        self.assertEqual(self.stage("cached", "vision")["duration_ms"], 4000)

    def test_failed_merge_retains_completed_vision_and_records_no_verification(self):
        result, calls = self.run_summary("failed", fail="vision_merge")
        self.assertIsNone(result)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.stage("failed", "vision")["status"], "completed")
        self.assertEqual(self.stage("failed", "merge")["status"], "failed")
        self.assertEqual(self.stage("failed", "merge")["duration_ms"], 5000)
        self.assertNotIn("verify", self.metrics("failed")["stages"])

    def test_cancelled_vision_records_partial_interval_without_dispatching_merge(self):
        with self.assertRaises(SummarizationCancelled):
            self.run_summary("cancel", cancel=True)
        self.assertEqual(self.stage("cancel", "vision")["status"], "cancelled")
        self.assertEqual(self.stage("cancel", "vision")["duration_ms"], 7000)
        self.assertNotIn("merge", self.metrics("cancel")["stages"])

    def test_short_text_skips_vision_and_merge_without_fabricated_zero(self):
        self.grids = []
        _result, calls = self.run_summary("text")
        self.assertEqual([stage for stage, _ in calls], ["text_summary"])
        for stage in ("vision", "merge"):
            self.assertEqual(self.stage("text", stage)["status"], "skipped")
            self.assertNotIn("duration_ms", self.stage("text", stage))


    def test_unsupported_vision_records_skipped_without_changing_text_route(self):
        with patch("app.summarizer.llm_model_supports_vision", return_value=False):
            baseline, baseline_calls = self.run_summary("unsupported-baseline", enabled=False)
            result, calls = self.run_summary("unsupported")
        self.assertEqual(result, baseline)
        self.assertEqual(calls, baseline_calls)
        self.assertEqual([stage for stage, _ in calls], ["text_summary"])
        self.assertEqual(self.stage("unsupported", "vision")["status"], "skipped")
        self.assertNotIn("duration_ms", self.stage("unsupported", "vision"))

    def test_observation_failure_never_changes_model_requests_outputs_or_cancellation(self):
        def broken(*args, **kwargs):
            raise OSError("synthetic metrics full")
        baseline, baseline_calls = self.run_summary("healthy", enabled=False)
        result, calls = self.run_summary("broken", observer=broken)
        self.assertEqual(result, baseline)
        self.assertEqual(calls, baseline_calls)
        self.assertEqual(self.metrics("broken")["stages"], {})
        with self.assertRaises(SummarizationCancelled):
            self.run_summary("broken-cancel", observer=broken, cancel=True)
        result, calls = self.run_summary("broken-merge", observer=broken, fail="vision_merge")
        self.assertIsNone(result)
        self.assertEqual([stage for stage, _ in calls], ["vision_batch", "vision_batch", "vision_merge"])
        self.grids = []
        result, calls = self.run_summary("broken-text", observer=broken)
        self.assertIsNotNone(result)
        self.assertEqual([stage for stage, _ in calls], ["text_summary"])

    def test_text_chunk_assembly_is_timed_once_and_keeps_all_requests_and_bytes(self):
        self.grids = []
        self.transcript = TranscriptResult(full_text="Original source. " * 8000)
        baseline, baseline_calls = self.run_summary("chunk-baseline", enabled=False)
        result, calls = self.run_summary("chunk")
        self.assertEqual(result, baseline)
        self.assertEqual(calls, baseline_calls)
        self.assertGreater(len(calls), 3)
        self.assertTrue(all(stage == "text_summary" for stage, _ in calls))
        # Local concatenation genuinely takes zero synthetic clock ticks.
        self.assertEqual(self.stage("chunk", "merge")["duration_ms"], 0)
        self.assertEqual(self.stage("chunk", "merge")["status"], "completed")
        self.assertEqual(sum(e["event"] == "stage_timing" and e["phase"] == "merge"
                             for e in read_task_events("chunk")), 1)


class LocalCheckTimingTests(TimingFixtures):
    def test_summary_success_is_not_attempt_completion_before_local_checks_and_persistence(self):
        start_pipeline_attempt("final")
        self.clock = 2
        record_stage_duration("final", "summary", 0)
        attempt = self.metrics("final")["attempts"][-1]
        self.assertEqual(attempt["status"], "running")
        self.assertNotIn("finished_at_unix_ms", attempt)
        with measured_stage("verify", partial(record_stage_duration, "final")):
            self.clock = 5
        self.assertEqual(self.stage("final", "verify")["duration_ms"], 3000)
        self.assertEqual(self.metrics("final")["attempts"][-1]["status"], "running")
        finish_pipeline_attempt("final", expected_attempt_id=current_pipeline_attempt("final"))
        self.assertEqual(self.metrics("final")["attempts"][-1]["status"], "completed")

    def test_local_failure_or_cancellation_preserves_exception_and_measured_interval(self):
        for error, status in ((RuntimeError("synthetic"), "failed"), (TaskCancelled("synthetic"), "cancelled")):
            start_pipeline_attempt(status)
            self.clock = 10
            with self.assertRaises(type(error)) as raised:
                with measured_stage("verify", partial(record_stage_duration, status), cancelled=(TaskCancelled,)):
                    self.clock = 13
                    raise error
            self.assertIs(raised.exception, error)
            self.assertEqual(self.stage(status, "verify")["duration_ms"], 3000)
            self.assertEqual(self.stage(status, "verify")["status"], status)
            self.assertEqual(self.metrics(status)["attempts"][-1]["status"], status)

    def test_saved_transcript_verification_times_only_existing_output_and_source_checks(self):
        from app import subtitle_notes
        from app.processor import process_saved_transcript_task
        task = create_task("local", "Synthetic", options=self.options)
        transcript = TranscriptResult(source="fixture", full_text="Original source.",
            segments=[TranscriptSegment(start=0, end=10, text="Original source.")])
        path = write_json(task.id, "transcript.json", transcript.model_dump(mode="json"))
        update_task(task.id, transcript_path=str(path))
        normalize = subtitle_notes.normalize_note_markdown
        claims = subtitle_notes.build_claim_evidence_map
        def summary(*args, **kwargs):
            self.clock += 20
            return "# Synthetic\n\nOriginal source.", "text-llm", "", []
        def local_format(*args, **kwargs):
            self.assertEqual(self.metrics(task.id)["attempts"][-1]["status"], "running")
            self.clock += 3
            return normalize(*args, **kwargs)
        def local_sources(*args, **kwargs):
            self.clock += 2
            return claims(*args, **kwargs)
        with patch("app.processor.summarize_with_diagnostics", side_effect=summary) as model, \
             patch("app.subtitle_notes.normalize_note_markdown", side_effect=local_format), \
             patch("app.subtitle_notes.build_claim_evidence_map", side_effect=local_sources):
            process_saved_transcript_task(task.id, self.options.model_copy(update={"visual_understanding": False}))
        model.assert_called_once()
        self.assertEqual(get_task(task.id).status, "success")
        self.assertEqual(self.stage(task.id, "verify")["duration_ms"], 5000)
        self.assertEqual(self.metrics(task.id)["attempts"][-1]["status"], "completed")
        self.assertEqual(Path(get_task(task.id).note_path).read_text(encoding="utf-8"),
                         "# Synthetic\n\n> 证据来源：已保存的音频转写；本次未分析画面。\n\nOriginal source.\n")


    def test_completed_note_survives_final_metric_write_failure_without_retry(self):
        from app.processor import process_saved_transcript_task
        task = create_task("local", "Synthetic", options=self.options)
        transcript = TranscriptResult(source="fixture", full_text="Original source.",
            segments=[TranscriptSegment(start=0, end=10, text="Original source.")])
        path = write_json(task.id, "transcript.json", transcript.model_dump(mode="json"))
        update_task(task.id, transcript_path=str(path))
        def fail_only_finish(task_id, filename, payload):
            if filename == "pipeline_metrics.json" and payload["attempts"][-1]["status"] == "completed":
                raise OSError("synthetic final metric full")
            return write_json(task_id, filename, payload)
        with patch("app.processor.summarize_with_diagnostics", return_value=("# Synthetic\n\nOriginal source.", "text-llm", "", [])) as model, \
             patch("app.pipeline_progress.write_json", side_effect=fail_only_finish):
            process_saved_transcript_task(task.id, self.options.model_copy(update={"visual_understanding": False}))
        model.assert_called_once()
        self.assertEqual(get_task(task.id).status, "success")
        self.assertEqual(get_task(task.id).error_code, "")
        self.assertTrue(Path(get_task(task.id).note_path).is_file())
        self.assertNotIn("finished_at_unix_ms", self.metrics(task.id)["attempts"][-1])

    def test_observation_failure_does_not_mask_original_local_check_exception(self):
        original = TaskCancelled("synthetic cancellation")
        def broken(*args):
            raise OSError("synthetic observer failure")
        with self.assertRaises(TaskCancelled) as raised:
            with measured_stage("verify", broken, cancelled=(TaskCancelled,)):
                raise original
        self.assertIs(raised.exception, original)


    def test_video_local_checks_follow_summary_and_finish_only_after_publication(self):
        task_id = self.run_video_checks("# Synthetic\n\nOriginal source.")
        self.assertEqual(self.stage(task_id, "summary")["duration_ms"], 20000)
        self.assertEqual(self.stage(task_id, "verify")["duration_ms"], 5000)
        self.assertEqual(self.metrics(task_id)["attempts"][-1]["status"], "completed")
        self.assertEqual(get_task(task_id).status, "success")
        self.assertTrue(Path(get_task(task_id).note_path).is_file())

    def test_video_blocked_output_records_failed_local_check_without_publishing(self):
        task_id = self.run_video_checks("# Synthetic\n\nOriginal source. Invalid \ufffd text.")
        self.assertEqual(self.stage(task_id, "summary")["status"], "completed")
        self.assertEqual(self.stage(task_id, "verify")["status"], "failed")
        self.assertEqual(self.stage(task_id, "verify")["duration_ms"], 3000)
        self.assertEqual(self.metrics(task_id)["attempts"][-1]["status"], "failed")
        self.assertEqual(get_task(task_id).error_code, "note_quality_failed")
        self.assertFalse((task_dir(task_id) / "note.md").exists())

    def run_video_checks(self, note):
        from app import note_pipeline
        from app.models import EvidenceCoverage, MediaIntegrity
        task = create_task("local", "Synthetic", options=self.options)
        start_pipeline_attempt(task.id)
        update_task(task.id, status="running", phase="summarizing")
        transcript = TranscriptResult(source="fixture", full_text="Original source.",
            segments=[TranscriptSegment(start=0, end=10, text="Original source.")])
        normalize = note_pipeline.normalize_note_markdown
        claims = note_pipeline.build_claim_evidence_map
        def summary(*args):
            self.clock = 20
            record_stage_duration(task.id, "summary", 0)
            return note, "text-llm", "", []
        def local_format(*args, **kwargs):
            attempt = self.metrics(task.id)["attempts"][-1]
            self.assertEqual(attempt["status"], "running")
            self.assertNotIn("finished_at_unix_ms", attempt)
            self.clock += 3
            return normalize(*args, **kwargs)
        def local_sources(*args, **kwargs):
            self.clock += 2
            return claims(*args, **kwargs)
        with patch("app.note_pipeline.normalize_note_markdown", side_effect=local_format), \
             patch("app.note_pipeline.build_claim_evidence_map", side_effect=local_sources):
            note_pipeline.finish_note_task(task.id, task.title, "", self.options, transcript,
                [], [], [], [], MediaIntegrity(status="ready", duration=10), "", "", "", None,
                has_visual_summary_evidence=lambda *args: False,
                calculate_evidence_coverage=lambda *args, **kwargs: EvidenceCoverage(status="ready", can_summarize=True),
                evidence_coverage_markdown=lambda *args: "## 依据与覆盖\n\nOriginal source.",
                summarize_with_diagnostics=summary, build_summary_diagnostics=lambda **kwargs: {},
                check_cancel=lambda task_id: None,
                mark_checkpoint=lambda task_id, checkpoint: update_task(task_id, checkpoint=checkpoint))
        return task.id


class AttemptIsolationTests(TimingFixtures):
    def test_stale_stage_and_final_callbacks_leave_retry_metrics_and_events_unchanged(self):
        attempt_a = start_pipeline_attempt("retry")
        observe_a = stage_duration_recorder("retry", attempt_a)
        finish_a = partial(finish_pipeline_attempt, "retry", expected_attempt_id=attempt_a)
        attempt_b = start_pipeline_attempt("retry")
        before = self.metrics("retry")
        events_before = read_task_events("retry")
        self.clock = 9
        for stage in ("queue", "frames", "vision", "merge", "verify", "visual", "summary"):
            for status in ("completed", "failed", "cancelled", "skipped"):
                observe_a(stage, None if status == "skipped" else 0, status)
        finish_a()
        finish_a("failed")
        self.assertEqual(self.metrics("retry"), before)
        self.assertEqual(read_task_events("retry"), events_before)
        self.assertEqual(before["current_attempt_id"], attempt_b)
        self.assertEqual(before["stages"], {})
        self.assertEqual(before["attempts"][-1]["status"], "running")
        self.assertNotIn("finished_at_unix_ms", before["attempts"][-1])
        # The current attempt still records and completes normally.
        stage_duration_recorder("retry", attempt_b)("verify", 4, "completed")
        finish_pipeline_attempt("retry", expected_attempt_id=attempt_b)
        self.assertEqual(self.stage("retry", "verify")["duration_ms"], 5000)
        self.assertEqual(self.metrics("retry")["attempts"][-1]["status"], "completed")

    def test_retry_start_cannot_interleave_with_stage_finish_or_draft_metadata_commit(self):
        from app import pipeline_progress
        for operation in ("stage", "finish", "draft"):
            with self.subTest(operation=operation):
                task_id = "atomic-" + operation
                attempt_a = start_pipeline_attempt(task_id)
                writing, release, retry_lock_entered = threading.Event(), threading.Event(), threading.Event()
                retry_thread = [None]
                actual_lock = pipeline_progress._task_data_lock
                class ObservedLock:
                    def __enter__(self):
                        if threading.get_ident() == retry_thread[0]:
                            retry_lock_entered.set()
                        return actual_lock.__enter__()
                    def __exit__(self, *args):
                        return actual_lock.__exit__(*args)
                actual_write = pipeline_progress.write_json
                def paused_write(target_id, filename, payload):
                    if target_id == task_id and filename == "pipeline_metrics.json" and payload["current_attempt_id"] == attempt_a:
                        writing.set()
                        if not release.wait(5):
                            raise AssertionError("Synthetic write was not released")
                    return actual_write(target_id, filename, payload)
                def old_write():
                    if operation == "stage":
                        stage_duration_recorder(task_id, attempt_a)("frames", 0, "completed")
                    elif operation == "finish":
                        finish_pipeline_attempt(task_id, expected_attempt_id=attempt_a)
                    else:
                        write_progressive_draft(task_id, "Synthetic", TranscriptResult(full_text="Original source."))
                def retry():
                    retry_thread[0] = threading.get_ident()
                    return start_pipeline_attempt(task_id)
                with patch("app.pipeline_progress.write_json", side_effect=paused_write), \
                     patch("app.pipeline_progress._task_data_lock", ObservedLock()), ThreadPoolExecutor(max_workers=2) as workers:
                    old = workers.submit(old_write)
                    try:
                        self.assertTrue(writing.wait(5))
                        new = workers.submit(retry)
                        self.assertTrue(retry_lock_entered.wait(5))
                        self.assertFalse(new.done(), "Retry must wait until the old metadata transaction commits")
                    finally:
                        release.set()
                    old.result(5)
                    attempt_b = new.result(5)
                payload = self.metrics(task_id)
                self.assertEqual(payload["current_attempt_id"], attempt_b)
                self.assertEqual(payload["stages"], {})
                self.assertEqual(payload["draft"], {})
                self.assertEqual(payload["attempts"][-1]["status"], "running")
                self.assertNotIn("finished_at_unix_ms", payload["attempts"][-1])

    def test_saved_text_finalization_keeps_captured_identity_across_summary_return(self):
        from app.processor import process_saved_transcript_task
        task = create_task("local", "Synthetic", options=self.options)
        transcript = TranscriptResult(source="fixture", full_text="Original source.",
            segments=[TranscriptSegment(start=0, end=10, text="Original source.")])
        path = write_json(task.id, "transcript.json", transcript.model_dump(mode="json"))
        update_task(task.id, transcript_path=str(path))
        retry_snapshot = []
        def summary(*args, **kwargs):
            # Retain the old callback passed through the real processor adapter.
            old_callback = kwargs["timing_callback"]
            start_pipeline_attempt(task.id)
            retry_snapshot.append(self.metrics(task.id))
            old_callback("merge", 0, "completed")
            return "# Synthetic\n\nOriginal source.", "text-llm", "", []
        with patch("app.processor.summarize_with_diagnostics", side_effect=summary) as model:
            process_saved_transcript_task(task.id, self.options.model_copy(update={"visual_understanding": False}))
        model.assert_called_once()
        self.assertEqual(self.metrics(task.id), retry_snapshot[0])
        self.assertEqual(self.metrics(task.id)["stages"], {})

    def test_unknown_capture_never_recaptures_later_attempt_in_either_finalizer(self):
        from app import note_pipeline, subtitle_notes
        from app.models import EvidenceCoverage, MediaIntegrity
        transcript = TranscriptResult(source="fixture", full_text="Original source.",
            segments=[TranscriptSegment(start=0, end=10, text="Original source.")])
        for route in ("video", "subtitle"):
            with self.subTest(route=route):
                task = create_task("local", "Synthetic", options=self.options)
                start_pipeline_attempt(task.id)
                before = self.metrics(task.id)
                with patch(f"app.{route + '_notes' if route == 'subtitle' else 'note_pipeline'}.current_pipeline_attempt",
                           side_effect=AssertionError("An explicit unknown capture must never be reacquired")):
                    if route == "subtitle":
                        subtitle_notes.finish_transcript_note(task.id, task.title, "", transcript, self.options,
                            duration=10, media_skipped=True,
                            summarize=lambda *args: ("# Synthetic\n\nOriginal source.", "text-llm", "", []),
                            build_diagnostics=lambda **kwargs: {}, check_cancel=lambda task_id: None, attempt_id=None)
                    else:
                        note_pipeline.finish_note_task(task.id, task.title, "", self.options, transcript,
                            [], [], [], [], MediaIntegrity(status="ready", duration=10), "", "", "", None,
                            has_visual_summary_evidence=lambda *args: False,
                            calculate_evidence_coverage=lambda *args, **kwargs: EvidenceCoverage(status="ready", can_summarize=True),
                            evidence_coverage_markdown=lambda *args: "## 依据与覆盖\n\nOriginal source.",
                            summarize_with_diagnostics=lambda *args: ("# Synthetic\n\nOriginal source.", "text-llm", "", []),
                            build_summary_diagnostics=lambda **kwargs: {}, check_cancel=lambda task_id: None,
                            mark_checkpoint=lambda *args: None, attempt_id=None)
                self.assertEqual(self.metrics(task.id), before)
                self.assertEqual(get_task(task.id).status, "success")

    def test_video_finalizer_keeps_explicit_attempt_identity(self):
        from app import note_pipeline
        from app.models import EvidenceCoverage, MediaIntegrity
        task = create_task("local", "Synthetic", options=self.options)
        attempt_a = start_pipeline_attempt(task.id)
        transcript = TranscriptResult(source="fixture", full_text="Original source.",
            segments=[TranscriptSegment(start=0, end=10, text="Original source.")])
        retry_snapshot = []
        def summary(*args):
            start_pipeline_attempt(task.id)
            retry_snapshot.append(self.metrics(task.id))
            return "# Synthetic\n\nOriginal source.", "text-llm", "", []
        note_pipeline.finish_note_task(task.id, task.title, "", self.options, transcript,
            [], [], [], [], MediaIntegrity(status="ready", duration=10), "", "", "", None,
            has_visual_summary_evidence=lambda *args: False,
            calculate_evidence_coverage=lambda *args, **kwargs: EvidenceCoverage(status="ready", can_summarize=True),
            evidence_coverage_markdown=lambda *args: "## 依据与覆盖\n\nOriginal source.",
            summarize_with_diagnostics=summary, build_summary_diagnostics=lambda **kwargs: {},
            check_cancel=lambda task_id: None,
            mark_checkpoint=lambda *args: None, attempt_id=attempt_a)
        self.assertEqual(self.metrics(task.id), retry_snapshot[0])


class FrameStageTimingTests(TimingFixtures):
    def test_local_preparation_records_frames_and_retains_existing_visual_aggregate(self):
        self.run_frames()
        self.assertEqual(self.stage(self.task.id, "frames")["duration_ms"], 8000)
        self.assertEqual(self.stage(self.task.id, "visual")["duration_ms"], 10000)
        self.assertEqual(self.stage(self.task.id, "frames")["status"], "completed")

    def test_ocr_only_preparation_is_still_measured_as_local_frames(self):
        self.run_frames(visual=False, ocr=True)
        self.assertEqual(self.stage(self.task.id, "frames")["duration_ms"], 8000)
        self.assertEqual(self.stage(self.task.id, "frames")["status"], "completed")

    def test_disabled_frame_work_is_skipped_without_measured_zero(self):
        self.run_frames(visual=False)
        self.assertEqual(self.stage(self.task.id, "frames")["status"], "skipped")
        self.assertNotIn("duration_ms", self.stage(self.task.id, "frames"))

    def test_failed_and_cancelled_frames_record_elapsed_work_without_later_stages(self):
        for error, status in ((RuntimeError("synthetic"), "failed"), (TaskCancelled("synthetic"), "cancelled")):
            with self.assertRaises(type(error)):
                self.run_frames(error=error)
            self.assertEqual(self.stage(self.task.id, "frames")["status"], status)
            self.assertEqual(self.stage(self.task.id, "frames")["duration_ms"], 8000)
            self.assertNotIn("visual", self.metrics(self.task.id)["stages"])
            self.assertNotIn("summary", self.metrics(self.task.id)["stages"])

    def run_frames(self, *, visual=True, ocr=False, error=None):
        from app.models import MediaIntegrity
        from app.processor import _process_video_file
        from app.visual_pipeline import VisualArtifacts
        self.task = create_task("local", "Synthetic", options=self.options)
        media = task_dir(self.task.id) / "source.mp4"
        media.write_bytes(b"synthetic media, never decoded")
        transcript = TranscriptResult(source="fixture", full_text="Original source.",
            segments=[TranscriptSegment(start=0, end=10, text="Original source.")])
        self.clock = 10
        def prepare(*args, **kwargs):
            self.clock += 8
            if error is not None:
                raise error
            return VisualArtifacts([], [], [], "", metrics={})
        def index(*args, **kwargs):
            self.clock += 2
            return ""
        with patch("app.processor.probe_media_integrity", return_value=MediaIntegrity(status="ready", duration=10)), \
             patch("app.processor.normalize_video"), \
             patch("app.processor.prepare_transcript", return_value=SimpleNamespace(transcript=transcript, asr_error="")), \
             patch("app.processor.extract_visual_evidence", side_effect=prepare), \
             patch("app.processor.write_visual_index", side_effect=index), \
             patch("app.processor.time", SimpleNamespace(monotonic=lambda: self.clock)), \
             patch("app.processor.finish_note_task") as finish:
            _process_video_file(self.task.id, media, "Synthetic", "",
                self.options.model_copy(update={"visual_understanding": visual, "local_ocr": ocr}))
        finish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
