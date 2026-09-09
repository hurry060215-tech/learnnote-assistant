import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app.models import ActiveVideoInfo,BrowserSubtitleCue,CurrentPageTaskRequest,TaskOptions
from app.processor import process_current_page_task
from app.storage import create_task,get_task
from app.transcript_passages import caption_passages

class ExplicitModeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.patches=[patch('app.storage.TASK_DIR',self.root/'tasks'),patch('app.observability.TASK_DIR',self.root/'tasks'),patch('app.storage.ensure_dirs',lambda:None)]
  for p in self.patches:p.start()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.temp.cleanup()
 def test_caption_mode_exports_text_without_model_or_media(self):
  r=CurrentPageTaskRequest(page_url='https://example.com/video',title='仅字幕',active_video=ActiveVideoInfo(duration=10),browser_subtitles=[BrowserSubtitleCue(start=0,end=10,text='这是一段完整的短视频字幕。')],options=TaskOptions(content_mode='subtitles',visual_understanding=True))
  t=create_task('current_page',r.title,r.page_url,options=r.options)
  with patch('app.processor.MediaDownloader') as cls,patch('app.processor.summarize_with_diagnostics') as llm:
   cls.return_value.attempts=[];cls.return_value.resolved_title='';process_current_page_task(t.id,r)
   cls.return_value.download.assert_not_called();llm.assert_not_called()
  done=get_task(t.id);self.assertEqual(done.status,'success');self.assertEqual(done.summary_source,'subtitle-extract');self.assertTrue(Path(done.transcript_path).is_file())
 def test_missing_captions_do_not_start_media_fallback(self):
  r=CurrentPageTaskRequest(page_url='https://example.com/video',title='没有字幕',options=TaskOptions(content_mode='subtitles'))
  t=create_task('current_page',r.title,r.page_url,options=r.options)
  with patch('app.processor.MediaDownloader') as cls,patch('app.processor.summarize_with_diagnostics') as llm:
   cls.return_value.attempts=[];cls.return_value.resolved_title='';cls.return_value.resolved_duration=0;cls.return_value.download_subtitle.return_value=None
   process_current_page_task(t.id,r);cls.return_value.download.assert_not_called();llm.assert_not_called()
  self.assertEqual(get_task(t.id).error_code,'subtitles_unavailable')
 def test_explicit_modes_resolve_conflicting_visual_flags(self):
  self.assertFalse(TaskOptions(content_mode='text',visual_understanding=True,local_ocr=True).local_ocr)
  self.assertTrue(TaskOptions(content_mode='visual',visual_understanding=False).visual_understanding)
 def test_known_text_only_model_does_not_start_visual_download(self):
  r=CurrentPageTaskRequest(page_url='https://example.com/video',title='需要画面',options=TaskOptions(content_mode='visual',llm_base_url='https://api.deepseek.com/v1',llm_model='deepseek-chat'))
  t=create_task('current_page',r.title,r.page_url,options=r.options)
  with patch('app.processor.MediaDownloader') as downloader:
   process_current_page_task(t.id,r)
   downloader.assert_not_called()
  self.assertEqual(get_task(t.id).error_code,'visual_model_required')
 def test_caption_mode_cannot_fallback_to_page_model(self):
  from app.processor import process_page_text_task,complete_with_download_failure_fallback
  r=CurrentPageTaskRequest(mode='page_text',page_url='https://example.com/video',title='只要字幕',page_text='网页上的内容',options=TaskOptions(content_mode='subtitles'))
  t=create_task('current_page',r.title,r.page_url,options=r.options)
  with patch('app.processor.write_page_text_artifacts') as page_model:
   process_page_text_task(t.id,r)
   self.assertFalse(complete_with_download_failure_fallback(t.id,r,'drm_or_encrypted','restricted'))
   page_model.assert_not_called()
 def test_protected_video_can_export_available_captions_without_model(self):
  r=CurrentPageTaskRequest(page_url='https://example.com/video',title='已有字幕',drm_detected=True,active_video=ActiveVideoInfo(duration=10),browser_subtitles=[BrowserSubtitleCue(start=0,end=10,text='可读取的字幕原文。')],options=TaskOptions(content_mode='subtitles'))
  t=create_task('current_page',r.title,r.page_url,options=r.options)
  with patch('app.processor.MediaDownloader') as cls,patch('app.processor.summarize_with_diagnostics') as llm,patch('app.processor.write_page_text_artifacts') as page_model:
   cls.return_value.attempts=[];cls.return_value.resolved_title='';process_current_page_task(t.id,r)
   cls.return_value.download.assert_not_called();llm.assert_not_called();page_model.assert_not_called()
  self.assertEqual(get_task(t.id).summary_source,'subtitle-extract')
 def test_passages_follow_actual_cues_and_pauses(self):
  parts=caption_passages([{'start':13.2,'end':20,'text':'第一段。'},{'start':25.5,'end':39,'text':'后面的另一段。'},{'start':40,'end':42,'text':'接着说。'}])
  self.assertEqual([p[0]['start'] for p in parts],[13.2,25.5]);self.assertEqual(parts[-1][-1]['end'],42)
 def test_local_caption_resume_uses_saved_browser_captions_without_asr(self):
  from app.models import MediaIntegrity
  from app.processor import process_local_video_task
  from app.storage import update_task
  options=TaskOptions(content_mode='subtitles')
  task=create_task('local','已保存的浏览器字幕',options=options)
  update_task(task.id,media_integrity=MediaIntegrity(status='ready',duration=10))
  cues=[BrowserSubtitleCue(start=0,end=10,text='这是已经交接的完整字幕。')]
  with patch('app.processor.extract_embedded_subtitle') as embedded,patch('app.processor.transcribe_with_task_progress') as asr,patch('app.processor.summarize_with_diagnostics') as llm:
   process_local_video_task(task.id,self.root/'media.mp4',task.title,options,browser_subtitles=cues)
  embedded.assert_not_called();asr.assert_not_called();llm.assert_not_called()
  done=get_task(task.id);self.assertEqual(done.status,'success')
  import json
  self.assertEqual(json.loads(Path(done.transcript_path).read_text(encoding='utf-8'))['source'],'browser-subtitle')
