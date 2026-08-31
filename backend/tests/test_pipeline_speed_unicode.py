from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.media import extract_frames_adaptive
from app.models import FrameGrid, TaskOptions, TranscriptResult, TranscriptSegment
from app.observability import read_task_events
from app.pipeline_progress import record_stage_duration, start_pipeline_attempt, write_progressive_draft
from app.summarizer import SummarizationCancelled, _read_vision_cache, _vision_cache_key, summarize_with_diagnostics_audit, summarize_with_llm
from app.text_cleanup import TextDecodingError, canonicalize_unicode_text, decode_text_bytes


class UnicodePipelineTests(unittest.TestCase):
    def test_old_task_options_gain_safe_performance_defaults(self) -> None:
        options = TaskOptions.model_validate({"visual_understanding": True, "frame_interval": 20})
        self.assertEqual(options.frame_extract_batch_size, 12)
        self.assertEqual(options.vision_batch_size, 4)
        self.assertEqual(options.vision_concurrency, 2)

    def test_canonical_decoder_handles_common_chinese_encodings(self) -> None:
        for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "gb18030"):
            decoded = decode_text_bytes("课程总结".encode(encoding))
            self.assertEqual(decoded.text, "课程总结")

    def test_decoder_handles_shift_jis_and_does_not_reject_portuguese(self) -> None:
        self.assertEqual(decode_text_bytes("日本語字幕".encode("shift_jis")).text, "日本語字幕")
        self.assertEqual(canonicalize_unicode_text("Ãgua e Ãnimo"), "Ãgua e Ãnimo")

    def test_mojibake_is_repaired_or_blocked_without_silent_replacement(self) -> None:
        self.assertEqual(canonicalize_unicode_text("è¯¾ç¨‹æ€»ç»“"), "课程总结")
        gb_mojibake = "中文".encode("utf-8").decode("gb18030")
        self.assertEqual(canonicalize_unicode_text(gb_mojibake), "中文")
        with self.assertRaises(TextDecodingError):
            canonicalize_unicode_text("课程\ufffd总结")


