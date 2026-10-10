from __future__ import annotations

from contextlib import ExitStack, closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image
from fastapi import BackgroundTasks

from app.models import ScreenSubtitleSettings, TaskOptions, TranscriptResult, TranscriptSegment, TaskRecord
from app.processor_state import TaskCancelled
from app.screen_subtitles import extract, as_transcript, _merge, _targets, ScreenOcrError


class ScreenSubtitleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.media = self.root / 'video.mp4'
        self.media.write_bytes(b'synthetic-media-identity')
        self.settings = ScreenSubtitleSettings()
        self.identity = {'engine': 'test-runtime-v1', 'model': 'test-sha'}
        self.calls = []
        self.stack = ExitStack()
        self.stack.enter_context(patch('app.screen_subtitles.media_info', return_value={'duration': 130., 'width': 640, 'height': 360}))
        self.stack.enter_context(patch('app.screen_subtitles.sample_frames', side_effect=self.frames))

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def frames(self, path, targets, settings, cancel_check):
        for target in targets:
            cancel_check()
            self.calls.append(target)
            yield target, target, Image.new('RGB', (640, 94), 'white'), (0, 266, 640, 360)

    def engine(self, image):
        return [([[10, 10], [300, 10], [300, 50], [10, 50]], '学习率 Learning rate', .79)], .01

    def run_extract(self, **kwargs):
        return extract(self.media, kwargs.pop('settings', self.settings), self.root / 'cache', engine=self.engine, identity=kwargs.pop('identity', self.identity), **kwargs)

    def test_entire_timeline_more_than_twenty_four_frames_and_exact_fingerprint(self):
        original = self.media.read_bytes()
        report = self.run_extract()
        self.assertEqual(report['status'], 'ready')
        self.assertEqual(len(self.calls), 260)
        self.assertEqual(report['total_windows'], 3)
        self.assertEqual(report['cues'][0]['end'], 130)
        self.assertEqual(report['cues'][0]['lines'][0]['bbox'][0], [10, 276])
        self.assertTrue(report['cues'][0]['lines'][0]['uncertain'])
        self.assertEqual(report['cues'][0]['verification'], 'unreviewed')
        again = self.run_extract()
        self.assertEqual(again['cache_hits'], 3)
        self.assertEqual(len(self.calls), 260)
        changed = self.run_extract(settings=ScreenSubtitleSettings(crop_top=.6))
        self.assertNotEqual(changed['fingerprint'], report['fingerprint'])
        self.assertEqual(changed['cache_hits'], 0)
        changed_engine = self.run_extract(identity={'engine': 'test-runtime-v2'})
        self.assertEqual(changed_engine['cache_hits'], 0)
        changed_interval = self.run_extract(settings=ScreenSubtitleSettings(interval_seconds=1))
        self.assertEqual(changed_interval['sample_count'], 130)
        self.assertEqual(changed_interval['cache_hits'], 0)
        self.assertEqual(self.media.read_bytes(), original)
        transcript = as_transcript(report)
        self.assertEqual(transcript.source, 'screen-ocr')
        self.assertTrue(transcript.provenance['coverage']['complete'])
        self.assertIn('未人工核验', transcript.warning)

    def test_cancel_mid_window_restarts_only_verified_windows(self):
        def cancel():
            if len(self.calls) >= 130:
                raise TaskCancelled('fixture')
        with self.assertRaises(TaskCancelled):
            self.run_extract(cancel_check=cancel)
        self.assertEqual(len(list((self.root / 'cache').glob('*/window-*.json'))), 1)
        self.calls.clear()
        report = self.run_extract()
        self.assertEqual(report['cache_hits'], 1)
        self.assertEqual(len(self.calls), 140)
        self.assertEqual(self.calls[0], 60)
        self.assertTrue(report['coverage']['complete'])

    def test_corrupt_or_incomplete_windows_are_recomputed_and_reported(self):
        first = self.run_extract()
        files = sorted((self.root / 'cache' / first['fingerprint']).glob('window-*.json'))
        files[1].write_text('{broken')
        self.calls.clear()
        result = self.run_extract()
        self.assertEqual(result['cache_hits'], 2)

        self.assertEqual(result['invalid_cache_windows'], [1])
        self.assertEqual(len(self.calls), 120)
        payload = json.loads(files[0].read_text())
        payload['samples'][0]['lines'][0]['text'] = 'changed silently'
        files[0].write_text(json.dumps(payload))
        result = self.run_extract()
        self.assertEqual(result['invalid_cache_windows'], [0])
        self.assertEqual(result['cache_hits'], 2)

    def test_corrupt_manifest_invalidates_all_windows_instead_of_silent_reuse(self):
        first = self.run_extract()
        (self.root / 'cache' / first['fingerprint'] / 'manifest.json').write_text('{broken')
        result = self.run_extract()
        self.assertTrue(result['invalid_cache_manifest'])
        self.assertEqual(result['cache_hits'], 0)
        self.assertEqual(result['invalid_cache_windows'], [0, 1, 2])

    def test_media_replaced_does_not_resume_under_same_task_identity(self):
        first = self.run_extract()
        self.media.write_bytes(b'changed-media')
        with self.assertRaisesRegex(ScreenOcrError, 'media_changed'):
            self.run_extract(expected_media_sha256=first['media_sha256'])
        result = self.run_extract()
        self.assertEqual(result['cache_hits'], 0)

    def test_failed_window_is_partial_and_never_cached_or_marked_complete(self):
        original = self.frames
        def truncated(path, targets, settings, cancel_check):
            if targets[0] == 60:
                yield from original(path, targets[:5], settings, cancel_check)
                raise ScreenOcrError('video_truncated')
            yield from original(path, targets, settings, cancel_check)
        with patch('app.screen_subtitles.sample_frames', side_effect=truncated):
            report = self.run_extract()
        self.assertEqual(report['status'], 'partial')
        self.assertFalse(report['coverage']['complete'])
        self.assertEqual(report['coverage']['sampled_seconds'], 60)
        self.assertEqual(report['failed_windows'][0]['error'], 'video_truncated')
        self.assertEqual(len(list((self.root / 'cache').glob('*/window-*.json'))), 1)
        self.assertEqual(self.run_extract()['cache_hits'], 1)

    def test_empty_failed_and_language_filtered_are_distinct(self):
        with patch.object(self, 'engine', return_value=([], .01)):
            empty = self.run_extract(identity={'engine': 'empty'})
        self.assertEqual(empty['status'], 'empty')
        self.assertTrue(empty['coverage']['complete'])
        self.assertEqual(empty['cues'], [])
        with patch.object(self, 'engine', side_effect=RuntimeError('engine failed')):
            failed = self.run_extract(identity={'engine': 'broken'})
        self.assertEqual(failed['status'], 'failed')
        self.assertFalse(failed['coverage']['complete'])
        with patch.object(self, 'engine', return_value=([([[0,0],[30,0],[30,10],[0,10]], 'English', .9)], .01)):
            filtered = self.run_extract(settings=ScreenSubtitleSettings(language='zh'))
        self.assertEqual(filtered['status'], 'empty')
        window = next((self.root / 'cache' / filtered['fingerprint']).glob('window-*.json'))
        self.assertEqual(json.loads(window.read_text())['samples'][0]['lines'][0]['text'], 'English')
        self.assertFalse(json.loads(window.read_text())['samples'][0]['lines'][0]['selected'])

    def test_blank_gaps_changes_and_uncertainty_survive_merge(self):
        samples = []
        for i, text in enumerate(['A', 'A', '', 'A', 'B', 'B']):
            samples.append({'timestamp': i * .5, 'lines': [{'text':text, 'selected':True, 'confidence': .6 + i*.01}] if text else []})
        cues=[]
        _merge(cues, samples, .5, 3)
        self.assertEqual([(v['start'],v['end'],v['text']) for v in cues], [(0,1,'A'),(1.5,2,'A'),(2,3,'B')])
        self.assertEqual(cues[0]['confidence'], .6)
        self.assertEqual(_targets(60, 120, 7), [63,70,77,84,91,98,105,112,119])


class ScreenSubtitleTaskTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.stack = ExitStack()
        for target in ('app.storage.TASK_DIR', 'app.observability.TASK_DIR'):
            self.stack.enter_context(patch(target, self.root / 'tasks'))
        self.stack.enter_context(patch('app.storage.ensure_dirs', lambda: None))
        self.media = self.root / 'source.mp4'
        self.media.write_bytes(b'owned-video')
        from app.storage import create_task, update_task, write_json
        self.source = create_task('local', 'Original title', options=TaskOptions(content_mode='text'))
        self.transcript = write_json(self.source.id, 'transcript.json', TranscriptResult(source='faster-whisper',full_text='Original ASR').model_dump())
        self.note = self.root / 'tasks' / self.source.id / 'note.md'
        self.note.write_text('Original note')
        self.source = update_task(self.source.id, status='success', source_media_path=str(self.media), transcript_path=str(self.transcript), note_path=str(self.note))

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def test_opt_in_new_task_preserves_source_and_skips_model_readiness(self):
        from app.screen_subtitle_routes import create_screen_subtitles, ScreenSubtitleRequest
        from app.storage import get_task
        with patch('app.screen_subtitle_routes.schedule_processing') as schedule, patch('app.screen_subtitle_routes.require_ready_note_model') as ready:
            result = create_screen_subtitles(self.source.id, ScreenSubtitleRequest(), BackgroundTasks())
        ready.assert_not_called()
        self.assertNotEqual(result['task_id'], self.source.id)
        task = get_task(result['task_id'])
        self.assertEqual(task.mode, 'screen_subtitles')
        self.assertEqual(task.options.content_mode, 'subtitles')
        self.assertEqual(task.source_task_id, self.source.id)
        self.assertEqual(schedule.call_args.kwargs['_queue_kind'], 'screen_ocr')
        self.assertEqual(get_task(self.source.id).note_path, str(self.note))
        self.assertEqual(self.note.read_text(), 'Original note')
        self.assertEqual(json.loads(self.transcript.read_text())['full_text'], 'Original ASR')

    def test_resume_dispatches_ocr_and_rejects_settings_change(self):
        from app.screen_subtitle_routes import create_screen_subtitles, ScreenSubtitleRequest, resume_screen_subtitles
        from app.storage import update_task
        from fastapi import HTTPException
        with patch('app.screen_subtitle_routes.schedule_processing'):
            result=create_screen_subtitles(self.source.id, ScreenSubtitleRequest(), BackgroundTasks())
        task_id=result['task_id']
        update_task(task_id,status='cancelled',cancel_requested=True)
        with self.assertRaises(HTTPException):
            resume_screen_subtitles(task_id, BackgroundTasks(), TaskOptions(screen_subtitles=ScreenSubtitleSettings(crop_top=.5)))
        with patch('app.screen_subtitle_routes.schedule_processing') as schedule, patch('app.screen_subtitle_routes.require_ready_note_model') as ready:
            from app.main import resume_task_from_checkpoint
            resumed=resume_task_from_checkpoint(task_id, BackgroundTasks(), None)
        self.assertTrue(resumed['resumed'])
        self.assertEqual(schedule.call_args.kwargs['_queue_kind'], 'screen_ocr')
        ready.assert_not_called()

    def test_cancelled_ocr_range_before_clipping_resumes_range_before_ocr(self):
        from app.screen_subtitle_routes import create_screen_subtitles, ScreenSubtitleRequest
        from app.storage import update_task
        from app.main import resume_task_from_checkpoint
        with patch('app.screen_subtitle_routes.schedule_processing'):
            created=create_screen_subtitles(self.source.id,ScreenSubtitleRequest(),BackgroundTasks())
        update_task(created['task_id'],status='cancelled',checkpoint='screen_subtitles_range_pending',learning_range={'start':10,'end':20,'original_start':70,'original_end':80})
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            create_screen_subtitles(created['task_id'],ScreenSubtitleRequest(),BackgroundTasks())
        with patch('app.screen_subtitle_routes.schedule_processing') as schedule:
            result=resume_task_from_checkpoint(created['task_id'],BackgroundTasks(),None)
        self.assertTrue(result['resumed'])
        self.assertEqual(schedule.call_args.kwargs['_queue_kind'],'range')
        self.assertEqual(schedule.call_args.args[1].__name__,'process_range_task')
        self.assertEqual(schedule.call_args.args[3],self.media)

    def test_preview_error_does_not_disclose_exception_text(self):
        from app.screen_subtitle_routes import preview_screen_subtitles, ScreenSubtitlePreviewRequest
        from fastapi import HTTPException
        with patch('app.screen_subtitle_routes.preview',side_effect=ScreenOcrError('/private/fixture/path')):
            with self.assertRaises(HTTPException) as raised:
                preview_screen_subtitles(self.source.id,ScreenSubtitlePreviewRequest())
        self.assertEqual(raised.exception.detail['code'],'screen_ocr_preview_failed')
        self.assertNotIn('/private',str(raised.exception.detail))

    def test_partial_saved_ocr_cannot_generate_summary(self):
        from app.storage import write_json,update_task,get_task
        from app.processor import process_saved_transcript_task
        transcript = TranscriptResult(source='screen-ocr', full_text='Partial text',segments=[TranscriptSegment(start=0,end=1,text='Partial text')],provenance={'status':'partial','coverage':{'complete':False}})
        path=write_json(self.source.id,'transcript.json',transcript.model_dump())
        update_task(self.source.id,transcript_path=str(path))
        with patch('app.processor.summarize_with_diagnostics') as summarize:
            process_saved_transcript_task(self.source.id,TaskOptions(content_mode='text'))
        summarize.assert_not_called()
        self.assertEqual(get_task(self.source.id).status,'failed')
        self.assertEqual(self.note.read_text(),'Original note')

    def test_offline_queue_recovery_uses_ocr_processor(self):
        from app.task_queue import LocalTaskQueue, recover_processing, queue_for
        task=TaskRecord(id='ocrfixture',source_type='local',mode='screen_subtitles',title='OCR',source_media_path=str(self.media),options=TaskOptions(content_mode='subtitles',screen_subtitles=ScreenSubtitleSettings()),status='running',created_at='2026-10-10',updated_at='2026-10-10')
        queue=LocalTaskQueue(self.root)
        with closing(sqlite3.connect(queue.path)) as db:
            db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at) VALUES ('ocrfixture','screen_ocr',0,'running',0)")
            db.commit()
        event=threading.Event()
        with patch('app.storage.get_task',return_value=task), patch('app.storage.update_task'), patch('app.screen_subtitle_tasks.process_screen_subtitle_task',side_effect=lambda *a:event.set()) as processor, patch('app.processor.process_local_video_task') as asr:
            recovered=recover_processing(self.root)
            self.assertTrue(event.wait(5))
            queue_for(self.root).stop()
        self.assertEqual(recovered['recovered'],1)
        processor.assert_called_once()
        asr.assert_not_called()
        queue.stop()

class ScreenSubtitleProcessorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        for target in ('app.storage.TASK_DIR','app.observability.TASK_DIR'):
            self.stack.enter_context(patch(target,self.root/'tasks'))
        self.stack.enter_context(patch('app.storage.ensure_dirs',lambda:None))
        from app.storage import create_task,update_task
        self.media=self.root/'video.mp4';self.media.write_bytes(b'fixture')
        self.options=TaskOptions(content_mode='subtitles',screen_subtitles=ScreenSubtitleSettings())
        self.task=create_task('local','OCR',options=self.options,mode='screen_subtitles')
        update_task(self.task.id,source_media_path=str(self.media))

    def tearDown(self):
        self.stack.close();self.temp.cleanup()

    def report(self,status='ready'):
        return {'media':{'duration':130,'width':640,'height':360},'media_sha256':hashlib.sha256(self.media.read_bytes()).hexdigest(),
            'fingerprint':'a'*64,'settings':self.options.screen_subtitles.model_dump(),'engine':{'version':'fixture'},'warning':'画面字幕 OCR 未人工核验',
            'status':status,'completed_windows':3 if status=='ready' else 1,'total_windows':3,'cache_hits':0,
            'coverage':{'complete':status=='ready','sampled_seconds':130 if status=='ready' else 60,'requested_seconds':130},
            'cues':[{'start':0.,'end':.5,'text':'学习率'}] if status !='empty' else []}

    def test_extraction_only_never_downloads_transcribes_or_summarizes(self):
        from app.screen_subtitle_tasks import process_screen_subtitle_task
        from app.storage import get_task,task_dir
        with patch('app.screen_subtitle_tasks.extract',return_value=self.report()),patch('app.processor.process_saved_transcript_task') as summary,patch('app.processor.transcribe_audio') as asr,patch('app.processor.MediaDownloader') as download:
            process_screen_subtitle_task(self.task.id,self.media,self.options)
        summary.assert_not_called();asr.assert_not_called();download.assert_not_called()
        task=get_task(self.task.id)
        self.assertEqual(task.status,'success');self.assertEqual(task.mode,'screen_subtitles')
        self.assertEqual(task.summary_source,'screen-ocr-extract')
        self.assertIn('OCR',Path(task.note_path).read_text())
        self.assertEqual(json.loads(Path(task.transcript_path).read_text())['source'],'screen-ocr')
        self.assertTrue((task_dir(task.id)/'resource_usage.json').exists())

    def test_empty_or_partial_are_failed_and_cannot_call_model(self):
        from app.screen_subtitle_tasks import process_screen_subtitle_task
        from app.storage import get_task,update_task
        options=self.options.model_copy(update={'content_mode':'text'})
        for status in ('partial','empty','failed'):
            with self.subTest(status=status):
                update_task(self.task.id,status='queued')
                with patch('app.screen_subtitle_tasks.extract',return_value=self.report(status)),patch('app.processor.process_saved_transcript_task') as summary:
                    process_screen_subtitle_task(self.task.id,self.media,options)
                summary.assert_not_called()
                task=get_task(self.task.id)
                self.assertEqual(task.status,'failed')
                self.assertIn(task.error_code,{'screen_ocr_empty','screen_ocr_incomplete'})

    def test_ocr_range_transcript_and_note_explain_original_time_offset(self):
        from app.screen_subtitle_tasks import process_screen_subtitle_task
        from app.storage import update_task,get_task
        update_task(self.task.id,source_task_id='original-ocr',learning_range={'start':10,'end':20,'original_start':70,'original_end':80})
        with patch('app.screen_subtitle_tasks.extract',return_value=self.report()):
            process_screen_subtitle_task(self.task.id,self.media,self.options)
        task=get_task(self.task.id)
        transcript=json.loads(Path(task.transcript_path).read_text())
        self.assertEqual(transcript['provenance']['source_task_id'],'original-ocr')
        self.assertEqual(transcript['provenance']['original_time_offset'],70)
        self.assertIn('原视频 70 秒',Path(task.note_path).read_text())

    def test_ocr_prompt_and_generated_note_keep_uncertainty_and_source(self):
        from app.screen_subtitles import as_transcript
        from app.storage import write_json,update_task,get_task
        from app.processor import process_saved_transcript_task
        from app.summarizer import _evidence_contract
        transcript=as_transcript(self.report())
        self.assertIn('screen-ocr',_evidence_contract(transcript,[]))
        path=write_json(self.task.id,'transcript.json',transcript.model_dump())
        update_task(self.task.id,transcript_path=str(path),media_path=str(self.media),screen_subtitles_media_sha256=transcript.provenance['media_sha256'])
        with patch('app.processor.summarize_with_diagnostics',return_value=('# OCR\n\n学习率。','text-llm','',[])):
            process_saved_transcript_task(self.task.id,TaskOptions(content_mode='text'))
        task=get_task(self.task.id)
        self.assertEqual(task.status,'success')
        self.assertEqual(task.summary_diagnostics['source_quality'],'unreviewed')
        self.assertEqual(task.summary_diagnostics['evidence_quality'],'screen_ocr')
        note=Path(task.note_path).read_text()
        self.assertIn('画面字幕 OCR（未人工核验）',note)
        self.assertNotIn('已保存的音频转写',note)

    def test_literal_ocr_quote_is_direct_match_but_remains_unreviewed_evidence(self):
        from app.claims import build_claim_evidence_map, safe_claim_projection
        transcript=TranscriptResult(source='screen-ocr',full_text='学习率影响梯度下降',segments=[TranscriptSegment(start=0,end=1,text='学习率影响梯度下降')])
        result=build_claim_evidence_map('same-task','课程','# 课程\n\n学习率影响梯度下降。',transcript)
        self.assertEqual(result['claims'][0]['verification'],'direct')
        self.assertEqual(result['evidence'][0]['source'],'screen-ocr')
        self.assertEqual(result['evidence'][0]['verification'],'unreviewed')
        public=safe_claim_projection(result)
        self.assertEqual(public['evidence'][0]['verification'],'unreviewed')
        speech=build_claim_evidence_map('same-task','课程','# 课程\n\n学习率影响梯度下降。',transcript.model_copy(update={'source':'faster-whisper'}))
        self.assertNotEqual(result['evidence_revision'],speech['evidence_revision'])


