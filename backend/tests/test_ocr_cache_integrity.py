import hashlib
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from app.local_ocr import create_ocr_engine, recognize_frames
from app.media import _frame_cache_payload
from app.models import FrameSample
from app.processor_state import TaskCancelled

BOX = [[0, 0], [20, 0], [20, 10], [0, 10]]


class OcrCacheIntegrityTests(unittest.TestCase):
    def test_engine_disables_sdk_telemetry_before_session_creation(self):
        events = []
        runtime = types.SimpleNamespace(disable_telemetry_events=lambda: events.append("disabled"))
        ocr = types.SimpleNamespace(RapidOCR=lambda **kwargs: events.append("created"))
        with patch.dict("sys.modules", {"onnxruntime": runtime, "rapidocr_onnxruntime": ocr}):
            create_ocr_engine()
        self.assertEqual(events, ["disabled", "created"])

    def test_frame_cache_detects_media_changed_with_same_size_and_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.write_bytes(b"first")
            stamp = video.stat()
            first = _frame_cache_payload(video, [(0, ["start"])], interval=10, scene_threshold=.22)
            video.write_bytes(b"other")
            os.utime(video, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            second = _frame_cache_payload(video, [(0, ["start"])], interval=10, scene_threshold=.22)
            self.assertEqual(first["source_size"], second["source_size"])
            self.assertEqual(first["source_mtime_ns"], second["source_mtime_ns"])
            self.assertNotEqual(first["source_sha256"], second["source_sha256"])
            self.assertEqual(second["source_sha256"], hashlib.sha256(b"other").hexdigest())
            self.assertIn("extractor_version", second)

    def test_identical_images_reuse_ocr_but_preserve_each_source_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = []
            for index in range(2):
                path = root / f"{index}.png"
                path.write_bytes(b"identical image")
                samples.append(FrameSample(path=str(path), timestamp=index * 30))
            with patch("builtins.print"):
                calls = []
                def engine(path):
                    calls.append(path)
                    return [[BOX, "学习 rate", .8]], .1
                result = recognize_frames(samples, engine=engine, cache_dir=root / "cache")
            self.assertEqual(len(calls), 1)
            self.assertEqual([frame["timestamp"] for frame in result["frames"]], [0, 30])
            self.assertEqual(result["cache_hits"], 1)
            line = result["frames"][0]["lines"][0]
            self.assertEqual(line["language"], "und-Hani")
            self.assertEqual(line["language_source"], "script_hint")
            self.assertTrue(line["uncertain"])

    def test_tampered_cache_is_rebuilt_and_never_labels_output_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "frame.png"
            image.write_bytes(b"image")
            sample = FrameSample(path=str(image), timestamp=12)
            calls = []
            def engine(path):
                calls.append(path)
                return [[BOX, "original", .95]], .1
            recognize_frames([sample], engine=engine, cache_dir=root / "cache")
            cache = next((root / "cache").glob("*.json"))
            value = json.loads(cache.read_text())
            value["image_sha256"] = "wrong source"
            value["lines"][0]["text"] = "invented"
            cache.write_text(json.dumps(value))
            result = recognize_frames([sample], engine=engine, cache_dir=root / "cache")
            self.assertEqual(len(calls), 2)
            self.assertEqual(result["frames"][0]["lines"][0]["text"], "original")
            value = json.loads(cache.read_text())
            value["lines"][0]["verification"] = "verified"
            cache.write_text(json.dumps(value))
            result = recognize_frames([sample], engine=engine, cache_dir=root / "cache")
            self.assertEqual(result["frames"][0]["lines"][0]["verification"], "unreviewed")

    def test_failed_frame_does_not_discard_other_frames_or_leak_error_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = []
            for index in range(3):
                path = root / f"{index}.png"
                path.write_bytes(bytes([index]))
                samples.append(FrameSample(path=str(path), timestamp=index))
            def engine(path):
                if Path(path).stem == "1":
                    raise RuntimeError("private file path or course text")
                return [[BOX, "usable", .9]], .1
            result = recognize_frames(samples, engine=engine, cache_dir=root / "cache")
            self.assertEqual(result["status"], "partial")
            self.assertEqual(len(result["frames"]), 2)
            self.assertEqual(result["failed_frames"], [{"timestamp": 1.0, "error_type": "RuntimeError"}])
            self.assertNotIn("private file", str(result))
            self.assertEqual(result["remote_calls"], 0)

    def test_cancel_check_propagates_instead_of_becoming_partial_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "frame.png"
            image.write_bytes(b"image")
            def cancel():
                raise TaskCancelled()
            with self.assertRaises(TaskCancelled):
                recognize_frames([FrameSample(path=str(image), timestamp=0)], engine=lambda _: ([], 0), cancel_check=cancel)

    def test_nonfinite_confidence_and_boxes_are_not_persisted(self):
        for output in ([BOX, "text", float("nan")], [[[float("inf"), 0]] * 4, "text", .9]):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                image = root / "frame.png"
                image.write_bytes(b"image")
                result = recognize_frames([FrameSample(path=str(image), timestamp=0)], engine=lambda _: ([output], 0), cache_dir=root / "cache")
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["frames"], [])
                self.assertFalse((root / "cache").exists())


if __name__ == "__main__":
    unittest.main()
