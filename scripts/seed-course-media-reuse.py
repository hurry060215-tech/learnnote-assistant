"""Seed synthetic shared course evidence in an isolated build data root only."""
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
data = Path(os.environ.get("LEARNNOTE_DATA_DIR", "")).resolve()
if not os.environ.get("LEARNNOTE_DATA_DIR") or not data.is_relative_to(ROOT / "build"):
    raise SystemExit("Course fixtures require an isolated checkout build data directory")
sys.path.insert(0, str(ROOT / "backend"))

from app import course_episodes, courses, storage
from app.models import SourceIdentity, TaskOptions

url = f"https://example.test/synthetic-course-{uuid4().hex}.mp4"
source = [{"kind": "url", "url": url}]
owner = courses.save_course("Synthetic shared evidence owner", source)
legacy = courses.save_course("Synthetic legacy unbound course", source)
episode = course_episodes.course_episodes(owner)[0]
task = storage.create_task("current_page", "Synthetic shared course evidence", page_url=url,
                           handoff_id=episode["handoff_id"], source_identity=SourceIdentity(page_url=url),
                           options=TaskOptions(content_mode="text"))
root = storage.task_dir(task.id)
transcript, note = root / "transcript.json", root / "note.md"
transcript.write_text(json.dumps({"full_text": "Synthetic shared evidence remains stable.", "segments": [
    {"start": 0, "end": 10, "text": "Synthetic shared evidence remains stable."}]}), encoding="utf-8")
note.write_text("# Synthetic shared course evidence\n\nSynthetic shared evidence remains stable.", encoding="utf-8")
storage.update_task(task.id, status="success", phase="completed", checkpoint="summarized",
                    transcript_path=str(transcript), note_path=str(note))
course_episodes.prepare_course_episode(owner, episode["episode_id"])
print(json.dumps({"task_id": task.id, "url": url, "owner_id": owner["id"], "legacy_id": legacy["id"]}))
