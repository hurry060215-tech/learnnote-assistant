import unittest
from app.note_document import normalize_note_markdown


class QuestionPreferenceTests(unittest.TestCase):
    def test_generated_quiz_removed_only_when_explicitly_disabled(self):
        note = '# 标题\n\n## 正文\n内容保留。\n\n## 自测题\n生成的问题？\n### 答案\n生成的答案。\n\n## 依据与覆盖\n来源保留。'
        value = normalize_note_markdown('标题',note,generate_questions=False)
        self.assertNotIn('生成的问题',value.markdown)
        self.assertNotIn('生成的答案',value.markdown)
        self.assertIn('来源保留',value.markdown)
        self.assertEqual(value.report['removed_question_sections'],1)
        self.assertIn('生成的问题',normalize_note_markdown('标题',note).markdown)
        self.assertIn('生成的问题',normalize_note_markdown('标题',note,generate_questions=True).markdown)

    def test_title_code_and_source_examples_are_not_deleted(self):
        note = '# 自测题\n\n## 课堂例题\n原文例题保留。\n\n```markdown\n## 自测题\n代码示例保留\n```'
        value = normalize_note_markdown('自测题',note,generate_questions=False)
        self.assertIn('原文例题保留',value.markdown)
        self.assertIn('代码示例保留',value.markdown)
