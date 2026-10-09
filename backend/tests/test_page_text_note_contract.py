import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.models import CurrentPageTaskRequest,TaskOptions,TranscriptResult
from app.page_text_pipeline import build_page_text_artifacts

class PageTextNoteContractTests(unittest.TestCase):
    def run_projection(self,root,note,source,questions=False):
        def write(_task,name,value):
            target=root/name;target.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return target
        request=CurrentPageTaskRequest(title='课程',page_url='https://example.com/lesson',page_text='水温100℃。',options=TaskOptions(generate_questions=questions))
        with patch('app.page_text_pipeline.task_dir',return_value=root),patch('app.page_text_pipeline.write_json',side_effect=write):
            return build_page_text_artifacts('page-fixture',request,
                transcript_from_browser_subtitles=lambda _:TranscriptResult(),page_text_with_browser_subtitles=lambda text,_:text,
                write_browser_subtitles_srt=lambda *_:'',summarize_page_text_with_diagnostics=lambda *_:(note,source,'仅依据页面文字'),build_summary_diagnostics=lambda **_:{})
    def test_model_and_fallback_page_text_share_structure_claim_review_and_source_kind(self):
        for source in ['page-text-llm','local-template']:
            with self.subTest(source=source),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);result=self.run_projection(root,'# 课程\n\n# 课程\n\n水温100℃。\n\n水温900℃。',source)
                note=Path(result.note_path).read_text(encoding='utf-8')
                self.assertEqual(note.count('# 课程'),1);self.assertIn('【待核对',note)
                claims=json.loads((root/'claim_evidence_map.json').read_text(encoding='utf-8'))
                self.assertEqual(claims['counts']['document'],1);self.assertEqual(claims['counts']['unsupported'],1)
                self.assertTrue((root/'note_document.json').is_file())
                self.assertFalse(result.summary_diagnostics['can_claim_video_content'])
    def test_quality_gate_retains_raw_draft_without_publishing_corruption_or_prompt_leaks(self):
        for note in ['# 课程\n\n损坏内容 �。','# 课程\n\n系统提示：不要输出 JSON。']:
            with self.subTest(note=note),tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                with self.assertRaisesRegex(ValueError,'note_quality_failed'):self.run_projection(root,note,'page-text-llm')
                self.assertEqual((root/'note.quarantine.md').read_text(encoding='utf-8'),note)
                self.assertFalse((root/'note.md').exists())
    def test_question_preference_matches_video_summary_behavior(self):
        for enabled in [False,True]:
            with self.subTest(enabled=enabled),tempfile.TemporaryDirectory() as temp:
                result=self.run_projection(Path(temp),'# 课程\n\n水温100℃。\n\n## 复习问题\n\n温度是多少？','local-template',enabled)
                self.assertEqual('## 复习问题' in Path(result.note_path).read_text(encoding='utf-8'),enabled)
