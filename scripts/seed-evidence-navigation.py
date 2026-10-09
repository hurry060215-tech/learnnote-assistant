"""Create synthetic navigation assets only inside this checkout's build folder."""
import json
import os
from pathlib import Path
import sys
from uuid import uuid4
import wave

ROOT = Path(__file__).resolve().parents[1]
data = Path(os.environ.get("LEARNNOTE_DATA_DIR", "")).resolve()
if not os.environ.get("LEARNNOTE_DATA_DIR") or not data.is_relative_to(ROOT / "build"):
    raise SystemExit("Navigation fixtures require an isolated checkout build data directory")
os.environ["ORT_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image, ImageDraw
from app.config import TASK_DIR
from app.claims import build_claim_evidence_map
from app.models import TranscriptResult
from app.knowledge import add_evidence
from app.models import FrameGrid, SourceEvidence, StudyCard, TaskRecord, VisualWindow, now_iso
from app.storage import save_task
from app.study import save_cards

task_id = "navigation-" + uuid4().hex[:12]
root = TASK_DIR / task_id
(root / "grids").mkdir(parents=True)
grids, windows = [], []
for index, color in enumerate(("#a43333", "#3355aa")):
    frame = root / "grids" / f"window-{index}.jpg"
    picture = Image.new("RGB", (480, 240), color)
    ImageDraw.Draw(picture).text((24, 24), f"SYNTHETIC WINDOW {index + 1}", fill="white")
    picture.save(frame)
    url = f"/api/tasks/{task_id}/assets/{frame.name}"
    grids.append(FrameGrid(path=str(frame), url=url, start=index * 10, end=(index + 1) * 10, frame_count=1))
    windows.append(VisualWindow(id=f"window-{index + 1}", index=index, start=index * 10, end=(index + 1) * 10,
                                frame_count=1, grid_url=url, grid_path=str(frame)))
media = root / "synthetic.wav"
with wave.open(str(media), "wb") as output:
    output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
    output.writeframes(b"\0\0" * 16000 * 31)
note, transcript = root / "note.md", root / "transcript.json"
note_text = "# Synthetic source navigation 🧪\n\nFirst synthetic window.\n\nSecond synthetic window.\n\nFirst synthetic window.\n\nSecond synthetic window may imply an unverified conclusion [00:10 – 00:14].\n"
note.write_text(note_text, encoding="utf-8")
segments = [
    {"start": 0, "end": 3, "text": "First synthetic window."},
    {"start": 10, "end": 14, "text": "Second synthetic window."},
    {"start": 20, "end": 23, "text": "First synthetic window."},
] + [{"start": 25 + index * .025, "end": 25 + (index + 1) * .025, "text": f"Synthetic caption {index}."} for index in range(200)]
transcript_data = {"full_text": "First window. Second window.", "segments": segments}
transcript.write_text(json.dumps(transcript_data), encoding="utf-8")
claim_map = build_claim_evidence_map(task_id, "Synthetic source navigation", note_text,
    TranscriptResult.model_validate(transcript_data), windows)
(root / "claim_evidence_map.json").write_text(json.dumps(claim_map), encoding="utf-8")
(root / "qa_history.json").write_text(json.dumps({"schema_version": 1, "items": [{
    "id": "synthetic-question", "created_at": now_iso(), "question": "Which source window?",
    "answer": "Check the second synthetic window.", "source": "local", "citations": [{
        "source": "transcript", "source_kind": "task", "source_id": task_id, "window_id": "window-2",
        "start": 10, "end": 14, "label": "Synthetic citation", "text": "Second synthetic window.",
    }],
}]}), encoding="utf-8")
record = TaskRecord(id=task_id, title="Synthetic source navigation", source_type="local", mode="local", status="success",
                    phase="completed", note_path=str(note), transcript_path=str(transcript), media_path=str(media),
                    frame_grids=grids, visual_windows=windows, created_at=now_iso(), updated_at=now_iso())
save_task(record)
evidence = add_evidence(SourceEvidence(evidence_id=f"{task_id}-window-evidence", task_id=task_id, source_type="video",
                                      title=record.title, locator="10-20s", text="Second synthetic window.",
                                      metadata={"kind": "transcript", "start": 10, "end": 20, "window_id": "window-2"}))
card = save_cards([StudyCard(front="Which synthetic window?", back="The second window.", source_evidence_ids=[evidence.evidence_id])])[0]
# Same canonical source structure without a local player exercises subtitle-only fallback.
no_media_id = "navigation-subtitles-" + uuid4().hex[:12]
no_media_root = TASK_DIR / no_media_id
no_media_root.mkdir()
(no_media_root / "note.md").write_text(note_text, encoding="utf-8")
(no_media_root / "transcript.json").write_text(json.dumps(transcript_data), encoding="utf-8")
no_media_map = build_claim_evidence_map(no_media_id, "Synthetic subtitles", note_text, TranscriptResult.model_validate(transcript_data))
(no_media_root / "claim_evidence_map.json").write_text(json.dumps(no_media_map), encoding="utf-8")
save_task(TaskRecord(id=no_media_id, title="Synthetic subtitles", source_type="local", mode="local", status="success",
    phase="completed", note_path=str(no_media_root / "note.md"), transcript_path=str(no_media_root / "transcript.json"),
    created_at=now_iso(), updated_at=now_iso()))
print(json.dumps({"task_id": task_id, "evidence_id": evidence.evidence_id, "card_id": card.card_id,
    "claim_ids": [claim["claim_id"] for claim in claim_map["claims"]], "subtitle_task_id": no_media_id,
    "subtitle_claim_ids": [claim["claim_id"] for claim in no_media_map["claims"]]}))
