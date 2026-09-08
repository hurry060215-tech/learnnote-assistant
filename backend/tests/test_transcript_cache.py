import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from app.models import MediaIntegrity, TaskOptions, TranscriptResult, TranscriptSegment
from app.transcript_cache import load_local_transcript, save_local_transcript


class TranscriptCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch("app.storage.TASK_DIR", self.root)
        self.patch.start()
        self.integrity = MediaIntegrity(sha256="same-media")
        self.options = TaskOptions()
        self.transcript = TranscriptResult(source="faster-whisper", full_text="真实转写内容",
            segments=[TranscriptSegment(start=0, end=10, text="真实转写内容")])

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_reuse_requires_same_source_and_settings(self):
        save_local_transcript("task", self.transcript, self.integrity, self.options)
        self.assertEqual(load_local_transcript("task", self.integrity, self.options), self.transcript)
        for integrity, options in [
            (MediaIntegrity(sha256="other"), self.options),
            (self.integrity, self.options.model_copy(update={"whisper_model": "base"})),
            (self.integrity, self.options.model_copy(update={"transcriber": "openai-compatible"})),
        ]:
            self.assertIsNone(load_local_transcript("task", integrity, options))

    def test_tampered_cache_and_nonlocal_output_are_not_reused(self):
        save_local_transcript("task", self.transcript, self.integrity, self.options)
        (self.root / "task" / "transcript_cache_payload.json").write_text("{}", encoding="utf-8")
        self.assertIsNone(load_local_transcript("task", self.integrity, self.options))
        save_local_transcript("remote", self.transcript.model_copy(update={"source": "remote"}), self.integrity, self.options)
        self.assertIsNone(load_local_transcript("remote", self.integrity, self.options))

    def test_metadata_does_not_persist_model_key(self):
        options = self.options.model_copy(update={"llm_api_key": "private-model-secret"})
        save_local_transcript("task", self.transcript, self.integrity, options)
        self.assertNotIn("private-model-secret", (self.root / "task" / "transcript_cache.json").read_text())

    def test_pipeline_reuses_cache_without_audio_extraction(self):
        from app.transcript_pipeline import prepare_transcript
        from app.text_cleanup import correct_transcript_terms
        integrity = self.integrity.model_copy(update={"status": "ready", "duration": 10})
        from app.transcript_cache import media_cache_integrity
        (self.root / "media.mp4").write_bytes(b"normalized-media")
        integrity = media_cache_integrity(integrity, self.root / "media.mp4")
        save_local_transcript("task", self.transcript, integrity, self.options)
        helpers = {name: Mock(return_value=None) for name in ["parse_subtitle_or_none", "browser_subtitles_are_reliable", "extract_embedded_subtitle", "extract_audio", "transcribe_with_task_progress", "write_browser_subtitles_srt", "use_remote_asr", "calculate_evidence_coverage"]}
        helpers["correct_transcript_terms"] = correct_transcript_terms
        helpers["asr_failure_detail"] = lambda _: ""
        helpers["transcript_from_browser_subtitles"] = lambda _: TranscriptResult()
        with patch("app.transcript_pipeline.update_task"), patch("app.transcript_pipeline.check_cancel"):
            result = prepare_transcript("task", self.root / "media.mp4", self.root / "media.mp4", integrity, self.options, None, [], "", **helpers)
        self.assertEqual(result.transcript.full_text, self.transcript.full_text)
        helpers["extract_audio"].assert_not_called()
        helpers["transcribe_with_task_progress"].assert_not_called()

    def test_corrupt_speech_does_not_create_an_unrecoverable_cache(self):
        damaged = self.transcript.model_copy(update={"full_text": "坏\ufffd\ufffd", "segments": [TranscriptSegment(start=0, end=2, text="坏\ufffd\ufffd")]})
        save_local_transcript("bad", damaged, self.integrity, self.options)
        self.assertIsNone(load_local_transcript("bad", self.integrity, self.options))
