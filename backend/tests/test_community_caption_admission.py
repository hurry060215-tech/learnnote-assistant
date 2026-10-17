"""Real current-page admission and caption completion retain exact part identity."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class CommunityCaptionAdmissionTests(unittest.TestCase):
    def test_admitted_caption_completion_preserves_community_source_boundary(self):
        if os.environ.get("LEARNNOTE_COMMUNITY_CAPTION_WORKER") != "1":
            with tempfile.TemporaryDirectory() as directory:
                env = {**os.environ, "LEARNNOTE_DATA_DIR": directory,
                       "LEARNNOTE_COMMUNITY_CAPTION_WORKER": "1", "PYTHONPATH": "backend"}
                code = """import runpy, unittest
scope = runpy.run_path('scripts/test-backend-offline.py')
with scope['offline_network']():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName(
        'backend.tests.test_community_caption_admission.CommunityCaptionAdmissionTests'))
raise SystemExit(not result.wasSuccessful())
"""
                result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2],
                                        env=env, text=True, capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue((Path(directory) / "library.sqlite3").is_file())
            return
        from fastapi.testclient import TestClient
        from app import community, main, storage
        from app.models import SourceIdentity
        from app.processor import process_current_page_task
        url = "https://www.bilibili.com/video/BV1xx411c7mD?p=2"
        with TestClient(main.app) as client:
            community.set_community_enabled(True)
            for mode in ("video", "subtitle_only"):
                with self.subTest(mode=mode), patch("app.main.schedule_processing") as schedule, \
                     patch("app.processor.MediaDownloader") as download, \
                     patch("app.processor.maybe_download_page_subtitle", return_value=None) as fetch, \
                     patch("app.processor.transcribe_audio") as asr, \
                     patch("app.processor.transcribe_audio_openai_compatible") as remote_asr, \
                     patch("app.processor.summarize_with_diagnostics") as model:
                    download.return_value.attempts = []
                    download.return_value.resolved_title = ""
                    response = client.post("/api/tasks/from-current-page", json={
                        "page_url": url, "title": "Synthetic caption source", "mode": mode,
                        "handoff_id": "community-caption-" + mode,
                        "active_video": {"duration": 120, "current_time": 20},
                        "browser_subtitles": [{"start": i * 10, "end": (i + 1) * 10,
                            "text": "Synthetic lesson evidence with a complete explanatory sentence."} for i in range(12)],
                        "options": {"content_mode": "subtitles", "visual_understanding": False},
                    })
                    self.assertEqual(response.status_code, 200, response.text)
                    task_id = response.json()["task_id"]
                    schedule.assert_called_once()
                    self.assertIs(schedule.call_args.args[1], process_current_page_task)
                    process_current_page_task(task_id, schedule.call_args.args[3])
                    task = storage.get_task(task_id)
                    self.assertEqual((task.status, task.mode, task.summary_source), ("success", "subtitle_only", "subtitle-extract"), task.error_detail)
                    self.assertEqual(task.source_identity.page_url, url)
                    before = Path(task.transcript_path).read_bytes()
                    endpoint = f"/api/tasks/{task_id}/community-context"
                    body = {"page_url": url + "&tracking=discard", "items": [{"kind": "comment", "text": "Audience question distinct from the lesson."}]}
                    preview = client.post(endpoint + "/preview", json=body)
                    self.assertEqual(preview.status_code, 200, preview.text)
                    reviewed = preview.json()
                    self.assertEqual(reviewed["source_uri"], url)
                    for changed in (url.replace("p=2", "p=1"), url.replace("BV1xx411c7mD", "BV1xx411c7mE")):
                        self.assertEqual(client.post(endpoint + "/preview", json={**body, "page_url": changed}).status_code, 409)
                    saved = client.post(endpoint + "/save", json={"preview_id": reviewed["preview_id"],
                        "fingerprint": reviewed["fingerprint"], "selected_item_ids": [reviewed["items"][0]["item_id"]]})
                    self.assertEqual(saved.status_code, 200, saved.text)
                    self.assertEqual(Path(task.transcript_path).read_bytes(), before)
                    self.assertNotIn("Audience question", json.dumps(storage.get_task(task_id).model_dump(mode="json")))
                    # A subtitle mode alone does not establish browser provenance.
                    for changes in ({"source_type": "local"}, {"source_type": "page_text"},
                                    {"source_identity": SourceIdentity()},
                                    {"source_identity": task.source_identity.model_copy(update={"page_url": url.replace("p=2", "p=3")})}):
                        storage.update_task(task_id, **changes)
                        self.assertEqual(client.post(endpoint + "/preview", json=body).status_code, 409)
                        storage.update_task(task_id, source_type=task.source_type, source_identity=task.source_identity)
                    download.return_value.download.assert_not_called()
                    download.return_value.download_resource.assert_not_called()
                    if mode == "subtitle_only":
                        fetch.assert_not_called()
                    for forbidden in (asr, remote_asr, model):
                        forbidden.assert_not_called()
