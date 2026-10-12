from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from app import config, library
from app.models import SourceIdentity, TaskRecord


class MaterialRegistrationRaceTests(unittest.TestCase):
    def test_concurrent_same_media_registration_returns_one_material(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            stack.enter_context(patch.multiple(config, DATA_DIR=root, UPLOAD_DIR=root / "uploads",
                TASK_DIR=root / "tasks", STATIC_DIR=root / "static", MODEL_CACHE_DIR=root / "models", TEMP_DIR=root / "temp"))
            stack.enter_context(patch("app.library.DATA_DIR", root))
            stack.enter_context(patch("app.knowledge.DATA_DIR", root))
            media = root / "synthetic.mp4"
            original = b"synthetic registration fixture"
            media.write_bytes(original)
            identity = SourceIdentity(media_sha256=sha256(original).hexdigest())
            tasks = [TaskRecord(id=f"task-{i}", source_type="local", mode="local", title="Shared local video",
                source_media_path=str(media), source_identity=identity, status="success",
                created_at="2026-10-09T00:00:00+00:00", updated_at="2026-10-09T00:00:00+00:00") for i in range(2)]
            barrier = Barrier(2)

            def evidence(task_id, **kwargs):
                barrier.wait(timeout=5)
                return [{"evidence_id": f"{task_id}-cue"}]

            stack.enter_context(patch("app.knowledge.evidence_for_task", side_effect=evidence))
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(library.register_task_material, tasks))
            self.assertEqual(len({item["material_id"] for item in results}), 1)
            self.assertEqual(sorted(item["deduplicated"] for item in results), [False, True])
            stored = library.list_materials()
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]["evidence_ids"], [f"{stored[0]['linked_task_id']}-cue"])
            self.assertEqual(media.read_bytes(), original)

