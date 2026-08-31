from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import TaskRecord


class LearningExperienceApiTests(unittest.TestCase):
    def test_material_export_dashboard_and_opt_in_community_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            tasks = root / "tasks"
            task_path = tasks / "learning-api"
            task_path.mkdir(parents=True)
            note = task_path / "note.md"
            note.write_text("# API 课程\n\n## 结论\n\n学习率决定更新步长。", encoding="utf-8")
            task = TaskRecord(
                id="learning-api", source_type="local", mode="local", title="API 课程", status="success",
                note_path=str(note), created_at="2026-08-31T00:00:00+00:00", updated_at="2026-08-31T00:00:00+00:00",
            )
            (task_path / "task.json").write_text(task.model_dump_json(indent=2), encoding="utf-8")
            for target, value in (
                ("app.storage.TASK_DIR", tasks),
                ("app.library.TASK_DIR", tasks),
                ("app.library.DATA_DIR", root),
                ("app.library.TEMP_DIR", root / "temp"),
                ("app.knowledge.DATA_DIR", root),
                ("app.study.DATA_DIR", root),
                ("app.community.DATA_DIR", root),
            ):
                stack.enter_context(patch(target, value))

            client = TestClient(app)
            imported = client.post(
                "/api/library/materials/import",
                files={"file": ("lesson.md", "# 本地资料\n\n可追溯学习内容。".encode("utf-8"), "text/markdown")},
            )
            self.assertEqual(imported.status_code, 200)
            material_id = imported.json()["material"]["material_id"]
            evidence_id = imported.json()["material"]["evidence_ids"][0]
            self.assertEqual(client.get(f"/api/library/materials/{material_id}/anchors").status_code, 200)

            rejected = client.post("/api/study/cards", json={"cards": [{"front": "问题", "back": "答案", "source_evidence_ids": ["not-canonical"]}]})
            self.assertEqual(rejected.status_code, 422)
            created = client.post("/api/study/cards", json={"cards": [{
                "card_id": "attacker-controlled", "front": "问题", "back": "答案",
                "source_evidence_ids": [evidence_id], "reps": 999, "stability": "Infinity",
            }]})
            self.assertEqual(created.status_code, 200)
            card = created.json()["cards"][0]
            self.assertNotEqual(card["card_id"], "attacker-controlled")
            self.assertEqual(card["reps"], 0)
            self.assertEqual(card["stability"], 1.0)
            dashboard = client.get("/api/study/dashboard").json()
            self.assertTrue(all("back" not in item for item in dashboard["due_cards"]))

            docx = client.get("/api/tasks/learning-api/exports/docx")
            pdf = client.get("/api/tasks/learning-api/exports/pdf")
            self.assertEqual(docx.status_code, 200)
            self.assertTrue(docx.content.startswith(b"PK"))
            self.assertEqual(pdf.status_code, 200)
            self.assertTrue(pdf.content.startswith(b"%PDF"))
            self.assertEqual(client.get("/api/study/dashboard").status_code, 200)

            blocked = client.post(
                "/api/tasks/learning-api/community-context",
                json={"items": [{"kind": "comment", "text": "独立观点"}]},
            )
            self.assertEqual(blocked.status_code, 409)
            self.assertEqual(client.put("/api/study/community/settings", json={"enabled": True}).status_code, 200)
            stored = client.post(
                "/api/tasks/learning-api/community-context",
                json={"items": [{"kind": "comment", "text": "独立观点"}]},
            )
            self.assertEqual(stored.status_code, 200)
            self.assertFalse(stored.json()["evidence_eligible"])


if __name__ == "__main__":
    unittest.main()