class FrameBatchTests(unittest.TestCase):
    def test_batch_extraction_caches_kept_frames_and_avoids_per_frame_processes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "video.mp4"
            video.write_bytes(b"video")
            batch_calls: list[list[int]] = []

            def fake_batch(_ffmpeg, _video, requests):
                batch_calls.append([timestamp for timestamp, _output in requests])
                for timestamp, output in requests:
                    Image.new("RGB", (32, 18), (timestamp * 7 % 255, 80, 120)).save(output)
                return True

            common_patches = (
                patch("app.media.ffmpeg_bin", return_value="ffmpeg"),
                patch("app.media.probe_duration", return_value=40),
                patch("app.media.detect_scene_change_timestamps", return_value=[]),
                patch(
                    "app.media._adaptive_frame_plan",
                    return_value=[(0, ["start"]), (10, ["coverage"]), (20, ["coverage"]), (39, ["tail"])],
                ),
                patch("app.media._extract_frame_batch", side_effect=fake_batch),
                patch("app.media._extract_single_frame", side_effect=AssertionError("batch should not fall back")),
            )
            with common_patches[0], common_patches[1], common_patches[2], common_patches[3], common_patches[4], common_patches[5]:
                first, _ = extract_frames_adaptive(video, root / "frames", interval=10, batch_size=4)
                second, _ = extract_frames_adaptive(video, root / "frames", interval=10, batch_size=4)

            self.assertEqual(len(first), 4)
            self.assertEqual([path.name for path in first], [path.name for path in second])
            self.assertEqual(batch_calls, [[0, 10, 20, 39]])
            metrics = json.loads((root / "frames" / "frame_extraction_metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["cached_frame_count"], 4)
            self.assertEqual(metrics["ffmpeg_batch_process_count"], 0)

    def test_failed_batch_falls_back_only_for_missing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "video.mp4"
            video.write_bytes(b"video")
            fallback_calls: list[int] = []

            def failed_batch(_ffmpeg, _video, requests):
                timestamp, output = requests[0]
                Image.new("RGB", (32, 18), (timestamp, 40, 80)).save(output)
                return False

            def fallback(_ffmpeg, _video, timestamp, output):
                fallback_calls.append(timestamp)
                Image.new("RGB", (32, 18), (timestamp, 90, 120)).save(output)
                return True

            with patch("app.media.ffmpeg_bin", return_value="ffmpeg"), \
                patch("app.media.probe_duration", return_value=30), \
                patch("app.media.detect_scene_change_timestamps", return_value=[]), \
                patch("app.media._adaptive_frame_plan", return_value=[(0, ["start"]), (10, ["coverage"]), (20, ["tail"])]), \
                patch("app.media._extract_frame_batch", side_effect=failed_batch), \
                patch("app.media._extract_single_frame", side_effect=fallback):
                frames, _ = extract_frames_adaptive(video, root / "frames", interval=10, batch_size=3)

            self.assertEqual(fallback_calls, [10, 20])
            self.assertEqual(len(frames), 3)

    def test_invalid_cache_never_reuses_stale_frame_after_failed_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "video.mp4"
            video.write_bytes(b"new-video")
            frame_dir = root / "frames"
            frame_dir.mkdir()
            stale = frame_dir / "frame_0000_000000.jpg"
            Image.new("RGB", (32, 18), (255, 0, 0)).save(stale)
            fallback_calls = []

            def fallback(_ffmpeg, _video, timestamp, output):
                fallback_calls.append(timestamp)
                Image.new("RGB", (32, 18), (0, 255, 0)).save(output)
                return True

            with patch("app.media.ffmpeg_bin", return_value="ffmpeg"), \
                patch("app.media.probe_duration", return_value=10), \
                patch("app.media.detect_scene_change_timestamps", return_value=[]), \
                patch("app.media._adaptive_frame_plan", return_value=[(0, ["start"])]), \
                patch("app.media._extract_frame_batch", return_value=False), \
                patch("app.media._extract_single_frame", side_effect=fallback):
                frames, _ = extract_frames_adaptive(video, frame_dir, interval=10, batch_size=1)
            self.assertEqual(fallback_calls, [0])
            pixel = Image.open(frames[0]).getpixel((0, 0))
            self.assertLess(pixel[0], 10)
            self.assertGreater(pixel[1], 240)


class ProgressAndVisionTests(unittest.TestCase):
    def test_corrupt_vision_cache_is_a_miss_and_endpoint_identity_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / "bad.json").write_text("[]", encoding="utf-8")
            self.assertEqual(_read_vision_cache(cache, "bad"), "")
            grid = FrameGrid(path=str(cache / "missing.jpg"), url="", start=0, end=1, frame_count=1)
            first = _vision_cache_key("model", "http://localhost:11434/v1", "prompt", [(0, grid)])
            second = _vision_cache_key("model", "http://localhost:1234/v1", "prompt", [(0, grid)])
            third = _vision_cache_key("model", "http://localhost:11434/other", "prompt", [(0, grid)])
            self.assertEqual(len({first, second, third}), 3)

    def test_draft_and_stage_events_are_redacted_ordered_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
            patch("app.storage.TASK_DIR", Path(tmp)), \
            patch("app.observability.TASK_DIR", Path(tmp)):
            transcript = TranscriptResult(
                full_text="第一节 https://example.com/video?token=secret-value",
                segments=[TranscriptSegment(start=3, end=5, text="打开链接 https://example.com/a?signature=private")],
            )
            first = write_progressive_draft("task-1", "课程", transcript)
            second = write_progressive_draft("task-1", "课程", transcript)
            started = time.monotonic() - 0.01
            first_timing = record_stage_duration("task-1", "transcript", started)
            second_timing = record_stage_duration("task-1", "transcript", started - 1)

            self.assertEqual(first, second)
            draft = first.read_text(encoding="utf-8")
            self.assertNotIn("secret-value", draft)
            self.assertNotIn("private", draft)
            self.assertIn("<redacted>", draft)
            self.assertEqual(first_timing, second_timing)
            events = read_task_events("task-1")
            self.assertEqual(sum(event["event"] == "draft_ready" for event in events), 1)
            self.assertEqual(sum(event["event"] == "stage_timing" for event in events), 1)
            sequences = [event["details"]["sequence"] for event in events]
            self.assertEqual(sequences, sorted(sequences))

    def test_resumed_pipeline_keeps_attempt_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("app.storage.TASK_DIR", Path(tmp)), patch("app.observability.TASK_DIR", Path(tmp)):
            first_attempt = start_pipeline_attempt("resume-task")
            record_stage_duration("resume-task", "media", time.monotonic() - 0.01)
            second_attempt = start_pipeline_attempt("resume-task")
            record_stage_duration("resume-task", "media", time.monotonic() - 0.02)
            metrics = json.loads((Path(tmp) / "resume-task" / "pipeline_metrics.json").read_text(encoding="utf-8"))
            self.assertNotEqual(first_attempt, second_attempt)
            self.assertEqual(len(metrics["attempts"]), 2)
            self.assertEqual(metrics["current_attempt_id"], second_attempt)
            self.assertEqual(len([event for event in read_task_events("resume-task") if event["event"] == "stage_timing"]), 2)

    def test_draft_redacts_cloud_signature_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("app.storage.TASK_DIR", Path(tmp)), patch("app.observability.TASK_DIR", Path(tmp)):
            transcript = TranscriptResult(
                full_text="AWS https://s3.example.com/a?X-Amz-Credential=CRED&X-Amz-Signature=SIG&X-Amz-Expires=900",
                segments=[TranscriptSegment(start=0, end=1, text="CDN https://cdn.example.com/a?Policy=POLICY&Key-Pair-Id=KEY&Signature=SIGN")],
            )
            draft = write_progressive_draft("signed-url", "课程", transcript).read_text(encoding="utf-8")
        for secret in ("CRED", "SIG", "900", "POLICY", "KEY", "SIGN"):
            self.assertNotIn(f"={secret}", draft)
        self.assertIn("<redacted>", draft)

    def test_vision_batches_run_with_bounded_concurrency_and_cache(self) -> None:
        class Message:
            def __init__(self, content):
                self.content = content

        class Response:
            def __init__(self, content):
                self.choices = [types.SimpleNamespace(message=Message(content))]

        class FakeCompletions:
            def __init__(self):
                self.lock = threading.Lock()
                self.active = 0
                self.max_active = 0
                self.vision_calls = 0

            def create(self, **kwargs):
                content = kwargs["messages"][0]["content"]
                if not isinstance(content, list):
                    return Response("# Cached lesson\n\nMerged note with `00:00:00`.")
                with self.lock:
                    self.active += 1
                    self.vision_calls += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.03)
                with self.lock:
                    self.active -= 1
                return Response("partial")

        completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = types.SimpleNamespace(completions=completions)

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grids = []
            for index in range(8):
                image = root / f"grid-{index}.jpg"
                image.write_bytes(f"image-{index}".encode())
                grids.append(FrameGrid(path=str(image), url=f"http://local/{index}", start=index * 10, end=index * 10 + 10, frame_count=1))
            options = TaskOptions(llm_api_key="test", llm_model="vision-model", vision_batch_size=4, vision_concurrency=2)
            transcript = TranscriptResult(full_text="lesson", segments=[])
            cache_dir = root / "cache"
            with patch.dict(sys.modules, {"openai": fake_openai}):
                summarize_with_llm("Cached lesson", transcript, grids, options, vision_cache_dir=cache_dir)
                _note, _source, _warning, events = summarize_with_diagnostics_audit(
                    "Cached lesson", transcript, grids, options, vision_cache_dir=cache_dir
                )

            self.assertEqual(completions.max_active, 2)
            self.assertEqual(completions.vision_calls, 2)
            self.assertEqual(sum(event.get("stage") == "vision_cache" for event in events), 2)

    def test_cancellation_stops_dispatching_later_vision_batches(self) -> None:
        class FakeCompletions:
            def __init__(self):
                self.calls = 0

            def create(self, **_kwargs):
                self.calls += 1
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="partial"))])

        completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = types.SimpleNamespace(completions=completions)

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            grids = []
            for index in range(12):
                image = root / f"grid-{index}.jpg"
                image.write_bytes(f"image-{index}".encode())
                grids.append(FrameGrid(path=str(image), url=f"http://local/{index}", start=index, end=index + 1, frame_count=1))
            options = TaskOptions(llm_api_key="test", llm_model="vision-model", vision_batch_size=4, vision_concurrency=1)
            with patch.dict(sys.modules, {"openai": fake_openai}), self.assertRaises(SummarizationCancelled):
                summarize_with_llm(
                    "Cancel lesson",
                    TranscriptResult(full_text="lesson"),
                    grids,
                    options,
                    cancel_check=lambda: completions.calls >= 1,
                )
        self.assertEqual(completions.calls, 1)


if __name__ == "__main__":
    unittest.main()
