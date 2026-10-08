from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from app.models import TaskOptions, TranscriptResult, TranscriptSegment
from app.storage import create_task, get_task, task_dir, update_task, write_json
from app.processor import process_saved_transcript_task
from app.text_cleanup import correct_transcript_terms
from app.transcript_quality import preserve_transcript_review_draft, transcript_quality_report

class TranscriptPublicationQualityTests(unittest.TestCase):
    def transcript(self):
        raw = '正常语音内容' * 50 + '\ufffd'
        return TranscriptResult(source='faster-whisper', full_text=raw, segments=[TranscriptSegment(start=10,end=20,text=raw)])

    def test_sparse_asr_remains_a_draft_and_raw_source_is_untouched(self):
        with tempfile.TemporaryDirectory() as temp, patch('app.storage.TASK_DIR',Path(temp)/'tasks'), patch('app.observability.TASK_DIR',Path(temp)/'tasks'), patch('app.storage.ensure_dirs',lambda:None):
            task = create_task('local','课程')
            raw_path = write_json(task.id,'transcript_raw.json',self.transcript().model_dump(mode='json'))
            raw_bytes = raw_path.read_bytes()
            transcript = correct_transcript_terms(self.transcript())
            path = write_json(task.id,'transcript.json',transcript.model_dump(mode='json'))
            update_task(task.id,transcript_path=str(path))
            with patch('app.processor.summarize_with_diagnostics') as summarize:
                process_saved_transcript_task(task.id,TaskOptions())
            summarize.assert_not_called()
            record = get_task(task.id)
            self.assertEqual(record.error_code,'transcript_review_required')
            self.assertEqual(record.status,'failed')
            self.assertEqual(record.summary_source,'transcript-draft')
            self.assertIn('【识别不清】',Path(record.note_path).read_text(encoding='utf-8'))
            self.assertFalse((task_dir(task.id)/'note.md').exists())
            self.assertEqual(raw_bytes,raw_path.read_bytes())
            quality = record.summary_diagnostics['transcript_quality']
            self.assertEqual(quality['issue_kind'],'asr_character_uncertainty')
            self.assertFalse(quality['encoding_repaired'])
            self.assertFalse(record.summary_diagnostics['summary_generated'])

    def test_quality_distinguishes_asr_ambiguity_from_corrupt_imported_text(self):
        source = self.transcript()
        self.assertEqual(transcript_quality_report(source)['issue_kind'],'asr_character_uncertainty')
        self.assertEqual(transcript_quality_report(source.model_copy(update={'source':'page-subtitle'}))['issue_kind'],'unicode_corruption')
        clean = TranscriptResult(full_text='正常文字。',source='faster-whisper')
        self.assertTrue(transcript_quality_report(clean)['formal_note_allowed'])

    def test_video_pipeline_blocks_before_any_summarizer_call(self):
        from app.note_pipeline import finish_note_task
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); updates=[]
            def write(_task,name,value):
                path=root/name;path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return path
            summarize=Mock();checkpoint=Mock()
            with patch('app.note_pipeline.task_dir',return_value=root),patch('app.note_pipeline.write_json',side_effect=write),patch('app.note_pipeline.update_task',side_effect=lambda _,**kwargs:updates.append(kwargs)):
                finish_note_task('fixture','课程','',TaskOptions(),correct_transcript_terms(self.transcript()),[],[],[],[],SimpleNamespace(duration=20),'','','',None,
                    has_visual_summary_evidence=Mock(),calculate_evidence_coverage=Mock(),evidence_coverage_markdown=Mock(),summarize_with_diagnostics=summarize,
                    build_summary_diagnostics=Mock(),check_cancel=Mock(),mark_checkpoint=checkpoint)
            summarize.assert_not_called();checkpoint.assert_not_called()
            self.assertEqual(updates[-1]['error_code'],'transcript_review_required')
            self.assertFalse((root/'note.md').exists())
