"""Explicit caption-upgrade consent and real task admission; no live services."""
import concurrent.futures
import hashlib
import json
import threading
import shutil
import subprocess
from unittest.mock import patch
import unittest
import test_course_learning as fixtures
from app import storage, courses, course_episodes, course_upgrades, course_upgrade_admission
from app.course_upgrade_links import upgrade_prefix


class CourseUpgradeTests(unittest.TestCase):
    setUp = fixtures.CourseLearningTests.setUp

    def prepare_upgrade(self):
        self.selected = {'base_url':'https://api.example.test/v1','model':'synthetic-vision','key':'fixture-only-key','fingerprint':'selected-v1'}
        self.connection = self.stack.enter_context(patch.object(course_upgrades,'connection',side_effect=lambda *args:dict(self.selected)))
        self.validation = self.stack.enter_context(patch.object(course_upgrade_admission,'validate_model'))
        self.dispatch = self.stack.enter_context(patch.object(course_upgrade_admission,'schedule_processing'))
        self.prefix = self.route.rsplit('/',1)[0]
        self.preview_body = {'revision':self.course['revision'],'base_url':self.selected['base_url'],'model':self.selected['model'],
            'options':{'content_mode':'visual','visual_understanding':True,'use_saved_connection':True,'resource_budget_mb':512,'summary_depth':'deep','frame_interval':1}}
        response = self.client.post(self.prefix+'/upgrade-preview',json=self.preview_body)
        self.assertEqual(response.status_code,200,response.text)
        self.review = response.json()
        self.apply_body = {'preview_id':self.review['preview_id'],'fingerprint':self.review['fingerprint'],
                           'confirm_download':True,'share_images':True}
        return self.review

    def test_preview_and_cancel_make_no_child_or_dispatch(self):
        original = self.task.model_dump(mode='json')
        review = self.prepare_upgrade()
        self.assertEqual(review['source_task_id'],self.task.id)
        self.assertEqual(review['page_url'],self.task.page_url)
        self.assertEqual(review['resource_budget_mb'],512)
        self.assertEqual(review['data_leaving_service'],['source_title','source_url','saved_caption_text','extracted_video_frames'])
        self.assertNotIn('fixture-only-key',str(review))
        self.assertEqual(len(storage.list_tasks_snapshot()),1)
        self.assertEqual(storage.get_task(self.task.id).model_dump(mode='json'),original)
        self.dispatch.assert_not_called()

        self.assertEqual(self.client.delete(self.prefix+'/upgrade-preview/'+review['preview_id']).status_code,200)
        self.assertEqual(self.client.post(self.prefix+'/upgrade',json=self.apply_body).status_code,409)
        self.dispatch.assert_not_called()

    def test_model_metadata_preview_uses_shared_redaction_without_changing_download_source(self):
        from app.model_data_consent import model_source_text
        title = 'Synthetic source Authorization: Bearer synthetic-private-token'
        storage.update_task(self.task.id,title=title)
        review = self.prepare_upgrade()
        self.assertEqual(review['title'],title)
        self.assertEqual(review['page_url'],self.task.page_url)
        self.assertEqual(review['model_source'],{'title':model_source_text(title),'url':model_source_text(self.task.page_url)})
        self.assertNotIn('synthetic-private-token',review['model_source']['title'])
        self.assertEqual(storage.get_task(self.task.id).title,title)

    def test_original_browser_media_urls_are_not_inherited(self):
        from app.models import ActiveVideoInfo
        storage.update_task(self.task.id,active_video=ActiveVideoInfo(
            src='https://private.example.test/signed?token=synthetic-secret',
            frame_url='https://private.example.test/account',duration=12,current_time=7))
        self.prepare_upgrade()
        response = self.client.post(self.prefix+'/upgrade',json=self.apply_body)
        self.assertEqual(response.status_code,200,response.text)
        queued = self.dispatch.call_args.args[3]
        self.assertEqual((queued.active_video.src,queued.active_video.frame_url),('',''))
        self.assertEqual(queued.active_video.current_time,0)
        self.assertNotIn('synthetic-secret',queued.model_dump_json())

    def test_fresh_dual_consent_creates_one_linked_child_and_reuses_owned_captions(self):
        original = storage.get_task(self.task.id).model_dump(mode='json')
        files = [(p.read_bytes(),p.stat().st_mtime_ns) for p in (self.caption,self.note)]
        self.prepare_upgrade()
        for missing in ('confirm_download','share_images'):
            self.assertEqual(self.client.post(self.prefix+'/upgrade',json={**self.apply_body,missing:False}).status_code,409)
        self.assertEqual(len(storage.list_tasks_snapshot()),1)
        first = self.client.post(self.prefix+'/upgrade',json=self.apply_body)
        self.assertEqual(first.status_code,200,first.text)
        child_id = first.json()['task_id']; self.assertNotEqual(child_id,self.task.id)
        again = self.client.post(self.prefix+'/upgrade',json=self.apply_body)
        self.assertEqual(again.status_code,200,again.text)
        self.assertEqual(again.json()['task_id'],child_id); self.assertTrue(again.json()['deduplicated'])
        self.assertEqual(self.dispatch.call_count,1)
        queued = self.dispatch.call_args.args[3]
        self.assertEqual(queued.page_url,self.task.page_url)
        self.assertEqual(queued.browser_subtitles[0].text,'Synthetic lesson evidence explains the original episode without requiring media.')
        self.assertEqual((queued.cookies,queued.resources,queued.page_text),([],[],''))
        self.assertEqual(queued.options.resource_budget_mb,512); self.assertEqual(queued.options.summary_depth,'deep')
        self.assertTrue(queued.options.visual_understanding)
        self.assertEqual(storage.get_task(child_id).source_task_id,self.task.id)
        self.assertIsNone(storage.get_task(child_id).options.llm_api_key)
        self.assertEqual(storage.get_task(self.task.id).model_dump(mode='json'),original)
        self.assertEqual(files,[(p.read_bytes(),p.stat().st_mtime_ns) for p in (self.caption,self.note)])
        episode = course_episodes.course_episodes(self.course)[0]
        self.assertEqual(episode['episode_id'],self.episode['episode_id']); self.assertEqual(episode['task_id'],self.task.id)
        self.assertEqual([item['task_id'] for item in episode['upgrades']],[child_id])
        self.assertIn(child_id,{item.get('id') for item in courses._evidence_sources(self.course)})

    def test_stale_source_model_paused_or_expired_review_never_dispatches(self):
        self.prepare_upgrade()
        original = self.caption.read_bytes()
        self.caption.write_bytes(original+b' ')
        self.assertEqual(self.client.post(self.prefix+'/upgrade',json=self.apply_body).status_code,409)
        self.caption.write_bytes(original)
        self.selected['fingerprint']='changed'
        self.assertEqual(self.client.post(self.prefix+'/upgrade',json=self.apply_body).status_code,409)
        self.selected['fingerprint']='selected-v1'
        courses.save_course(self.course['title'],self.course['sources'],True,self.course['id'],self.course['revision'])
        self.assertEqual(self.client.post(self.prefix+'/upgrade',json=self.apply_body).status_code,409)
        self.dispatch.assert_not_called()
        self.assertEqual(len(storage.list_tasks_snapshot()),1)

    def test_wrong_scope_or_review_fingerprint_cannot_authorize_upgrade(self):
        self.prepare_upgrade()
        other = courses.save_course('Other course',self.course['sources'])
        path = self.prefix.replace(self.course['id'],other['id'])+'/upgrade'
        self.assertEqual(self.client.post(path,json=self.apply_body).status_code,409)
        self.assertEqual(self.client.post(self.prefix+'/upgrade',json={**self.apply_body,'fingerprint':'0'*64}).status_code,409)
        self.dispatch.assert_not_called()

    def test_expired_review_and_inline_model_overrides_are_rejected(self):
        self.prepare_upgrade()
        for key,value in (('llm_api_key','not-allowed'),('llm_base_url','https://other.test'),('llm_model','other')):
            body = {**self.preview_body,'options':{**self.preview_body['options'],key:value}}
            self.assertEqual(self.client.post(self.prefix+'/upgrade-preview',json=body).status_code,409)
        with patch.object(course_upgrades.time,'monotonic',return_value=10**20):
            self.assertEqual(self.client.post(self.prefix+'/upgrade',json=self.apply_body).status_code,409)
        self.dispatch.assert_not_called()

    def test_concurrent_review_submission_only_admits_once(self):
        self.prepare_upgrade()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.client.post(self.prefix+'/upgrade',json=self.apply_body),range(4)))
        self.assertEqual({r.status_code for r in results},{200})
        self.assertEqual(len({r.json()['task_id'] for r in results}),1)
        self.assertEqual(self.dispatch.call_count,1)

    def test_other_review_cannot_redownload_an_active_or_media_backed_child(self):
        self.prepare_upgrade()
        second = self.client.post(self.prefix+'/upgrade-preview',json=self.preview_body).json()
        result = self.client.post(self.prefix+'/upgrade',json=self.apply_body)
        self.assertEqual(result.status_code,200,result.text)
        child_id = result.json()['task_id']
        second_apply = {**self.apply_body,'preview_id':second['preview_id'],'fingerprint':second['fingerprint']}
        self.assertEqual(self.client.post(self.prefix+'/upgrade',json=second_apply).status_code,409)
        self.assertEqual(self.client.post(self.prefix+'/upgrade-preview',json=self.preview_body).status_code,409)
        media = storage.task_dir(child_id)/'saved.mp4'; media.write_bytes(b'synthetic retained media')
        storage.update_task(child_id,status='failed',media_path=str(media))
        self.assertEqual(self.client.post(self.prefix+'/upgrade-preview',json=self.preview_body).status_code,409)
        self.assertFalse(course_episodes.course_episodes(self.course)[0]['caption_upgrade_available'])
        self.assertEqual(self.dispatch.call_count,1)

    def test_child_membership_cannot_attach_to_another_episode(self):
        self.prepare_upgrade()
        result = self.client.post(self.prefix+'/upgrade',json=self.apply_body)
        self.assertEqual(result.status_code,200,result.text)
        child_id = result.json()['task_id']
        other = courses.save_course('Other course',self.course['sources'])
        self.assertEqual(course_episodes.course_episodes(other)[0]['upgrades'],[])
        storage.update_task(child_id,page_url='https://www.youtube.com/watch?v=wrong123456')
        with self.assertRaisesRegex(ValueError,'identity_conflict'):
            course_episodes.course_episodes(self.course)

    def test_real_synthetic_media_pipeline_keeps_original_and_avoids_asr(self):
        self.run_media_fixture()

    def test_partial_reviewed_captions_cannot_fall_through_to_remote_asr(self):
        self.run_media_fixture(partial=True)

    def test_reviewed_cue_upper_bound_uses_physical_media_tolerance_only(self):
        from app.course_upgrade_captions import require_reviewed_coverage
        from app.models import BrowserSubtitleCue
        from app.processor_state import ContentMismatchError
        cue = BrowserSubtitleCue(start=0,end=12.01,text='Reviewed synthetic evidence')
        require_reviewed_coverage([cue],12,lambda *_:True)
        self.assertEqual(cue.end,12.01)
        for end in (12.010000001,120):
            with self.subTest(end=end), self.assertRaises(ContentMismatchError):
                require_reviewed_coverage([cue.model_copy(update={'end':end})],12,lambda *_:True)

    def test_overlong_reviewed_captions_reject_changed_media_before_summary(self):
        self.run_media_fixture(overlong=True)

    def test_tampered_reviewed_captions_reject_before_download_and_resume(self):
        self.run_media_fixture(tamper=True)

    def test_new_requests_forbid_extra_fields_and_nonboolean_consent(self):
        self.prepare_upgrade()
        for key in ('confirm_download', 'share_images'):
            for value in ('true', 1, None):
                self.assertEqual(self.client.post(self.prefix+'/upgrade',json={**self.apply_body,key:value}).status_code,422)
        self.assertEqual(self.client.post(self.prefix+'/upgrade',json={**self.apply_body,'cookie':'unreviewed'}).status_code,422)
        self.assertEqual(self.client.post(self.prefix+'/upgrade-preview',json={**self.preview_body,'page_text':'unreviewed'}).status_code,422)
        self.dispatch.assert_not_called()

    def test_new_openapi_operations_and_request_schemas_are_explicit(self):
        from app import main
        schema = main.app.openapi()
        base = '/api/courses/{course_id}/episodes/{episode_id}/'
        for suffix, method, model in (
            ('retry','post','EpisodeRetry'), ('upgrade-preview','post','EpisodeUpgradePreview'),
            ('upgrade-preview/{preview_id}','delete',None), ('upgrade','post','EpisodeUpgrade')):
            self.assertEqual(set(schema['paths'][base+suffix]),{method})
            if model:
                request = schema['paths'][base+suffix][method]['requestBody']
                self.assertTrue(request['required'])
                self.assertEqual(request['content']['application/json']['schema']['$ref'],'#/components/schemas/'+model)
        for name, required in (
            ('EpisodeRetry',{'revision','task_id','generation','options'}),
            ('EpisodeUpgradePreview',{'revision','options','base_url','model'}),
            ('EpisodeUpgrade',{'preview_id','fingerprint','confirm_download','share_images'})):
            model = schema['components']['schemas'][name]
            self.assertIs(model['additionalProperties'],False)
            self.assertEqual(set(model['required']),required)
        properties = schema['components']['schemas']['EpisodeUpgrade']['properties']
        for name in ('confirm_download','share_images'):
            self.assertEqual(properties[name]['type'],'boolean')
            self.assertNotIn('default',properties[name])

    def run_media_fixture(self, *, partial=False, tamper=False, overlong=False):
        from app import processor
        from app.runtime import ffmpeg_bin, hidden_subprocess_kwargs
        from app.models import ResourceCandidate
        ffmpeg = ffmpeg_bin()
        if not ffmpeg:
            self.skipTest('FFmpeg is required for the synthetic media fixture')
        media = self.root/'fixture.mp4'
        subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-f','lavfi','-i',
            'testsrc2=size=320x180:rate=5','-f','lavfi','-i','sine=frequency=440:sample_rate=16000',
            '-t','12','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',
            '-c:a','aac','-shortest',str(media)],check=True,capture_output=True,**hidden_subprocess_kwargs())
        if partial or overlong:
            data = json.loads(self.caption.read_text(encoding='utf-8'))
            data['segments'][0]['end'] = 120 if overlong else 1
            self.caption.write_text(json.dumps(data),encoding='utf-8')
        original = [(p.read_bytes(),p.stat().st_mtime_ns) for p in (self.caption,self.note)]
        self.prepare_upgrade()
        response = self.client.post(self.prefix+'/upgrade',json=self.apply_body)
        self.assertEqual(response.status_code,200,response.text)
        child_id = response.json()['task_id']
        queued = self.dispatch.call_args.args[3]
        queued.options.transcriber = 'openai-compatible'
        if tamper:
            (storage.task_dir(child_id)/'course-upgrade-captions.json').write_text('[]',encoding='utf-8')
        downloads = []
        def download(downloader,page_url,resources,cookies,title):
            self.assertEqual(page_url,self.task.page_url)
            self.assertEqual((resources,cookies),([],[]))
            downloader.resolved_title = 'Unreviewed downloader title'
            target = downloader.download_dir/'synthetic.mp4'
            shutil.copyfile(media,target); downloads.append(page_url)
            return target,ResourceCandidate(url='https://cdn.example.test/synthetic.mp4',kind='video')
        def summary(title,transcript,grids,options,*args,**kwargs):
            self.assertEqual(title,self.task.title)
            self.assertTrue(grids,'Actual video frames must reach the deterministic fixture')
            self.assertEqual(transcript.full_text,'Synthetic lesson evidence explains the original episode without requiring media.')
            return '# Synthetic visual upgrade\n\n'+transcript.full_text+'\n\n[00:00]', 'offline-fixture', '', []
        with patch.object(processor,'llm_model_supports_vision',return_value=True), \
             patch.object(processor,'maybe_download_page_subtitle',side_effect=AssertionError('No alternate subtitle request')) as subtitle_fetch, \
             patch.object(processor.MediaDownloader,'download',autospec=True,side_effect=download), \
             patch.object(processor,'summarize_with_diagnostics',side_effect=summary) as summarize, \
             patch.object(processor,'transcribe_audio',side_effect=AssertionError('Owned captions must avoid ASR')) as asr, \
             patch.object(processor,'transcribe_audio_openai_compatible',side_effect=AssertionError('No remote ASR consent')) as remote_asr:
            processor.process_current_page_task(child_id,queued)
            subtitle_fetch.assert_not_called()
            asr.assert_not_called()
            remote_asr.assert_not_called()
            if partial or tamper or overlong:
                child = storage.get_task(child_id)
                self.assertEqual(child.status,'failed')
                self.assertEqual(child.error_code,'media_mismatch',child.model_dump())
                summarize.assert_not_called()
                processor.process_local_video_task(child_id,media,queued.title,queued.options)
                self.assertEqual(storage.get_task(child_id).error_code,'media_mismatch')
                saved = storage.task_dir(child_id)/'transcript.json'
                shutil.copyfile(self.caption,saved)
                storage.update_task(child_id,transcript_path=str(saved))
                processor.process_saved_transcript_task(child_id,queued.options.model_copy(update={'content_mode':'text','visual_understanding':False}))
                summarize.assert_not_called()
                asr.assert_not_called()
                remote_asr.assert_not_called()
                self.assertEqual(len(downloads),0 if tamper else 1)
                self.assertEqual(original,[(p.read_bytes(),p.stat().st_mtime_ns) for p in (self.caption,self.note)])
                return
        child = storage.get_task(child_id)
        self.assertEqual(child.status,'success',child.model_dump())
        self.assertEqual(child.source_task_id,self.task.id)
        self.assertTrue(child.frame_grids)
        self.assertEqual(len(downloads),1)
        self.assertEqual(original,[(p.read_bytes(),p.stat().st_mtime_ns) for p in (self.caption,self.note)])
        again = self.client.post(self.prefix+'/upgrade',json=self.apply_body)
        self.assertEqual(again.status_code,200,again.text)
        self.assertEqual(again.json()['task_id'],child_id)
        self.assertEqual(self.dispatch.call_count,1)
