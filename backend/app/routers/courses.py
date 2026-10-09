from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict

from ..courses import list_courses, get_course, save_course, delete_course, compare_course, ask_course, edit_course_identity
from ..concept_identity import read_history, restore_history
from ..playlists import preview_playlist
from ..course_episodes import course_episodes, prepare_course_episode, bind_course_episode
from .graph_snapshot import graph_snapshot_router

course_router = APIRouter(prefix="/api/courses", tags=["courses"])
course_router.include_router(graph_snapshot_router)


class CourseSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["task", "material", "url"]
    id: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_-]*$")
    url: str = Field(default="", max_length=4096)
    title: str = Field(default="", max_length=500)


class CourseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    sources: list[CourseSource] = Field(default_factory=list, max_length=200)
    paused: bool = False
    revision: int = Field(default=0, ge=0)


class PlaylistRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)


@course_router.post("/playlist-preview")
def api_playlist_preview(request: PlaylistRequest):
    try:
        return preview_playlist(request.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc), "message": "无法展开该公开播放列表。可改为每行粘贴一个视频或分P链接；不会绕过登录权限。"}) from exc


@course_router.get("")
def api_courses():
    return {"courses": list_courses()}


@course_router.post("")
def api_create_course(request: CourseRequest):
    try:
        course = save_course(request.title, [item.model_dump() for item in request.sources], request.paused)
        return {"course": course, "episodes": course_episodes(course)}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@course_router.get("/{course_id}")
def api_course(course_id: str):
    try:
        course = get_course(course_id)
        return {"course": course, "episodes": course_episodes(course)}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Course unavailable") from exc


@course_router.put("/{course_id}")
def api_save_course(course_id: str, request: CourseRequest):
    try:
        course = save_course(request.title, [item.model_dump() for item in request.sources], request.paused, course_id, request.revision)
        return {"course": course, "episodes": course_episodes(course)}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@course_router.delete("/{course_id}")
def api_delete_course(course_id: str):
    try:
        delete_course(course_id)
        return {"deleted": True, "sources_deleted": False}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Course unavailable") from exc


@course_router.get("/{course_id}/compare")
def api_compare_course(course_id: str, q: str = Query(min_length=1, max_length=200), source_id: str = Query(default="", max_length=128), source_kind: Literal["", "task", "material"] = "", start: float | None = Query(default=None, ge=0), end: float | None = Query(default=None, ge=0)):
    try:
        return compare_course(course_id, q, source_id=source_id, source_kind=source_kind, start=start, end=end)
    except (ValueError, OSError) as exc:
        if str(exc) == "concept_history_invalid":
            raise HTTPException(status_code=409, detail={"code": "concept_history_invalid", "message": "含义分组记录损坏；已保留原文件与历史备份，未重置你的整理选择。"}) from exc
        if str(exc) == "comparison_scope_too_large":
            raise HTTPException(status_code=409, detail={"code": "comparison_scope_too_large", "message": "本课程出处超过本地对比上限，请先缩小课程范围。未截断你的分组记录。"}) from exc
        raise HTTPException(status_code=404, detail="Course unavailable") from exc


class ConceptIdentityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    action: Literal["split", "merge"]
    term: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=120)
    evidence_ids: list[str] = Field(default_factory=list, max_length=1000)
    group_ids: list[str] = Field(default_factory=list, max_length=1000)
    revision: int = Field(ge=0)
    course_revision: int = Field(ge=1)
    scope_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


def _concept_error(exc):
    known_codes = ("invalid_course_id", "concept_history_invalid", "concept_history_limit", "concept_request_conflict",
                   "concept_changed_reload_required", "concept_evidence_changed_reload_required", "concept_evidence_outside_scope",
                   "concept_merge_groups_required", "concept_evidence_unresolved", "concept_backup_conflict", "comparison_scope_too_large")
    code = "concept_storage_unavailable" if isinstance(exc, OSError) else next((known for known in known_codes if known == str(exc)), "concept_operation_failed")
    message = "分组未保存。课程、出处或分组可能已变化，请重新打开课程并核对；损坏或冲突的记录不会被覆盖。"
    if code == "concept_history_limit":
        message = "本地分组操作达到上限（单次 1000 条出处、每门课程 1000 次操作或 20 MB）。已有记录已保留，可先导出完整历史。"
    return HTTPException(status_code=409, detail={"code": code, "message": message})


@course_router.post("/{course_id}/concepts")
def api_edit_concept(course_id: str, request: ConceptIdentityRequest):
    try:
        return edit_course_identity(course_id, request.request_id, request.model_dump(exclude={"request_id"}))
    except (ValueError, OSError) as exc:
        raise _concept_error(exc) from exc


@course_router.get("/{course_id}/concepts/backup")
def api_concept_backup(course_id: str):
    try:
        get_course(course_id)
        return read_history(course_id)
    except (ValueError, OSError) as exc:
        raise _concept_error(exc) from exc


class ConceptRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    backup: dict


@course_router.post("/{course_id}/concepts/restore")
def api_restore_concepts(course_id: str, request: ConceptRestoreRequest):
    try:
        get_course(course_id)
        return restore_history(course_id, request.backup, request.revision)
    except (ValueError, OSError) as exc:
        raise _concept_error(exc) from exc


class CourseQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=2000)
    revision: int = Field(ge=1)
    limit: int = Field(default=6, ge=1, le=50)
    mode: Literal["lexical", "embedding", "semantic", "local-embedding"] = "lexical"


@course_router.post("/{course_id}/ask")
def api_ask_course(course_id: str, request: CourseQuestion):
    try:
        return ask_course(course_id, request.question, request.revision, request.limit, request.mode)
    except (ValueError, OSError) as exc:
        stale = str(exc) == "course_changed_reload_required"
        raise HTTPException(status_code=409 if stale else 404, detail={"code": "course_changed_reload_required" if stale else "course_unavailable", "message": "课程已改变，请重新打开课程后再提问。" if stale else "课程不存在或已删除，请重新选择课程。"}) from exc
    except RuntimeError as exc:
        if str(exc) == "local_embedding_unavailable":
            raise HTTPException(status_code=409, detail={"code": "local_embedding_unavailable", "message": "可选本地 embedding 或缓存模型不可用，请使用本地关键词检索。"}) from exc
        raise


class EpisodeBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


@course_router.post("/{course_id}/episodes/{episode_id}/prepare")
def api_prepare_course_episode(course_id: str, episode_id: str):
    try:
        return {"episode": prepare_course_episode(get_course(course_id), episode_id)}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail={"code":str(exc), "message":"课程已暂停、来源失效或任务身份冲突，请刷新课程后重试。"}) from exc


@course_router.post("/{course_id}/episodes/{episode_id}/bind")
def api_bind_course_episode(course_id: str, episode_id: str, request: EpisodeBinding):
    try:
        return {"episode": bind_course_episode(get_course(course_id), episode_id, request.task_id)}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=409, detail={"code":str(exc), "message":"任务与该课程分集不匹配，未修改已有绑定。"}) from exc
