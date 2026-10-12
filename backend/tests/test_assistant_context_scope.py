from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import assistant_skills as skills
from app.assistant_context import conversation_turns
from app.main import app
from app.models import TaskOptions


class AssistantContextTests(unittest.TestCase):
    def turn(self, question, *, conversation="live", skill="general.chat", age=0, state="completed"):
        return {"question": question, "answer": "合成回答", "conversation_id": conversation,
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=age)).isoformat(),
                "skill": {"id": skill}, "execution": {"state": state}}

    def test_archive_other_scopes_and_help_are_not_general_chat_context(self):
        archived = [self.turn("几周前PDF导出", age=60 * 24 * 14),
                    self.turn("另一份笔记", conversation="other"),
                    self.turn("如何导出PDF", skill="product.help")]
        with tempfile.TemporaryDirectory() as directory, patch.object(skills, "DATA_DIR", Path(directory)), \
                patch.object(skills, "history", return_value=archived), patch("openai.OpenAI") as constructor:
            client = constructor.return_value.__enter__.return_value
            client.chat.completions.create.return_value = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="成功依赖目标与持续行动。"))])
            result = skills.execute_global("general.chat", "最好的成功方式", TaskOptions(
                llm_base_url="http://127.0.0.1:1234/v1", llm_model="dummy"), conversation_id="live")
            messages = client.chat.completions.create.call_args.kwargs["messages"]
            self.assertEqual([m["content"] for m in messages if m["role"] == "user"], ["最好的成功方式"])
            self.assertEqual(result["source"], "llm")

    def test_same_live_topic_retains_followups_without_failed_or_old_turns(self):
        items = [self.turn("过期", age=31), self.turn("目标如何拆解？"), self.turn("给个例子")]
        self.assertEqual([t["question"] for t in conversation_turns(items, "live", "general.chat")],
                         ["目标如何拆解？", "给个例子"])
        self.assertEqual(conversation_turns(items, "", "general.chat"), [])
        self.assertEqual(conversation_turns(items, "new-topic", "general.chat"), [])
        self.assertEqual(conversation_turns(items + [self.turn("未完成", state="failed")], "live", "general.chat"), [])

    def test_help_followup_cannot_cross_conversations(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(skills, "DATA_DIR", Path(directory)):
            skills.execute_global("product.help", "怎么导出PDF", conversation_id="old")
            result = skills.execute_global("product.help", "下一步呢", conversation_id="new")
            self.assertNotIn("导出笔记", [action["label"] for action in result["actions"]])
            self.assertEqual(skills.history()[-1]["conversation_id"], "new")

    def test_outline_requests_are_scoped_and_distinct_from_software_help(self):
        for question in ("笔记生成目录", "为当前笔记生成目录", "列出当前笔记的目录", "整理大纲"):
            with self.subTest(question=question):
                self.assertEqual(skills.resolve_skill(question, "auto", True)["skill"]["id"], "note.outline")
                self.assertTrue(skills.resolve_skill(question, "auto", False)["needs_source"])
        for question in ("目录在哪里", "怎么调整目录字号", "怎么导出当前笔记"):
            self.assertEqual(skills.resolve_skill(question, "auto", True)["skill"]["id"], "product.help")
        self.assertEqual(skills.resolve_skill("最好的成功方式", "auto", True, "product.help")["skill"]["id"], "general.chat")


class AssistantOutlineApiTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in ("app.library", "app.knowledge", "app.routers.library", "app.routers.notes"):
            self.stack.enter_context(patch(f"{module}.DATA_DIR", self.root))
        self.client = TestClient(app)

    def test_outline_reads_personal_saved_revision_not_other_material_or_code(self):
        original = "# 原始标题\n\n## 原文段落\n\n原始字节不能改变。"
        imported = self.client.post("/api/library/materials/import", files={"file": ("outline.md", original.encode(), "text/markdown")})
        self.assertEqual(imported.status_code, 200, imported.text)
        source_id = imported.json()["material"]["material_id"]
        url = f"/api/tasks/editions/material/{source_id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.text)
        edition = response.json()
        edited = "# 个人修订\n\n## **学习率与稳定性**\n\n```md\n## 代码不是目录\n```\n\n### [安全标题](javascript:alert)"
        saved = self.client.put(url, json={"revision": edition["revision"], "text": edited})
        self.assertEqual(saved.status_code, 200, saved.text)
        outline_url = f"/api/assistant/outline/material/{source_id}"
        with patch("openai.OpenAI") as constructor:
            result = self.client.get(outline_url, params={"revision": saved.json()["revision"]})
            constructor.assert_not_called()
        self.assertEqual(result.status_code, 200, result.text)
        headings = [item["title"] for item in result.json()["outline"]]
        self.assertEqual(headings, ["个人修订", "学习率与稳定性", "[安全标题](javascript:alert)"])
        self.assertIn(r"\[安全标题\](javascript:alert)", result.json()["answer"])
        self.assertEqual(self.client.get(url).json()["text"], edited)
        from app.library import material_content
        self.assertEqual(material_content(source_id), original)
        self.assertEqual(self.client.get(outline_url, params={"revision": edition["revision"]}).status_code, 409)
        self.assertEqual(self.client.get("/api/assistant/outline/material/not-existing").status_code, 404)
        self.assertEqual(self.client.get(f"/api/assistant/outline/shell/{source_id}").status_code, 422)

    def test_unstructured_note_reports_no_existing_headings_without_inventing_them(self):
        from app.assistant_outline import read_outline
        with patch("app.routers.notes.get_edition", return_value={"text": "正文只有一段。", "revision": "a" * 64}):
            result = read_outline("task", "synthetic")
        self.assertEqual(result["outline"], [])
        self.assertIn("还没有 Markdown 标题", result["answer"])

