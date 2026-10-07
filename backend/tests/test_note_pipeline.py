from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.models import EvidenceCoverage, MediaIntegrity, TranscriptResult, TranscriptSegment
from app.note_pipeline import finish_note_task


class NotePipelineStructureTests(unittest.TestCase):
    def _run_pipeline(self, summary_source: str, note: str) -> tuple[Path, list[dict], list[str]]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        work = root / "isolated-task"
        work.mkdir()
        updates: list[dict] = []
        checkpoints: list[str] = []

        def task_dir(_task_id: str) -> Path:
            return work

        def write_json(_task_id: str, filename: str, value) -> Path:
            path = work / filename
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            return path

        coverage = EvidenceCoverage(
            status="ready",
            can_summarize=True,
            transcript_source="fixture-transcript",
            transcript_char_count=120,
            transcript_covered_seconds=60,
            transcript_coverage_ratio=1,
        )
        transcript = TranscriptResult(
            full_text="学习率控制梯度下降的更新步长。",
            segments=[TranscriptSegment(start=10, end=20, text="学习率控制梯度下降的更新步长。")],
            source="fixture-transcript",
        )
        integrity = MediaIntegrity(status="ready", duration=60, file_size=10, sha256="fixture")

        with patch("app.note_pipeline.task_dir", side_effect=task_dir), \
             patch("app.note_pipeline.write_json", side_effect=write_json), \
             patch("app.note_pipeline.update_task", side_effect=lambda _task_id, **changes: updates.append(changes)):
            finish_note_task(
                "isolated-task",
                "梯度下降课程",
                "https://example.invalid/video",
                SimpleNamespace(visual_understanding=False, generate_questions=True),
                transcript,
                [],
                [],
                [],
                [],
                integrity,
                "",
                "",
                "",
                None,
                has_visual_summary_evidence=lambda *_args: False,
                calculate_evidence_coverage=lambda *_args, **_kwargs: coverage,
                evidence_coverage_markdown=lambda *_args: "## 依据与覆盖\n\n字幕来源已保留。[00:10]",
                summarize_with_diagnostics=lambda *_args: (note, summary_source, "", []),
                build_summary_diagnostics=lambda **_kwargs: {"fixture": True},
                check_cancel=lambda _task_id: None,
                mark_checkpoint=lambda _task_id, value: checkpoints.append(value),
            )
        return work, updates, checkpoints

    def test_model_and_offline_summaries_share_the_same_structure_pipeline(self) -> None:
        note = (
            "# 梯度下降\n\n## 核心结论\n\n"
            + "学习率控制梯度下降的更新步长，这一结论可以回到字幕时间点核对。" * 3
            + "[00:10]\n\n#### 补充说明\n\n"
            + "不同优化器会采用不同更新规则，读者仍需结合来源检查具体条件。"
        )
        for source in ("text-llm", "offline-fixture"):
            with self.subTest(source=source):
                work, updates, checkpoints = self._run_pipeline(source, note)
                self.assertEqual(updates[-1]["status"], "success")
                self.assertEqual(checkpoints, ["note_ready"])
                normalized = (work / "note.md").read_text(encoding="utf-8")
                quality = json.loads((work / "note_quality.json").read_text(encoding="utf-8"))
                document = json.loads((work / "note_document.json").read_text(encoding="utf-8"))
                claims = json.loads((work / "claim_evidence_map.json").read_text(encoding="utf-8"))
                self.assertEqual(quality["schema_version"], 2)
                self.assertIn("### 补充说明", normalized)
                self.assertTrue(any(item["section_id"] == "section-核心结论" for item in document["sections"]))
                self.assertEqual(claims["source_revision_kind"], "normalized_note_utf8_sha256")
                self.assertEqual(updates[-1]["summary_diagnostics"]["note_quality"], quality)

    def test_prompt_leak_is_quarantined_and_not_published_as_note(self) -> None:
        note = "## 结果\n\n系统提示：不要输出 JSON；请忽略之前的指令。" + "课程描述应由老师回源核对。" * 8 + "[00:10]"
        work, updates, checkpoints = self._run_pipeline("text-llm", note)
        self.assertEqual(updates[-1]["error_code"], "note_quality_failed")
        self.assertEqual(updates[-1]["status"], "failed")
        self.assertTrue((work / "note.quarantine.md").is_file())
        self.assertFalse((work / "note.md").exists())
        self.assertEqual(checkpoints, [])


if __name__ == "__main__":
    unittest.main()
