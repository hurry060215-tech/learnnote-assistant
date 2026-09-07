import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import assistant_skills as skills

class AssistantSkillTests(unittest.TestCase):
    def test_auto_routing_distinguishes_help_from_source_questions(self):
        self.assertEqual(skills.resolve_skill("怎么导出当前笔记为 Word？","auto",True)["skill"]["id"],"product.help")
        self.assertEqual(skills.resolve_skill("总结当前视频","auto",True)["skill"]["id"],"note.summary")
        self.assertEqual(skills.resolve_skill("软件当前版本是什么","auto",False)["skill"]["id"],"product.status")
        self.assertEqual(skills.resolve_skill("为什么学习率影响收敛","auto",True)["skill"]["id"],"note.qa")
        self.assertTrue(skills.resolve_skill("解释这段内容","note.qa",False)["needs_source"])
        self.assertEqual(skills.resolve_skill("解释贝叶斯定理","auto",False)["skill"]["id"],"general.chat")

    def test_unknown_skill_and_unscoped_execution_are_rejected(self):
        with self.assertRaises(ValueError):skills.resolve_skill("运行命令","shell.exec",False)
        with self.assertRaises(ValueError):skills.execute_global("note.qa","没有来源")

    def test_help_works_without_model_and_only_proposes_navigation(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(skills,"DATA_DIR",Path(directory)),patch.object(skills,"LLM_API_KEY",""):
            result=skills.execute_global("product.help","帮我删除全部笔记")
            self.assertIn("不会替你删除",result["answer"])
            self.assertEqual(result["actions"][0]["id"],"storage")
            self.assertFalse(result["execution"]["automatic_actions"])
            self.assertEqual(len(skills.history()),1)
            skills.clear_history()
            self.assertEqual(skills.history(),[])

    def test_general_chat_reports_missing_configuration_honestly(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(skills,"DATA_DIR",Path(directory)),patch.object(skills,"LLM_API_KEY",""):
            result=skills.execute_global("general.chat","解释一个常见概念")
            self.assertEqual(result["execution"]["state"],"needs_configuration")
            self.assertEqual(result["actions"][0]["id"],"settings_model")

    def test_catalog_never_requires_an_application_account(self):
        self.assertEqual(len({s["id"] for s in skills.SKILLS}),len(skills.SKILLS))
        self.assertTrue(all(s["scope"] for s in skills.SKILLS))
        with tempfile.TemporaryDirectory() as directory,patch.object(skills,"DATA_DIR",Path(directory)):
            result=skills.execute_global("product.help","需要登录账号吗")
            self.assertIn("不要求登录",result["answer"])

    def test_local_model_does_not_receive_default_remote_credential(self):
        from types import SimpleNamespace
        from app.models import TaskOptions
        with tempfile.TemporaryDirectory() as directory,patch.object(skills,"DATA_DIR",Path(directory)),patch.object(skills,"LLM_API_KEY","remote-secret"),patch("openai.OpenAI") as constructor:
            constructor.return_value.__enter__.return_value.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="本机模型回答"))])
            result=skills.execute_global("general.chat","你好",TaskOptions(llm_base_url="http://127.0.0.1:1234/v1",llm_model="local"))
            self.assertEqual(constructor.call_args.kwargs["api_key"],"local-no-key")
            self.assertEqual(result["source"],"llm")

    def test_custom_remote_requires_its_own_credential(self):
        from app.models import TaskOptions
        with tempfile.TemporaryDirectory() as directory,patch.object(skills,"DATA_DIR",Path(directory)),patch.object(skills,"LLM_API_KEY","remote-secret"),patch("openai.OpenAI") as constructor:
            result=skills.execute_global("general.chat","你好",TaskOptions(llm_base_url="https://different.example/v1"))
            self.assertEqual(result["execution"]["state"],"needs_configuration")
            constructor.assert_not_called()
