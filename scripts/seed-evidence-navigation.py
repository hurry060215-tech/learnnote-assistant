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
    output.writeframes(b"\0\0" * 16000 * 21)
note, transcript = root / "note.md", root / "transcript.json"
note_text = "# Synthetic source navigation\n\nFirst window at 0 seconds; second window at 10 seconds."
if "--source-review" in sys.argv:
    note_text = "# 合成来源核对笔记\n\n## 正文\n\n" + "\n\n".join(
        f"**【待核对：仅定位到来源】** 第{i + 1}条合成表述，需核对出处。[00:12]"
        for i in range(40))
    note_text += "\n\n**【待核对：未找到支持来源】** 缺少证据的数字。\n\n**【推断：需回源核对】** 合成推断。"
    note_text += "\n\n`**【待核对：仅定位到来源】**` 是代码示例。"
note.write_text(note_text, encoding="utf-8")
transcript.write_text(json.dumps({"full_text": "First window. Second window.", "segments": [
    {"start": 0, "end": 10, "text": "First synthetic window."}, {"start": 10, "end": 20, "text": "Second synthetic window."},
]}), encoding="utf-8")
record = TaskRecord(id=task_id, title="Synthetic source navigation", source_type="local", mode="local", status="success",
                    phase="completed", note_path=str(note), transcript_path=str(transcript), media_path=str(media),
                    frame_grids=grids, visual_windows=windows, created_at=now_iso(), updated_at=now_iso())
save_task(record)
evidence = add_evidence(SourceEvidence(evidence_id=f"{task_id}-window-evidence", task_id=task_id, source_type="video",
                                      title=record.title, locator="10-20s", text="Second synthetic window.",
                                      metadata={"kind": "transcript", "start": 10, "end": 20, "window_id": "window-2"}))
card = save_cards([StudyCard(front="Which synthetic window?", back="The second window.", source_evidence_ids=[evidence.evidence_id])])[0]
print(json.dumps({"task_id": task_id, "evidence_id": evidence.evidence_id, "card_id": card.card_id}))
