from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import config, resource_monitor, transcriber


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("public_media_asr_benchmark", ROOT / "scripts" / "benchmark-public-media-asr.py")
assert SPEC is not None and SPEC.loader is not None
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


class ScheduledTicks:
    """Schedule a fixed number of sampler ticks without sleeps or model work."""

    def __init__(self, ticks: int):
        self.remaining = ticks

    def wait(self, timeout: float) -> bool:
        self.remaining -= 1
        return self.remaining < 0

    def set(self) -> None:
        pass


class JoinedThread(threading.Thread):
    def start(self) -> None:
        super().start()
        self.join(timeout=3)
        if self.is_alive():
            raise RuntimeError("Synthetic sampler did not finish")


class PublicMediaAsrBenchmarkTests(unittest.TestCase):
    def run_benchmark(self, *, ticks: int = 1, cpu_times=None, model_error=None):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            data = Path(temporary) / "data"
            data.mkdir()
            audio_path = data / "public-synthetic.wav"
            report_path = data / "report.json"
            with wave.open(str(audio_path), "wb") as audio:
                audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * 16000)

            # Exercise the real transcribe_audio entry, replacing only inference.
            model = Mock()
            model.transcribe.return_value = (
                iter([SimpleNamespace(start=0, end=1, text="UNSAVED synthetic transcript")]),
                SimpleNamespace(language="en", duration=1),
            )
            model_type = Mock(return_value=model, side_effect=model_error)
            stack.enter_context(patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=model_type)}))
            stack.enter_context(patch.dict(os.environ, {"LEARNNOTE_LLM_API_KEY": "", "OPENAI_API_KEY": ""}))
            stack.enter_context(patch.object(config, "MODEL_CACHE_DIR", data / "model-cache"))
            stack.enter_context(patch.object(config, "TEMP_DIR", data / "temp"))
            stack.enter_context(patch.object(transcriber, "MODEL_CACHE_DIR", data / "model-cache"))
            stack.enter_context(patch.object(BENCHMARK, "MODEL_CACHE_DIR", data / "model-cache"))
            stack.enter_context(patch.object(BENCHMARK, "threading", SimpleNamespace(Event=lambda: ScheduledTicks(ticks), Thread=JoinedThread)))
            stack.enter_context(patch.object(BENCHMARK, "time", SimpleNamespace(
                monotonic=Mock(side_effect=[0, 0, *range(1, ticks + 1), ticks + 0.5, ticks + 1]),
                process_time=Mock(side_effect=cpu_times if cpu_times is not None else [n * 0.25 for n in range(ticks + 1)]),
            )))
            thread_errors = []
            stack.enter_context(patch.object(threading, "excepthook", thread_errors.append))
            stack.enter_context(patch.object(sys, "argv", [str(BENCHMARK.__file__), str(audio_path), "--output", str(report_path)]))
            stdout = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            exit_code = 0
            try:
                BENCHMARK.main()
            except SystemExit as exc:
                exit_code = exc.code
            report_text = report_path.read_text(encoding="utf-8")
            report = json.loads(report_text)
            self.assertEqual(json.loads(stdout.getvalue()), report)
            self.assertNotIn("UNSAVED", report_text)
            self.assertFalse(report["transcript_text_saved"])
            self.assertEqual(report["provider_api_calls"], 0)
            self.assertIs(BENCHMARK.transcribe_audio, transcriber.transcribe_audio)
            model_type.assert_called_once_with("tiny", device=BENCHMARK.DEFAULT_WHISPER_DEVICE, compute_type=BENCHMARK.DEFAULT_WHISPER_COMPUTE_TYPE)
            if not model_error:
                model.transcribe.assert_called_once_with(str(audio_path.resolve()), vad_filter=True)
            self.assertEqual(thread_errors, [])
            return report, exit_code

    def test_native_resources_survive_a_scheduled_sampler_tick(self):
        report, code = self.run_benchmark()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "pass")
        resources = report["resource_usage"]
        self.assertEqual(resources["status"], "complete")
        self.assertIsNone(resources["sampler_error"])
        self.assertEqual(resources["sample_count"], 1)
        self.assertGreater(resources["rss_peak_bytes"], 0)
        self.assertGreater(resources["disk_free_min_bytes"], 0)

    def test_short_run_reports_no_observations_as_null(self):
        report, code = self.run_benchmark(ticks=0)
        self.assertEqual(code, 0)
        resources = report["resource_usage"]
        self.assertEqual(resources["status"], "unavailable")
        self.assertEqual(resources["sample_count"], 0)
        for metric in ("rss_peak_bytes", "process_cpu_percent_mean", "process_cpu_percent_peak", "disk_free_before_bytes", "disk_free_min_bytes", "disk_free_after_bytes"):
            self.assertIsNone(resources[metric], metric)

    def test_cpu_uses_each_interval_and_can_exceed_one_core(self):
        with patch.object(BENCHMARK, "rss_bytes", side_effect=[100, 200]), patch.object(BENCHMARK, "disk_free_bytes", side_effect=[1000, 900]):
            report, _ = self.run_benchmark(ticks=2, cpu_times=[10, 10.5, 12.5])
        resources = report["resource_usage"]
        self.assertEqual(resources["process_cpu_percent_mean"], 125)
        self.assertEqual(resources["process_cpu_percent_peak"], 200)
        self.assertEqual(resources["rss_peak_bytes"], 200)
        self.assertEqual(resources["disk_free_before_bytes"], 1000)
        self.assertEqual(resources["disk_free_after_bytes"], 900)
        for metric in ("rss_sample_count", "process_cpu_sample_count", "disk_sample_count"):
            self.assertEqual(resources[metric], 2)

    def test_missing_rss_preserves_cpu_and_disk(self):
        with patch.object(BENCHMARK, "rss_bytes", return_value=None):
            report, _ = self.run_benchmark()
        resources = report["resource_usage"]
        self.assertEqual(resources["status"], "partial")
        self.assertEqual(resources["rss_sample_count"], 0)
        self.assertIsNone(resources["rss_peak_bytes"])
        self.assertEqual(resources["process_cpu_percent_mean"], 25)
        self.assertGreater(resources["disk_free_min_bytes"], 0)

    def test_measured_zero_is_preserved(self):
        with patch.object(BENCHMARK, "rss_bytes", return_value=0), patch.object(BENCHMARK, "disk_free_bytes", return_value=0):
            report, _ = self.run_benchmark(cpu_times=[0, 0])
        resources = report["resource_usage"]
        self.assertEqual(resources["status"], "complete")
        for metric in ("rss_peak_bytes", "process_cpu_percent_mean", "process_cpu_percent_peak", "disk_free_min_bytes"):
            self.assertEqual(resources[metric], 0)
        for metric in ("rss_sample_count", "process_cpu_sample_count", "disk_sample_count"):
            self.assertEqual(resources[metric], 1)

    def test_disk_oserror_preserves_rss_and_cpu(self):
        with patch.object(resource_monitor.shutil, "disk_usage", side_effect=OSError("unavailable")):
            report, _ = self.run_benchmark()
        resources = report["resource_usage"]
        self.assertEqual(resources["status"], "partial")
        self.assertIsNone(resources["disk_free_min_bytes"])
        self.assertEqual(resources["disk_sample_count"], 0)
        self.assertGreater(resources["rss_peak_bytes"], 0)
        self.assertEqual(resources["process_cpu_percent_mean"], 25)

    def test_missing_endpoint_disk_observations_are_not_replaced(self):
        with patch.object(BENCHMARK, "disk_free_bytes", side_effect=[None, 900, None]):
            report, _ = self.run_benchmark(ticks=3)
        resources = report["resource_usage"]
        self.assertEqual(resources["status"], "partial")
        self.assertEqual(resources["disk_sample_count"], 1)
        self.assertEqual(resources["disk_free_min_bytes"], 900)
        self.assertIsNone(resources["disk_free_before_bytes"])
        self.assertIsNone(resources["disk_free_after_bytes"])

    def test_unexpected_sampler_failure_is_explicit_and_redacted(self):
        with patch.object(BENCHMARK, "rss_bytes", side_effect=ValueError("UNSAVED private details")):
            report, _ = self.run_benchmark()
        resources = report["resource_usage"]
        self.assertEqual(resources["status"], "error")
        self.assertEqual(resources["sampler_error"], "ValueError")
        self.assertEqual(resources["sample_count"], 0)
        self.assertIsNone(resources["rss_peak_bytes"])
        self.assertIsNone(resources["process_cpu_percent_mean"])

    def test_sampler_failure_after_valid_sample_is_not_complete(self):
        with patch.object(BENCHMARK, "rss_bytes", side_effect=[123, RuntimeError("failed")]):
            report, _ = self.run_benchmark(ticks=2)
        resources = report["resource_usage"]
        self.assertEqual(resources["status"], "error")
        self.assertEqual(resources["sampler_error"], "RuntimeError")
        self.assertEqual(resources["sample_count"], 1)
        self.assertEqual(resources["rss_peak_bytes"], 123)

    def test_resource_success_does_not_mask_inference_failure(self):
        report, code = self.run_benchmark(model_error=RuntimeError("synthetic model failure"))
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["resource_usage"]["status"], "complete")


if __name__ == "__main__":
    unittest.main()
