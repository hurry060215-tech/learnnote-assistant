"""Course-bound retry routes with stale-view checks."""
import sqlite3
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from .. import course_learning
from ..models import TaskOptions

course_learning_router = APIRouter()


class EpisodeRetry(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=1)
    task_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    generation: str = Field(pattern=r'^[a-f0-9]{64}$')
    options: TaskOptions


def learning_error(exc):
    messages = {
        'course_text_retry_required':'仅有字幕时请选择文字笔记；图文升级需要单独预览与授权。',
        'course_upgrade_consent_required':'请分别确认视频下载和向所选模型分享字幕、来源与画面。',
        'course_upgrade_child_available':'此分集已有升级任务或保存的视频，请打开该任务继续，未重复下载。',
        'course_upgrade_preview_expired':'升级预览已取消或过期，请重新预览。',
        'course_upgrade_preview_stale':'来源或模型已变化，请重新预览并确认。',
        'course_upgrade_vision_model_required':'请选择支持图像的模型后重新预览。',
        'course_upgrade_options_required':'请使用已保存的模型连接并明确选择图文笔记。',
        'course_upgrade_unavailable':'此分集暂不支持字幕到图文升级，请核对原始字幕与来源。',
        'course_upgrade_busy':'预览请求过多，请稍后重试。',
        'course_model_changed':'所选模型已变化，请重新预览。',
        'course_model_unavailable':'所选模型不可用，请检查已保存的连接。',
    }
    codes = set(messages) | {'course_changed_reload_required','course_episode_identity_conflict','course_episode_changed'}
    code = str(exc) if str(exc) in codes else 'course_learning_unavailable'
    return HTTPException(409, {'code':code,'message':messages.get(code,'课程或分集已变化，请刷新后重试。')})


@course_learning_router.post('/{course_id}/episodes/{episode_id}/retry')
def api_retry_episode(course_id: str, episode_id: str, request: EpisodeRetry, background_tasks: BackgroundTasks, http: Request):
    try:
        return course_learning.retry_episode(course_id, episode_id, request, background_tasks,
            retry_summary=http.app.state.course_retry_summary, resume_task=http.app.state.course_resume)
    except (ValueError, OSError, TypeError, sqlite3.Error) as exc:
        raise learning_error(exc) from None


from pydantic import StrictBool
from .. import course_upgrades, course_upgrade_admission


class EpisodeUpgradePreview(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=1)
    options: TaskOptions
    base_url: str = Field(min_length=1,max_length=2048)
    model: str = Field(min_length=1,max_length=300)


class EpisodeUpgrade(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    preview_id: str = Field(min_length=32,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirm_download: StrictBool
    share_images: StrictBool


@course_learning_router.post('/{course_id}/episodes/{episode_id}/upgrade-preview')
def api_upgrade_preview(course_id: str, episode_id: str, request: EpisodeUpgradePreview, http: Request):
    try:
        return course_upgrades.preview_upgrade(course_id,episode_id,request,
            validate_model=course_upgrade_admission.validate_model)
    except (ValueError,OSError,TypeError,sqlite3.Error) as exc:
        raise learning_error(exc) from None


@course_learning_router.delete('/{course_id}/episodes/{episode_id}/upgrade-preview/{preview_id}')
def api_cancel_upgrade_preview(course_id: str, episode_id: str, preview_id: str):
    return course_upgrades.cancel_preview(course_id,episode_id,preview_id)


@course_learning_router.post('/{course_id}/episodes/{episode_id}/upgrade')
def api_upgrade_episode(course_id: str, episode_id: str, request: EpisodeUpgrade,
                        background_tasks: BackgroundTasks, http: Request):
    try:
        return course_upgrades.apply_upgrade(course_id,episode_id,request,background_tasks,
            validate_model=course_upgrade_admission.validate_model,admit=course_upgrade_admission.admit_upgrade)
    except (ValueError,OSError,TypeError,sqlite3.Error) as exc:
        raise learning_error(exc) from None
