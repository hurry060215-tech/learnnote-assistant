import unittest,tempfile,sys
from pathlib import Path
from unittest.mock import Mock,patch
from types import SimpleNamespace
from app.models import TaskOptions,TranscriptResult
from app.processor_state import TaskCancelled
from app.transcript_pipeline import prepare_transcript
from app.transcriber import transcribe_audio

class CancellationRegressionTests(unittest.TestCase):
 def test_cancel_during_audio_extraction_does_not_write_empty_transcript(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   helpers={name:Mock(return_value=None) for name in ['parse_subtitle_or_none','browser_subtitles_are_reliable','extract_embedded_subtitle','extract_audio','transcribe_with_task_progress','write_browser_subtitles_srt','correct_transcript_terms','use_remote_asr','asr_failure_detail','calculate_evidence_coverage']}
   helpers['transcript_from_browser_subtitles']=Mock(return_value=TranscriptResult())
   with patch('app.transcript_pipeline.task_dir',return_value=root),patch('app.transcript_pipeline.update_task') as update,patch('app.transcript_pipeline.check_cancel',side_effect=TaskCancelled('task')),patch('app.transcript_pipeline.write_json') as write:
    with self.assertRaises(TaskCancelled):prepare_transcript('task',root/'media.mp4',root/'media.mp4',SimpleNamespace(status='ready',duration=10),TaskOptions(),None,[],'',**helpers)
    helpers['transcribe_with_task_progress'].assert_not_called();write.assert_not_called()
    self.assertFalse(any(c.kwargs.get('phase')=='transcribing' for c in update.call_args_list))
 def test_local_asr_callback_cancellation_propagates(self):
  progress=Mock(side_effect=[None,TaskCancelled('task')])
  with patch.dict(sys.modules,{'faster_whisper':SimpleNamespace(WhisperModel=Mock())}),patch('app.transcriber.configure_local_caches'),patch('app.transcriber.resolve_whisper_model',return_value='small'):
   with self.assertRaises(TaskCancelled):transcribe_audio(Path('audio.wav'),progress_callback=progress)

class SpeechUnicodeTests(unittest.TestCase):
 def test_sparse_local_decode_uncertainty_is_visible_without_losing_transcript(self):
  from app.models import TranscriptSegment
  from app.text_cleanup import correct_transcript_terms,TextDecodingError
  text="正常语音内容" * 50 + "\ufffd"
  original=TranscriptResult(source="faster-whisper",segments=[TranscriptSegment(start=670,end=672,text=text)],full_text=text)
  fixed=correct_transcript_terms(original)
  self.assertIn("【识别不清】",fixed.full_text)
  self.assertIn("11:10",fixed.warning)
  self.assertIn("\ufffd",original.full_text)
  with self.assertRaises(TextDecodingError):correct_transcript_terms(original.model_copy(update={"source":"page-subtitle"}))
 def test_widespread_local_corruption_still_fails(self):
  from app.text_cleanup import correct_transcript_terms,TextDecodingError
  with self.assertRaises(TextDecodingError):correct_transcript_terms(TranscriptResult(source="faster-whisper",full_text="坏\ufffd\ufffd"))

if __name__=='__main__':unittest.main()
