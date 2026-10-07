from __future__ import annotations

from contextlib import ExitStack
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class LearningBackupFlowTests(unittest.TestCase):
    def _bind_source_data(self, stack: ExitStack, root: Path) -> None:
        tasks = root / "tasks"
        for target, value in (
            ("app.storage.DATA_DIR", root),
            ("app.storage.TASK_DIR", tasks),
            ("app.library.DATA_DIR", root),
            ("app.library.TASK_DIR", tasks),
            ("app.library.TEMP_DIR", root / "temp"),
            ("app.knowledge.DATA_DIR", root),
            ("app.study.DATA_DIR", root),
            ("app.personal_notes.DATA_DIR", root),
            ("app.routers.notes.DATA_DIR", root),
            ("app.routers.library.DATA_DIR", root),
            ("app.routers.library.TEMP_DIR", root / "temp"),
        ):
            stack.enter_context(patch(target, value))

    def test_read_answer_source_review_regenerate_and_merge_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            source_data = root / "source"
            source_data.mkdir()
            self._bind_source_data(stack, source_data)
            client = TestClient(app)

            source_bytes = (
                "# Optimization\n\n## Update rule\n\nLearning rate controls each parameter update step and can change the convergence speed."
                .encode("utf-8")
            )
            imported = client.post(
                "/api/library/materials/import",
                files={"file": (
                    "optimization.md",
                    source_bytes,
                    "text/markdown",
                )},
            )
            self.assertEqual(imported.status_code, 200, imported.text)
            material = imported.json()["material"]
            material_id = material["material_id"]
            anchors = client.get(f"/api/library/materials/{material_id}/anchors").json()["anchors"]
            evidence_id = next(item["evidence_id"] for item in anchors if "Learning rate controls" in item["text"])
            reading = client.get(f"/api/library/materials/{material_id}/content")
            self.assertEqual(reading.status_code, 200, reading.text)
            self.assertIn("Learning rate controls", reading.json()["text"])

            plan = client.put("/api/study/plan", json={"title": "Local review", "daily_target": 3, "paused": False, "timezone": "Asia/Shanghai"})
            self.assertEqual(plan.status_code, 200, plan.text)
            proposals = client.post("/api/study/proposals", json={"evidence_ids": [evidence_id], "limit": 5})
            self.assertEqual(proposals.status_code, 200, proposals.text)
            proposal_items = proposals.json()["proposals"]
            self.assertTrue(proposal_items, f"material={material} proposal_response={proposals.json()}")
            proposal = proposal_items[0]
            created = client.post("/api/study/cards", json={"cards": [proposal]})
            self.assertEqual(created.status_code, 200, created.text)
            card_id = created.json()["cards"][0]["card_id"]
            dashboard_before = client.get("/api/study/dashboard").json()
            quiz = next(item for item in dashboard_before["quiz_queue"] if item["quiz_id"] == f"card-{card_id}")
            self.assertFalse(quiz["answer_included"])
            self.assertEqual(quiz["source_evidence_ids"], [evidence_id])

            source = client.get(f"/api/knowledge/evidence/{evidence_id}")
            self.assertEqual(source.status_code, 200, source.text)
            self.assertIn("Learning rate controls", source.json()["evidence"]["text"])
            self.assertEqual(client.post("/api/study/activity", json={"kind": "answer", "source_id": f"card:{card_id}"}).status_code, 200)
            self.assertEqual(client.post("/api/study/activity", json={"kind": "self_assessment", "source_id": f"card:{card_id}"}).status_code, 200)
            reviewed = client.post(f"/api/study/cards/{card_id}/review", json={"rating": 1, "idempotency_key": "lesson-mistake-once"})
            self.assertEqual(reviewed.status_code, 200, reviewed.text)
            dashboard_after = client.get("/api/study/dashboard").json()
            self.assertTrue(any(item["card_id"] == card_id for item in dashboard_after["mistakes"]))

            edition = client.get(f"/api/tasks/editions/material/{material_id}")
            self.assertEqual(edition.status_code, 200, edition.text)
            changed_edition = edition.json()["text"] + "\n\n## My correction\nKeep the source wording available for review."
            saved_edition = client.put(
                f"/api/tasks/editions/material/{material_id}",
                json={"text": changed_edition, "revision": edition.json()["revision"]},
            )
            self.assertEqual(saved_edition.status_code, 200, saved_edition.text)
            annotation = client.post(
                f"/api/personal/material/{material_id}",
                json={
                    "text": "My personal correction stays separate from generated notes.",
                    "quote": "Learning rate controls each parameter update step",
                    "anchor": {"source_revision": saved_edition.json()["revision"], "selected_text": "Learning rate controls each parameter update step"},
                },
            )
            self.assertEqual(annotation.status_code, 200, annotation.text)

            regenerated = client.post(
                "/api/library/materials/import",
                files={"file": ("optimization.md", source_bytes, "text/markdown")},
            )
            self.assertEqual(regenerated.status_code, 200, regenerated.text)
            regenerated_material_id = regenerated.json()["material"]["material_id"]
            self.assertEqual(regenerated_material_id, material_id)
            self.assertEqual(
                client.get(f"/api/personal/material/{regenerated_material_id}").json()["annotations"][0]["text"],
                "My personal correction stays separate from generated notes.",
            )

            backup = client.get("/api/study/backup")
            self.assertEqual(backup.status_code, 200, backup.text)
            payload = backup.json()
            self.assertEqual(payload["study"]["plan"]["timezone"], "Asia/Shanghai")
            self.assertEqual(len(payload["study"]["reviews"]), 1)
            self.assertEqual(len(payload["personal"]["annotations"]), 1)
            self.assertEqual(len(payload["personal"]["editions"]), 1)

            restored_data = root / "restored"
            restored_data.mkdir(parents=True)
            for target in ("app.study.DATA_DIR", "app.personal_notes.DATA_DIR", "app.routers.notes.DATA_DIR"):
                stack.enter_context(patch(target, restored_data))
            restored = client.post("/api/study/backup/restore", json=payload)
            self.assertEqual(restored.status_code, 200, restored.text)
            self.assertEqual(restored.json()["merge"]["restored_reviews"], 1)
            self.assertEqual(restored.json()["merge"]["restored_annotations"], 1)
            self.assertEqual(restored.json()["merge"]["restored_editions"], 1)
            self.assertEqual(client.get("/api/study/plan").json()["plan"]["timezone"], "Asia/Shanghai")
            self.assertEqual(len(client.get(f"/api/study/reviews?card_id={card_id}").json()["reviews"]), 1)
            restored_note = client.get(f"/api/tasks/editions/material/{material_id}")
            self.assertIn("My correction", restored_note.json()["text"])
            restored_annotations = client.get(f"/api/personal/material/{material_id}").json()["annotations"]
            self.assertEqual(restored_annotations[0]["text"], "My personal correction stays separate from generated notes.")
            restored_dashboard = client.get("/api/study/dashboard").json()
            self.assertTrue(any(item["card_id"] == card_id for item in restored_dashboard["mistakes"]))
            self.assertTrue(any(item["answer_count"] and item["self_assessment_count"] for item in restored_dashboard["progress"]["activity"]))

            local_annotation = client.post(
                f"/api/personal/material/{material_id}",
                json={"id": restored_annotations[0]["id"], "text": "A newer local correction.", "quote": restored_annotations[0]["quote"]},
            )
            self.assertEqual(local_annotation.status_code, 200, local_annotation.text)
            current_edition = client.get(f"/api/tasks/editions/material/{material_id}").json()
            local_edition_text = current_edition["text"] + "\n\n## Newer local edit\nKeep this correction too."
            self.assertEqual(client.put(
                f"/api/tasks/editions/material/{material_id}",
                json={"text": local_edition_text, "revision": current_edition["revision"]},
            ).status_code, 200)

            repeated = client.post("/api/study/backup/restore", json=payload)
            self.assertEqual(repeated.status_code, 200, repeated.text)
            self.assertEqual(repeated.json()["merge"]["restored_reviews"], 0)
            self.assertEqual(repeated.json()["merge"]["restored_annotations"], 0)
            self.assertEqual(repeated.json()["merge"]["restored_editions"], 0)
            self.assertEqual(repeated.json()["merge"]["restored_plan"], 0)
            self.assertEqual(client.get(f"/api/personal/material/{material_id}").json()["annotations"][0]["text"], "A newer local correction.")
            self.assertIn("Newer local edit", client.get(f"/api/tasks/editions/material/{material_id}").json()["text"])

            invalid = copy.deepcopy(payload)
            invalid["study"]["algorithm"] = "unknown-fsrs"
            rejected = client.post("/api/study/backup/restore", json=invalid)
            self.assertEqual(rejected.status_code, 422)
            self.assertEqual(len(client.get(f"/api/study/reviews?card_id={card_id}").json()["reviews"]), 1)


if __name__ == "__main__":
    unittest.main()