class ScreenSubtitleDecoderTests(unittest.TestCase):
    def test_real_low_fps_mp4_samples_displayed_frame_and_valid_tail(self):
        try:
            import av
        except ImportError:
            self.skipTest('Optional PyAV runtime is not installed')
        from app.screen_subtitles import sample_frames
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'one-fps.mp4'
            colors=[(220,20,20),(20,220,20),(20,20,220),(220,220,20)]
            with av.open(str(path),'w') as output:
                stream=output.add_stream('libx264',rate=1);stream.width=64;stream.height=48;stream.pix_fmt='yuv420p'
                for color in colors:
                    for packet in stream.encode(av.VideoFrame.from_image(Image.new('RGB',(64,48),color))):
                        output.mux(packet)
                for packet in stream.encode():output.mux(packet)
            samples=list(sample_frames(path,[i*.25 for i in range(16)],ScreenSubtitleSettings(interval_seconds=.25)))
            self.assertEqual(len(samples),16)
            self.assertEqual([row[1] for row in samples],[float(i//4) for i in range(16)])
            for index,(_,_,image,_) in enumerate(samples):
                actual=image.getpixel((4,4))
                self.assertTrue(all(abs(actual[n]-colors[index//4][n])<8 for n in range(3)))
            with self.assertRaisesRegex(ScreenOcrError,'video_truncated'):
                list(sample_frames(path,[3.75,4.25],ScreenSubtitleSettings(interval_seconds=.25)))

    def test_ocr_range_retains_settings_and_uses_clip_ocr_not_asr(self):
        from app.models import TaskRecord,MediaIntegrity
        from app.range_learning import create_range_task,process_range_task
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=root/'owned.mp4';path.write_bytes(b'owned')
            settings=ScreenSubtitleSettings(crop_top=.6,language='zh')
            source=TaskRecord(id='original',source_type='local',mode='screen_subtitles',title='OCR',created_at='',updated_at='',media_path=str(path),options=TaskOptions(content_mode='subtitles',screen_subtitles=settings),media_integrity=MediaIntegrity(duration=200),learning_range={'original_start':60})
            created=source.model_copy(update={'id':'range-result','mode':'rerun_from_media'})
            with patch('app.range_learning.DATA_DIR',root),patch('app.range_learning.get_task',return_value=source),patch('app.range_learning.create_task',return_value=created),patch('app.range_learning.update_task',side_effect=lambda key,**kw:created.model_copy(update=kw)),patch('app.range_learning.schedule_processing') as schedule:
                result=create_range_task(source.id,10,20,TaskOptions(content_mode='subtitles'),None)
            chosen=schedule.call_args.args[5]
            self.assertEqual(chosen.screen_subtitles,settings)
            self.assertEqual(result.learning_range['original_start'],70)
            clip=root/'selected-range.mp4';clip.write_bytes(b'synthetic-clip')
            with patch('app.range_learning.get_task',return_value=result),patch('app.range_learning.task_dir',return_value=root),patch('app.range_learning.update_task') as update,patch('app.processor_state.check_cancel'),patch('app.range_learning.extract_video_clip') as clipper,patch('app.screen_subtitle_tasks.process_screen_subtitle_task') as ocr,patch('app.processor.process_local_video_task') as asr,patch('app.range_learning.source_range_subtitles') as subtitles:
                process_range_task(result.id,path,result.title,chosen)
            clipper.assert_not_called();asr.assert_not_called();subtitles.assert_not_called()
            ocr.assert_called_once_with(result.id,clip,chosen.model_copy(update={'content_mode':'subtitles','visual_understanding':False,'local_ocr':False}))
            self.assertEqual(update.call_args.kwargs['mode'],'screen_subtitles')


if __name__ == '__main__':
    unittest.main()
