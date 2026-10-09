"""Create only synthetic evidence for the actual Windows Edge acceptance run."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build" / "personal-anchors-acceptance"
DATA = OUTPUT / "data"
os.environ["LEARNNOTE_DATA_DIR"] = str(DATA)
os.environ["ORT_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
sys.path.insert(0, str(ROOT / "backend"))

from app.claims import build_claim_evidence_map
from app.models import TranscriptResult
from app.storage import atomic_write_text, create_task, task_dir, update_task, write_json


def main():
    # This dedicated synthetic backend must not contact release/model services.
    atomic_write_text(DATA / "config/update-preferences.json", json.dumps({"auto_check": False, "auto_download": False}))
    task = create_task("local", "个人批注来源验收 Synthetic")
    root = task_dir(task.id)
    note = "# Synthetic annotation acceptance\n\nAn exact generated claim.\n"
    transcript = {"segments": [{"start": 1, "end": 5, "text": "First overlapping caption."},
                               {"start": 3, "end": 7, "text": "Second overlapping caption."}]}
    grid = root / "grids" / "synthetic.png"
    grid.parent.mkdir(parents=True, exist_ok=True)
    grid.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf1sAAAAASUVORK5CYII="))
    windows = [{"id": "synthetic-window", "index": 0, "start": 1, "end": 7, "frame_count": 1,
                "summary": "Synthetic frame.", "grid_path": str(grid), "grid_url": f"/api/tasks/{task.id}/assets/synthetic.png"}]
    note_path = root / "note.md"
    atomic_write_text(note_path, note)
    transcript_path = write_json(task.id, "transcript.json", transcript)
    visual_path = write_json(task.id, "visual_index.json", {"windows": windows})
    write_json(task.id, "claim_evidence_map.json", build_claim_evidence_map(task.id, task.title, note, TranscriptResult.model_validate(transcript), windows))
    update_task(task.id, status="success", phase="completed", progress=100, summary_source="llm",
                note_path=str(note_path), transcript_path=str(transcript_path), visual_index_path=str(visual_path))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fixture = {"synthetic": True, "task_id": task.id, "data_dir": str(DATA), "note_path": str(note_path), "grid_path": str(grid)}
    (OUTPUT / "fixture.json").write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    print(json.dumps(fixture))


if __name__ == "__main__":
    main()
