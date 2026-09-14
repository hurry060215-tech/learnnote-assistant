"""Create a clearly labelled local UI fixture, never in a user's data folder."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ["LEARNNOTE_DATA_DIR"] = str(ROOT / "build" / "ui-polish-data")
sys.path.insert(0, str(ROOT / "backend"))
from app.storage import create_task, update_task, write_json, task_dir
from app.update_service import save_preferences

save_preferences({"auto_check": False, "auto_download": False})
task = create_task("current_page", "阅读验收示例：笔记、来源与复习", "https://example.com/video")
note = task_dir(task.id) / "note.md"
note.write_text("""# 阅读验收示例：笔记、来源与复习

## 核心观点

学习笔记应当保留**重点、解释和原始出处**。先理解内容，再用自己的语言整理；遇到不确定的细节，可以回到字幕核对。

## 操作顺序

1. 选择一段视频或本地资料。
2. 阅读总结，核对 [00:05] 的来源。
3. 写下自己的理解，建立复习卡。

> 这是一份用于界面验收的示例，不是模型生成的研究结论。

### 可读性检查

较短的行距和适度字重让长文更容易浏览，但仍应保留段落之间的区分。

| 操作 | 结果 |
| --- | --- |
| 阅读 | 理解内容 |
| 核对 | 返回来源 |

```python
for item in notes:
    print(item.title)
```
""", encoding="utf-8")
transcript = write_json(task.id, "transcript.json", {"source": "fixture", "full_text": "学习笔记要保留原始出处。先理解，再整理。", "segments": [{"start": 0, "end": 5, "text": "学习笔记要保留原始出处。"}, {"start": 5, "end": 12, "text": "先理解，再整理。"}]})
update_task(task.id, status="success", phase="completed", progress=100, note_path=str(note), transcript_path=str(transcript), summary_source="text-llm")
print(task.id)
