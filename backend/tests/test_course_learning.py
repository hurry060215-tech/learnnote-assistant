"""Course retry uses real owned captions and admission, without remote calls."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import config, courses, course_episodes, storage, library, knowledge, study, community, main
from app.models import TaskOptions, TranscriptResult, TranscriptSegment
from app.task_control_state import task_generation


class CourseLearningTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        paths = {'DATA_DIR': self.root, 'TASK_DIR': self.root/'tasks', 'UPLOAD_DIR': self.root/'uploads',
                 'TEMP_DIR': self.root/'temp', 'MODEL_CACHE_DIR': self.root/'models', 'STATIC_DIR': self.root/'static'}
        for module in (config, courses, course_episodes, storage, library, knowledge, study, community, main):
            for key, value in paths.items():
                if hasattr(module, key): self.stack.enter_context(patch.object(module, key, value))
        config.ensure_dirs()
        self.stack.enter_context(patch.object(main, 'require_ready_note_model'))
        self.stack.enter_context(patch.object(main, 'resolve_model_options', side_effect=lambda options: options))
        self.schedule = self.stack.enter_context(patch.object(main, 'schedule_processing'))
        self.course = courses.save_course('Synthetic course', [{'kind':'url','url':'https://www.youtube.com/watch?v=abcdefghijk'}])
        self.episode = course_episodes.course_episodes(self.course)[0]
        course_episodes.prepare_course_episode(self.course, self.episode['episode_id'])
        self.task = storage.create_task('current_page', 'Synthetic caption episode', page_url=self.episode['url'],
            handoff_id=self.episode['handoff_id'], options=TaskOptions(content_mode='text', visual_understanding=False))
        self.caption = storage.task_dir(self.task.id)/'transcript.json'
        transcript = TranscriptResult(source='browser-subtitle', language='en', full_text='Synthetic lesson evidence explains the original episode without requiring media.',
            segments=[TranscriptSegment(start=0,end=12,text='Synthetic lesson evidence explains the original episode without requiring media.')])
        self.caption.write_text(transcript.model_dump_json(), encoding='utf-8')
        self.note = storage.task_dir(self.task.id)/'note.md'; self.note.write_text('# Original synthetic note\n', encoding='utf-8')
        self.task = storage.update_task(self.task.id, status='failed', mode='subtitle_only', checkpoint='transcribed',
            transcript_path=str(self.caption), note_path=str(self.note), error_code='summary_unavailable')
        course_episodes.bind_course_episode(self.course, self.episode['episode_id'], self.task.id)
        self.client = TestClient(main.app)
        self.route = f"/api/courses/{self.course['id']}/episodes/{self.episode['episode_id']}/retry"
        self.body = {'revision':self.course['revision'], 'task_id':self.task.id, 'generation':task_generation(self.task),
                     'options':{'content_mode':'text','visual_understanding':False,'resource_budget_mb':512}}

    def test_owned_caption_only_retry_preserves_identity_and_original_artifacts(self):
        before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in (self.caption,self.note)]
        episode = course_episodes.course_episodes(self.course)[0]
        self.assertEqual(episode['retry_kind'], 'summary')
        result = self.client.post(self.route,json=self.body)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['task_id'],self.task.id)
        self.assertEqual(self.schedule.call_count,1)
        self.assertEqual(self.schedule.call_args.args[1].__name__,'process_saved_transcript_task')
        self.assertEqual(self.schedule.call_args.kwargs['_queue_kind'],'summary')
        self.assertEqual(storage.get_task(self.task.id).options.resource_budget_mb,512)
        self.assertEqual(before,[(path.read_bytes(),path.stat().st_mtime_ns) for path in (self.caption,self.note)])
        self.assertEqual(course_episodes.course_episodes(self.course)[0]['task_id'],self.task.id)
        self.assertEqual(len(storage.list_tasks_snapshot()),1)
        self.assertEqual(self.client.post(self.route,json=self.body).status_code,409)
        self.assertEqual(self.schedule.call_count,1)

    def test_stale_generation_task_or_course_never_dispatches(self):
        for change in ({'generation':'0'*64},{'task_id':'wrong'},{'revision':self.course['revision']+1}):
            with self.subTest(change=change):
                self.assertEqual(self.client.post(self.route,json={**self.body,**change}).status_code,409)
        self.schedule.assert_not_called()

    def test_paused_removed_or_deleted_episode_never_dispatches(self):
        paused = courses.save_course(self.course['title'],self.course['sources'],True,self.course['id'],self.course['revision'])
        self.assertEqual(self.client.post(self.route,json={**self.body,'revision':paused['revision']}).status_code,409)
        removed = courses.save_course(paused['title'],[],False,paused['id'],paused['revision'])
        self.assertEqual(self.client.post(self.route,json={**self.body,'revision':removed['revision']}).status_code,409)
        courses.delete_course(self.course['id'])
        self.assertEqual(self.client.post(self.route,json=self.body).status_code,409)
        self.schedule.assert_not_called()

    def test_caption_retry_never_accepts_visual_or_subtitle_mode(self):
        for options in ({'content_mode':'visual','visual_understanding':True},
                        {'content_mode':'subtitles','visual_understanding':False}):
            with self.subTest(options=options):
                self.assertEqual(self.client.post(self.route,json={**self.body,'options':options}).status_code,409)
        self.schedule.assert_not_called()

    def test_foreign_caption_path_does_not_enable_summary_retry(self):
        foreign = self.root/'foreign.json'; foreign.write_bytes(self.caption.read_bytes())
        storage.update_task(self.task.id,transcript_path=str(foreign))
        self.assertEqual(course_episodes.course_episodes(self.course)[0]['retry_kind'],'media')
        self.assertEqual(self.client.post(self.route,json=self.body).status_code,409)
        self.schedule.assert_not_called()

    def test_caption_transition_does_not_relax_source_or_handoff_identity(self):
        original = storage.get_task(self.task.id)
        for change in ({'page_url':'https://www.youtube.com/watch?v=other123456'},
                       {'learning_range':{'start':1,'end':5}}, {'mode':'download_only'},
                       {'handoff_id':'browser-handoff-fixture'}):
            with self.subTest(change=change):
                storage.update_task(self.task.id, **change)
                self.assertEqual(self.client.post(self.route,json=self.body).status_code,409)
                storage.save_task(original)
        unrelated = storage.create_task('current_page','Unrelated captions',page_url=original.page_url,
            mode='subtitle_only',handoff_id='browser-unrelated',options=original.options)
        with self.assertRaisesRegex(ValueError,'identity_conflict'):
            course_episodes.bind_course_episode(self.course,self.episode['episode_id'],unrelated.id)
        self.schedule.assert_not_called()

    def test_caption_episode_cannot_be_rebound_to_another_bilibili_part(self):
        course = courses.save_course('Synthetic parts',[{'kind':'url','url':'https://www.bilibili.com/video/BV1xx411c7mD?p=1'}])
        episode = course_episodes.course_episodes(course)[0]
        course_episodes.prepare_course_episode(course,episode['episode_id'])
        wrong = storage.create_task('current_page','Wrong part',page_url='https://www.bilibili.com/video/BV1xx411c7mD?p=2',
            mode='subtitle_only',handoff_id=episode['handoff_id'],options=self.task.options)
        with self.assertRaisesRegex(ValueError,'identity_conflict'):
            course_episodes.bind_course_episode(course,episode['episode_id'],wrong.id)

    def test_generation_mutation_cannot_interleave_validation_and_admission(self):
        attempted = threading.Event()
        original_callback = main.app.state.course_retry_summary
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = []
            def mutate_generation():
                attempted.set()
                return storage.update_task(self.task.id,retry_count=9,status='failed')
            def guarded_callback(*args):
                pending.append(pool.submit(mutate_generation))
                self.assertTrue(attempted.wait(2))
                with self.assertRaises(TimeoutError):
                    pending[0].result(timeout=.05)
                self.assertEqual(task_generation(storage.get_task(self.task.id)),self.body['generation'])
                return original_callback(*args)
            with patch.object(main.app.state,'course_retry_summary',side_effect=guarded_callback):
                result = self.client.post(self.route,json=self.body)
            self.assertEqual(result.status_code,200,result.text)
            pending[0].result(timeout=2)
        self.assertEqual(self.schedule.call_count,1)
        self.assertEqual(self.client.post(self.route,json=self.body).status_code,409)
        self.assertEqual(self.schedule.call_count,1)
