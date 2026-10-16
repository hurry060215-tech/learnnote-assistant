"""Synthetic saved-path exports/admissions never mix original and copied files."""
from contextlib import ExitStack
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from app import main
from app.models import FrameGrid
import test_task_path_portability as portability_fixtures


class TaskExportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = portability_fixtures.TaskPathPortabilityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.task = self.fixture.copied_foreign()
        self.client = self.fixture.client
        self.original = (self.root / "task.json").read_bytes()
        self.prefix = self.task.note_path[:-len("note.md")]
        self.separator = "\\" if "\\" in self.prefix else "/"

    def manifest(self, **changes):
        payload = json.loads(self.original)
        payload.update(changes)
        (self.root / "task.json").write_text(json.dumps(payload), encoding="utf-8")

    def old_file(self, filename, content=b"OLD PRIVATE SYNTHETIC COPY"):
        path = self.fixture.sandbox / "old" / "tasks" / self.task.id / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def no_old_io(self, outside):
        stack = ExitStack()
        for method in ("stat", "lstat", "resolve", "read_bytes", "read_text", "open"):
            original = getattr(Path, method)
            def guarded(path, *args, _original=original, **kwargs):
                if path == outside or outside in path.parents:
                    raise AssertionError("Must reject old-copy ownership before filesystem access")
                return _original(path, *args, **kwargs)
            stack.enter_context(patch.object(Path, method, guarded))
        return stack

    def test_copied_bundle_uses_exact_owned_subtitle_grid_and_reports_without_rewriting(self):
        grid = self.prefix + "grids" + self.separator + "grid_001.jpg"
        reports = {"resource_inventory_path": ("resource_inventory.json", {"candidate_count": 2}),
                   "page_preflight_report_path": ("page_preflight_report.json", {"ready": True})}
        changes = {"frame_grids": [FrameGrid(path=grid, url="/synthetic", start=0, end=5, frame_count=1).model_dump(mode="json")]}
        for field, (name, value) in reports.items():
            (self.root / name).write_text(json.dumps(value), encoding="utf-8")
            changes[field] = self.prefix + name
        self.manifest(**changes)
        before = self.fixture.hashes(self.root)
        result = self.client.get(f"/api/tasks/{self.task.id}/exports/bundle")
        self.assertEqual(result.status_code, 200, result.text)
        with ZipFile(BytesIO(result.content)) as archive:
            self.assertEqual(archive.read("subtitles/browser_subtitles.srt"), (self.root / "browser_subtitles.srt").read_bytes())
            self.assertEqual(archive.read("grids/grid_001.jpg"), (self.root / "grids/grid_001.jpg").read_bytes())
            self.assertEqual(json.loads(archive.read("task.json"))["subtitle_path"], self.task.subtitle_path)
            manifest = json.loads(archive.read("manifest.json"))
            references = [manifest["artifacts"]["subtitles"], *manifest["artifacts"]["grid_entries"],
                          manifest["source"]["resource_inventory"]["export"], manifest["source"]["page_preflight_report"]["export"]]
            for reference in references:
                self.assertIn(reference, archive.namelist())
            for _, (name, value) in reports.items():
                self.assertEqual(json.loads(archive.read(name)), value)
        self.assertEqual(self.fixture.hashes(self.root), before)

    def test_bundle_rejects_old_subtitle_grid_and_reports_without_probing_or_partial_success(self):
        outside = self.old_file("old.srt")
        changes = [{"subtitle_path": str(outside)},
                   {"frame_grids": [FrameGrid(path=str(outside), url="/synthetic", start=0, end=5, frame_count=1).model_dump(mode="json")]},
                   {"resource_inventory_path": str(outside)}, {"page_preflight_report_path": str(outside)}]
        for change in changes:
            with self.subTest(field=next(iter(change))):
                self.manifest(**change)
                before = self.fixture.hashes(self.root)
                with self.no_old_io(outside):
                    result = self.client.get(f"/api/tasks/{self.task.id}/exports/bundle")
                self.assertEqual(result.status_code, 409, result.text)
                self.assertEqual(result.json()["detail"]["code"], "task_artifact_unavailable")
                self.assertEqual(self.fixture.hashes(self.root), before)
        self.assertEqual(outside.read_bytes(), b"OLD PRIVATE SYNTHETIC COPY")

    def test_missing_saved_bundle_attachment_is_recoverable_not_silently_omitted(self):
        (self.root / "browser_subtitles.srt").unlink()
        result = self.client.get(f"/api/tasks/{self.task.id}/exports/bundle")
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(result.json()["detail"]["reason"], "missing_destination")

    def test_optional_missing_reports_remain_empty_but_linked_reports_fail_closed(self):
        self.assertEqual(main.read_resource_inventory(self.task), {})
        self.assertEqual(main.read_page_preflight_report(self.task), {})
        outside = self.old_file("resource_inventory.json", b'{"old":true}')
        link = self.root / "resource_inventory.json"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlink creation unsupported: {exc}")
        with self.no_old_io(outside):
            result = self.client.get(f"/api/tasks/{self.task.id}/exports/bundle")
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(result.json()["detail"]["reason"], "linked_destination")

    def test_retry_summary_rejects_outside_transcript_before_probe_and_preserves_state(self):
        outside = self.old_file("transcript.json", (self.root / "transcript.json").read_bytes())
        self.manifest(transcript_path=str(outside))
        before = self.fixture.hashes(self.root)
        with self.no_old_io(outside), patch("app.main.schedule_processing") as schedule:
            result = self.client.post(f"/api/tasks/{self.task.id}/retry-summary", json={})
        self.assertEqual(result.status_code, 409, result.text)
        self.assertTrue(result.json()["detail"]["requires_preview"])
        schedule.assert_not_called()
        self.assertEqual(self.fixture.hashes(self.root), before)

    def test_explicit_retry_can_use_owned_copied_transcript_without_model_or_source_rewrite(self):
        before = {name: (self.root / name).read_bytes() for name in ("note.md", "transcript.json")}
        with patch("app.summarizer._model_key", return_value="synthetic"), patch("app.main.schedule_processing") as schedule:
            result = self.client.post(f"/api/tasks/{self.task.id}/retry-summary", json={"content_mode": "text"})
        self.assertEqual(result.status_code, 200, result.text)
        schedule.assert_called_once()
        for name, content in before.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertEqual(json.loads((self.root / "task.json").read_text())["transcript_path"], self.task.transcript_path)


if __name__ == "__main__":
    unittest.main()
