"""Explicit, short-lived review for a caption episode's first visual download."""
import hashlib
import math
import secrets
import threading
import time

from . import courses, storage
from .course_caption_state import owned_caption_path, eligible_source
from .course_learning import selected_episode
from .course_upgrade_links import upgrade_prefix, blocks_reacquisition
from .course_synthesis_model import connection
from .graph_snapshot import digest
from .models import CurrentPageTaskRequest, BrowserSubtitleCue, TranscriptResult, ActiveVideoInfo
from .source_input import normalize_source_input
from .model_data_consent import model_source_text

_lock = threading.RLock()
_previews = {}
PREVIEW_SECONDS = 600
MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024

def _capture(course_id, episode_id, revision):
    _, episode, task = selected_episode(course_id, episode_id, revision)
    if not eligible_source(task):
        raise ValueError('course_upgrade_unavailable')
    path = owned_caption_path(task)
    if path.stat().st_size > MAX_TRANSCRIPT_BYTES:
        raise ValueError('course_upgrade_unavailable')
    raw = path.read_bytes()
    transcript = TranscriptResult.model_validate_json(raw)
    if transcript.source not in {'browser-subtitle','page-subtitle','platform-subtitle'} or not transcript.segments or len(transcript.segments) > 20000:
        raise ValueError('course_upgrade_unavailable')
    cues = []
    for segment in transcript.segments:
        if not (math.isfinite(segment.start) and math.isfinite(segment.end) and 0 <= segment.start < segment.end and segment.text.strip()):
            raise ValueError('course_upgrade_unavailable')
        cues.append(BrowserSubtitleCue(start=segment.start,end=segment.end,text=segment.text))
    normalized = normalize_source_input(task.page_url)
    source_url = normalized.url
    if ((task.source_identity.platform and task.source_identity.platform != normalized.platform)
            or (task.source_identity.platform_id and task.source_identity.platform_id != normalized.source_id)):
        raise ValueError("course_episode_identity_conflict")
    if task.source_identity.page_url and normalize_source_input(task.source_identity.page_url).url != source_url:
        raise ValueError('course_episode_identity_conflict')
    fingerprint = digest({'task':task.model_dump(mode='json'),'caption_sha256':hashlib.sha256(raw).hexdigest()})
    return task, cues, fingerprint, episode


def _scope(course_id, episode_id):
    return (str(courses.DATA_DIR.resolve()),course_id,episode_id)


def preview_upgrade(course_id, episode_id, request, *, validate_model):
    options = request.options
    if (options.content_mode != 'visual' or not options.visual_understanding or not options.use_saved_connection
            or options.llm_api_key or options.llm_base_url or options.llm_model):
        raise ValueError('course_upgrade_options_required')
    selected = connection(request.base_url,request.model)
    resolved = options.model_copy(update={'llm_base_url':selected['base_url'],'llm_model':selected['model']})
    validate_model(resolved)
    with courses.course_transaction():
        task, cues, source_fingerprint, episode = _capture(course_id,episode_id,request.revision)
        if any(blocks_reacquisition(child) for child in episode.get("upgrades", [])):
            raise ValueError("course_upgrade_child_available")
    fingerprint = digest({'source':source_fingerprint,'connection':selected['fingerprint'],
                          'options':options.model_dump(mode='json'),'revision':request.revision})
    now = time.monotonic()
    with _lock:
        for token in list(_previews):
            if _previews[token]['expires'] <= now:
                del _previews[token]
        if len(_previews) >= 256:
            raise ValueError('course_upgrade_busy')
        token = secrets.token_urlsafe(32)
        _previews[token] = {'scope':_scope(course_id,episode_id),'request':request.model_copy(deep=True),
            'source':source_fingerprint,'connection':selected['fingerprint'],'fingerprint':fingerprint,
            'expires':now+PREVIEW_SECONDS,'cancelled':False,'source_id':task.id}
    return {'preview_id':token,'fingerprint':fingerprint,'source_task_id':task.id,'episode_id':episode_id,
            'page_url':task.page_url,'title':task.title,
            'model_source':{'title':model_source_text(task.title),'url':model_source_text(task.page_url)},
            'connection':{'base_url':selected['base_url'],'model':selected['model']},
            'resource_budget_mb':options.resource_budget_mb,'options':options.model_dump(mode='json'),
            'caption_characters':sum(len(cue.text) for cue in cues),
            'data_leaving_service':['source_title','source_url','saved_caption_text','extracted_video_frames'],
            'warning':'确认后首次下载此分集视频，并把来源标题、链接、字幕与提取画面发送到所选模型。网关可能转发；可能收费，金额未知。原笔记与字幕保留。'}


def cancel_preview(course_id,episode_id,token):
    with _lock:
        review = _previews.get(token)
        if review and review['scope'] == _scope(course_id,episode_id):
            review['cancelled'] = True
    return {'cancelled':True}


def apply_upgrade(course_id,episode_id,request,background_tasks,*,validate_model,admit):
    if request.confirm_download is not True or request.share_images is not True:
        raise ValueError('course_upgrade_consent_required')
    # Keep one review's admission serialized. Durable handoff identity handles a
    # lost response; a different review must never reuse global URL consent.
    with _lock, courses.course_transaction(), storage.task_state_transaction():
        review = _previews.get(request.preview_id)
        if (not review or review['scope'] != _scope(course_id,episode_id) or review['cancelled']
                or review['expires'] <= time.monotonic() or review['fingerprint'] != request.fingerprint):
            raise ValueError('course_upgrade_preview_expired')
        original = review['request']
        selected = connection(original.base_url,original.model)
        task,cues,source_fingerprint,episode = _capture(course_id,episode_id,original.revision)
        if source_fingerprint != review['source'] or selected['fingerprint'] != review['connection']:
            raise ValueError('course_upgrade_preview_stale')
        options = original.options.model_copy(update={'llm_base_url':selected['base_url'],'llm_model':selected['model'], 'llm_api_key':selected['key']})
        validate_model(options)
        if connection(original.base_url,original.model)['fingerprint'] != review['connection']:
            raise ValueError('course_upgrade_preview_stale')
        handoff = upgrade_prefix(course_id,episode_id,task.id) + hashlib.sha256(request.preview_id.encode()).hexdigest()[:32]
        for child in episode.get('upgrades', []):
            if blocks_reacquisition(child) and storage.get_task(child['task_id']).handoff_id != handoff:
                raise ValueError('course_upgrade_child_available')
        page_request = CurrentPageTaskRequest(page_url=task.page_url,title=task.title,handoff_id=handoff,
            browser_subtitles=cues,active_video=ActiveVideoInfo(duration=max(cue.end for cue in cues)),options=options)
        return admit(page_request,task,episode_id,background_tasks)
