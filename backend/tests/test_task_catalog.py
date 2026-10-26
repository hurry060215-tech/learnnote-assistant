"""Production library reads must not perform per-task media or evidence work."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import main, storage
from app.models import TaskRecord
from app.task_catalog import task_catalog_entry


class TaskCatalogTests(unittest.TestCase):
    def test_whitelist_omits_credentials_content_and_private_artifact_paths(self):
        record = TaskRecord(id="catalog-task", source_type="local", title="Synthetic",
                            created_at="2026-10-23", updated_at="2026-10-23",
                            note_path="private-source.md", browser_subtitles=[{"text": "private transcript", "start": 0, "end": 1}],
                            page_url="https://example.test/lesson?token=secret")
        entry = task_catalog_entry(record)
        self.assertEqual(entry["id"], record.id)
        self.assertTrue(entry["catalog"])
        self.assertEqual(set(entry), {"id", "source_task_id", "title", "source_type", "mode", "status", "summary_source",
                                    "created_at", "updated_at", "awaiting_confirmation", "control_generation", "catalog"})
        self.assertNotIn("private", str(entry))
        self.assertNotIn("secret", str(entry))

    def test_catalog_is_one_manifest_pass_without_artifact_reads_or_state_writes(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            tasks = Path(temporary) / "tasks"
            paths = []
            for i in range(3):
                record = TaskRecord(id=f"catalog-{i}", source_type="local", title="Synthetic",
                                    status="queued", created_at="2020-01-01", updated_at="2020-01-01")
                path = tasks / record.id / "task.json"
                path.parent.mkdir(parents=True)
                path.write_text(record.model_dump_json(), encoding="utf-8")
                paths.append(path)
            before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
            stack.enter_context(patch.object(storage, "TASK_DIR", tasks))
            read = stack.enter_context(patch.object(storage, "get_task", wraps=storage.get_task))
            stack.enter_context(patch.object(main, "task_payload", side_effect=AssertionError("full projection")))
            stack.enter_context(patch.object(main, "read_transcript", side_effect=AssertionError("transcript read")))
            stack.enter_context(patch.object(storage, "task_state_transaction", side_effect=AssertionError("write lock")))
            result = main.api_task_catalog()
            self.assertEqual(result["total"], 3)
            self.assertEqual(read.call_count, 3)
            self.assertTrue(all(item["status"] == "queued" for item in result["tasks"]))
            self.assertEqual(before, [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths])

    def test_catalog_route_precedes_dynamic_task_route_and_keeps_detail_contract(self):
        paths = [route.path for route in main.app.routes if hasattr(route, "path")]
        self.assertLess(paths.index("/api/tasks/catalog"), paths.index("/api/tasks/{task_id}"))
        self.assertIn("/api/tasks", paths)


if __name__ == "__main__":
    unittest.main()
