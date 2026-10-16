"""Admit a reviewed visual child using existing model and durable queue guards."""
import hashlib
from . import storage
from .reliability import current_page_source_identity
from .source_input import normalize_source_input
from .task_inputs import require_ready_note_model
from .task_queue import schedule_processing
from .summarizer import llm_model_supports_vision


def validate_model(options):
    require_ready_note_model(options)
    if not llm_model_supports_vision(options.llm_base_url,options.llm_model):
        raise ValueError('course_upgrade_vision_model_required')


def admit_upgrade(request,source,episode_id,background_tasks):
    from .processor import process_current_page_task
    # Caller holds course and task-state transactions through first write.
    matches = [task for task in storage.list_tasks_snapshot(strict=True) if task.handoff_id == request.handoff_id]
    identity = current_page_source_identity(request)
    if matches:
        if len(matches) != 1:
            raise ValueError('course_episode_identity_conflict')
        task = storage.get_task(matches[0].id)
        if (task.handoff_id != request.handoff_id or task.source_task_id != source.id
                or task.source_type != 'current_page' or task.mode != 'video' or task.learning_range
                or normalize_source_input(task.page_url).url != normalize_source_input(request.page_url).url
                or any(getattr(task.source_identity, key) != getattr(identity, key) for key in ("platform", "platform_id", "page_url"))):
            raise ValueError('course_episode_identity_conflict')
        return {'task_id':task.id,'task':task.model_dump(mode='json'),'source_task_id':source.id,
                'episode_id':episode_id,'deduplicated':True}
    task = storage.create_task('current_page',source.title,page_url=normalize_source_input(request.page_url).url,
        mode='video',options=request.options,handoff_id=request.handoff_id,source_identity=identity,
        source_task_id=source.id)
    task = storage.update_task(task.id,browser_subtitles=request.browser_subtitles,active_video=request.active_video)
    captions_path = storage.write_json(task.id,'course-upgrade-captions.json',
        [cue.model_dump(mode='json') for cue in request.browser_subtitles])
    storage.write_json(task.id,'course-upgrade-review.json',{
        'caption_sha256':hashlib.sha256(captions_path.read_bytes()).hexdigest(),
        'episode_id':episode_id,'source_task_id':source.id,'source_generation':source.control_generation,
        'source_url':request.page_url,'model':request.options.llm_model,'base_url':request.options.llm_base_url,
        'resource_budget_mb':request.options.resource_budget_mb,'download_confirmed':True,'image_sharing_confirmed':True})
    schedule_processing(background_tasks,process_current_page_task,task.id,request)
    return {'task_id':task.id,'task':task.model_dump(mode='json'),'source_task_id':source.id,
            'episode_id':episode_id,'deduplicated':False}
