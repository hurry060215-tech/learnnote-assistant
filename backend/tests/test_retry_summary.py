import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import TranscriptResult,TranscriptSegment
from app.storage import create_task,update_task,get_task

class RetrySummaryTests(unittest.TestCase):
 def test_retry_uses_owned_transcript_and_never_requires_media(self):
  with tempfile.TemporaryDirectory() as d,patch('app.storage.TASK_DIR',Path(d)):
   task=create_task('current_page','已保存字幕');p=Path(d)/task.id/'transcript.json';p.write_text(TranscriptResult(source='browser-subtitle',full_text='已保存的真实字幕',segments=[TranscriptSegment(start=0,end=10,text='已保存的真实字幕')]).model_dump_json(),encoding='utf-8');update_task(task.id,status='failed',phase='failed',error_code='summary_unavailable',transcript_path=str(p))
   with patch('app.main.schedule_processing') as schedule:
    r=TestClient(app).post(f'/api/tasks/{task.id}/retry-summary',json={'llm_base_url':'https://api.xiaomimimo.com/v1','llm_model':'mimo-v2.5','llm_api_key':'test-secret'})
   self.assertEqual(r.status_code,200,r.text);self.assertEqual(get_task(task.id).options.llm_api_key,None);self.assertEqual(schedule.call_args.kwargs['_queue_kind'],'summary');self.assertEqual(schedule.call_args.args[1].__name__,'process_saved_transcript_task');self.assertNotIn('test-secret',r.text)
 def test_active_or_missing_transcript_does_not_schedule(self):
  with tempfile.TemporaryDirectory() as d,patch('app.storage.TASK_DIR',Path(d)),patch('app.main.schedule_processing') as schedule:
   t=create_task('current_page','尚无字幕');update_task(t.id,status='failed',phase='failed')
   client=TestClient(app);self.assertEqual(client.post(f'/api/tasks/{t.id}/retry-summary',json={}).status_code,409);update_task(t.id,status='running');self.assertEqual(client.post(f'/api/tasks/{t.id}/retry-summary',json={}).status_code,409);schedule.assert_not_called()
