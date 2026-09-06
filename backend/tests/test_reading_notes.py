import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from app.models import TranscriptResult, TranscriptSegment, TaskOptions
from app.reading_notes import source_blocks, readable_extract
from app.summarizer import local_markdown_note, note_generation_contract
from app.routers.notes import get_edition, put_edition, EditionRequest

class ReadingNotesTests(unittest.TestCase):
    def test_default_extract_preserves_tail_and_does_not_repeat_template_sections(self):
        text = "学习率控制更新步长。"
        transcript = TranscriptResult(full_text=text, segments=[TranscriptSegment(start=i*30,end=i*30+10,text=f"{text} UNIQUE_{i}") for i in range(120)])
        note = local_markdown_note("讲义",transcript,[],options=TaskOptions())
        self.assertIn("字幕摘录",note)
        self.assertEqual(note.count("UNIQUE_119"),1)
        self.assertNotIn("## 易错点",note)
        self.assertNotIn("## 复习问题",note)
        self.assertIn("`59:30`",note)

    def test_chunking_covers_all_characters_and_does_not_mutate_input(self):
        original = "α" * 70001 + "FINAL_MARKER"
        transcript = TranscriptResult(full_text=original)
        blocks = source_blocks(transcript)
        self.assertEqual("".join(blocks), original)
        self.assertTrue(all(len(b)<=16000 for b in blocks))
        self.assertEqual(transcript.full_text,original)
        self.assertNotIn("1000-1800",note_generation_contract(TaskOptions()))

    def test_editions_are_independent_and_reject_stale_save(self):
        with tempfile.TemporaryDirectory() as directory, patch("app.routers.notes.DATA_DIR",Path(directory)), patch("app.routers.notes._edition_source",return_value="original"):
            first=get_edition("task","sample")
            saved=put_edition("task","sample",EditionRequest(text="edited",revision=first["revision"]))
            self.assertEqual(get_edition("task","sample")["text"],"edited")
            with self.assertRaises(HTTPException) as caught:
                put_edition("task","sample",EditionRequest(text="stale",revision=first["revision"]))
            self.assertEqual(caught.exception.status_code,409)
            self.assertEqual(get_edition("task","sample")["revision"],saved["revision"])

    def test_long_model_input_includes_final_block_and_preserves_original(self):
        from types import SimpleNamespace
        from app.summarizer import summarize_with_llm
        prompts = []
        def create(**kwargs):
            prompts.append(kwargs["messages"][0]["content"][0]["text"])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="# 讲义\n\n已有内容的整理。"))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        original = "可核对的课程内容。" * 8000 + "FINAL_SOURCE_MARKER"
        transcript = TranscriptResult(full_text=original)
        with patch("openai.OpenAI",return_value=client), patch("app.summarizer._validated_generated_note",side_effect=lambda *args:args[3]):
            result = summarize_with_llm("讲义",transcript,[],TaskOptions(llm_api_key="fixture",visual_understanding=False))
        self.assertIsNotNone(result)
        self.assertGreater(len(prompts),3)
        self.assertIn("FINAL_SOURCE_MARKER",prompts[-1])
        self.assertEqual(transcript.full_text,original)

    def test_short_chinese_fact_can_be_reviewed_without_padding(self):
        from app.study_content import review_points
        self.assertEqual(review_points("学习率控制参数更新步长。"), [("", "学习率控制参数更新步长。")])
        self.assertEqual(review_points("好的。"), [])

    def test_edition_export_uses_saved_revision(self):
        from app.routers.notes import export_edition
        with tempfile.TemporaryDirectory() as directory, patch("app.routers.notes.DATA_DIR",Path(directory)), patch("app.routers.notes._edition_source",return_value="original"):
            first=get_edition("task","example")
            put_edition("task","example",EditionRequest(text="edited final",revision=first["revision"]))
            result=export_edition("task","example","markdown")
            self.assertEqual(result.body.decode(),"edited final")

    def test_deleting_task_removes_its_private_edition(self):
        import hashlib
        from types import SimpleNamespace
        from app.storage import delete_task
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); editions=root/"user-editions";editions.mkdir()
            entry=editions/(hashlib.sha256(b"task:abc123").hexdigest()+".json")
            entry.write_text("private edit")
            record=SimpleNamespace(id="abc123",status="success",source_media_path="")
            with patch("app.storage.DATA_DIR",root),patch("app.storage.TASK_DIR",root/"tasks"),patch("app.storage.get_task",return_value=record),patch("app.storage.remove_task",return_value=True):
                delete_task("abc123")
            self.assertFalse(entry.exists())

    def test_material_question_returns_only_its_own_source(self):
        from app.routers.library import api_material_ask
        anchors=[{"text":"学习率控制参数更新步长。","locator":"第 1 段","evidence_id":"own-source"}]
        with patch("app.routers.library.material_anchors",return_value=anchors):
            result=api_material_ask("selected-material",{"question":"学习率控制什么？"})
        self.assertEqual(result["material_id"],"selected-material")
        self.assertEqual(result["evidence_ids"],["own-source"])
        self.assertIn("未生成推断",result["answer"])

    def test_first_study_plan_creation_is_atomic_across_readers(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from app import study
        gate=Barrier(4)
        original_connect=study._connect
        class Connection:
            def __init__(self):
                self.connection=original_connect()
                self.first=True
            def __getattr__(self,name):
                return getattr(self.connection,name)
            def execute(self,sql,*args):
                cursor=self.connection.execute(sql,*args)
                if self.first and sql.startswith("SELECT * FROM study_plans"):
                    self.first=False
                    row=cursor.fetchone()
                    gate.wait(timeout=10)
                    class Result:
                        def fetchone(self): return row
                    return Result()
                return cursor
        with tempfile.TemporaryDirectory() as directory,patch("app.study.DATA_DIR",Path(directory)):
            original_connect().close()
            with patch("app.study._connect",side_effect=Connection),ThreadPoolExecutor(max_workers=4) as workers:
                plans=list(workers.map(lambda _:study.get_study_plan(),range(4)))
            self.assertTrue(all(p.plan_id=="default" for p in plans))
            self.assertEqual(len({p.created_at for p in plans}),1)
