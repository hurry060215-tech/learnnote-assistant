"""Optional model-library contracts using synthetic local files only."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import local_models


@unittest.skipUnless(importlib.util.find_spec("tokenizers"), "optional tokenizer runtime")
class TokenizerContracts(unittest.TestCase):
    def test_local_round_trip_and_truncation_overflow(self):
        from tokenizers import Tokenizer, models, pre_tokenizers

        tokenizer = Tokenizer(models.WordLevel(
            {"[UNK]": 0, "alpha": 1, "beta": 2, "gamma": 3}, unk_token="[UNK]"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        tokenizer.enable_truncation(max_length=2, stride=1)
        encoded = tokenizer.encode("alpha beta gamma")
        self.assertEqual(encoded.ids, [1, 2])
        self.assertEqual([part.ids for part in encoded.overflowing], [[2, 3]])
        self.assertEqual(tokenizer.decode(encoded.ids), "alpha beta")
        restored = Tokenizer.from_str(tokenizer.to_str())
        self.assertEqual(restored.encode("beta gamma").ids, [2, 3])


@unittest.skipUnless(importlib.util.find_spec("faster_whisper"), "optional ASR runtime")
class ModelPreparationContracts(unittest.TestCase):
    def test_real_download_helper_reuses_local_files_without_requesting_hub(self):
        import huggingface_hub
        from faster_whisper.utils import download_model

        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "faster-whisper-tiny"
            folder.mkdir()
            original = {"config.json": b"{}", "model.bin": b"synthetic-not-a-model",
                        "tokenizer.json": b"{}"}
            for name, data in original.items():
                (folder / name).write_bytes(data)
            with patch.object(huggingface_hub.HfApi, "repo_info",
                              side_effect=AssertionError("Local reuse must not request Hub metadata")) as request:
                result = download_model("tiny", output_dir=str(folder),
                                        cache_dir=str(Path(root) / "hub"), local_files_only=True)
            self.assertEqual(Path(result), folder)
            request.assert_not_called()
            self.assertEqual({name: (folder / name).read_bytes() for name in original}, original)


class SharedModelCacheContracts(unittest.TestCase):
    def test_shared_blob_snapshot_is_ready_without_rewriting_or_downloading(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Path(root)
            hub = cache / "huggingface" / "hub"
            repository = hub / "models--Systran--faster-whisper-small"
            revision = "a" * 40
            snapshot = repository / "snapshots" / revision
            snapshot.mkdir(parents=True)
            (repository / "refs").mkdir()
            (repository / "refs" / "main").write_text(revision)
            (repository / "blobs").mkdir()
            (hub / "blobs").mkdir()
            originals = {}
            for index, name in enumerate(("config.json", "model.bin", "tokenizer.json")):
                blob = hub / "blobs" / str(index)
                originals[blob] = f"synthetic payload {index}".encode()
                blob.write_bytes(originals[blob])
                repository_blob = repository / "blobs" / str(index)
                try:
                    repository_blob.symlink_to(blob)
                    (snapshot / name).symlink_to(repository_blob)
                except OSError as exc:
                    self.skipTest(f"Host does not support unprivileged symlinks: {type(exc).__name__}")
            with patch.object(local_models, "MODEL_CACHE_DIR", cache), \
                 patch.object(local_models, "_states", {}), \
                 patch.object(local_models.threading, "Thread") as worker:
                self.assertEqual(local_models.prepare_model("small")["status"], "ready")
                worker.assert_not_called()
                self.assertEqual({path: path.read_bytes() for path in originals}, originals)
                (hub / "blobs" / "1").write_bytes(b"")
                self.assertEqual(local_models.model_status("small")["status"], "not_downloaded")
