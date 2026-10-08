import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import local_models

class LocalModelTests(unittest.TestCase):
    def test_missing_files_invalidate_success_state_and_allow_reprepare(self):
        with tempfile.TemporaryDirectory() as root, patch.object(local_models, "MODEL_CACHE_DIR", Path(root)), patch.object(local_models, "_states", {"tiny": {"status": "ready"}}), patch.object(local_models.threading, "Thread") as thread:
            self.assertEqual(local_models.model_status("tiny")["status"], "not_downloaded")
            self.assertEqual(local_models.prepare_model("tiny")["status"], "downloading")
            thread.return_value.start.assert_called_once()

    def test_damaged_cache_reference_is_recoverable_without_network(self):
        with tempfile.TemporaryDirectory() as root, patch.object(local_models, "MODEL_CACHE_DIR", Path(root)), patch.object(local_models, "_states", {}), patch.object(local_models.threading, "Thread") as thread:
            hub = Path(root) / "huggingface/hub/models--Systran--faster-whisper-small"
            (hub / "refs").mkdir(parents=True)
            (hub / "refs/main").write_bytes(b"\xff")
            self.assertEqual(local_models.model_status("small")["status"], "not_downloaded")
            thread.assert_not_called()

    def test_existing_whisper_hub_cache_does_not_download_again(self):
        with tempfile.TemporaryDirectory() as root, patch.object(local_models, "MODEL_CACHE_DIR", Path(root)), patch.object(local_models, "_states", {}), patch.object(local_models.threading,"Thread") as thread:
            hub=Path(root)/"huggingface/hub/models--Systran--faster-whisper-small"
            (hub/"refs").mkdir(parents=True); (hub/"refs/main").write_text("a"*40)
            folder=hub/"snapshots"/("a"*40);folder.mkdir(parents=True)
            for name in ("config.json", "model.bin", "tokenizer.json"): (folder/name).write_text("test")
            self.assertEqual(local_models.prepare_model("small")["status"],"ready")
            thread.assert_not_called()

    def test_status_never_downloads_and_rejects_arbitrary_paths(self):
        with tempfile.TemporaryDirectory() as root, patch.object(local_models, "MODEL_CACHE_DIR", Path(root)), patch.object(local_models, "_states", {}):
            self.assertEqual(local_models.model_status("small")["status"], "not_downloaded")
            with self.assertRaises(ValueError): local_models.prepare_model("../../anything")
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_ready_requires_complete_files(self):
        with tempfile.TemporaryDirectory() as root, patch.object(local_models, "MODEL_CACHE_DIR", Path(root)), patch.object(local_models, "_states", {}):
            folder=Path(root)/"faster-whisper-small"; folder.mkdir()
            for name in ("config.json", "model.bin", "tokenizer.json"): (folder/name).write_text("test")
            self.assertEqual(local_models.model_status("small")["status"], "ready")
            (folder/"model.bin").write_text("")
            self.assertEqual(local_models.model_status("small")["status"], "not_downloaded")
