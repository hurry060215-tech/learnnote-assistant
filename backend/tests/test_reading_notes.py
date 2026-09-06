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
