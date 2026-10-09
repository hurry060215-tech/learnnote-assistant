import sqlite3
from typing import Annotated, Literal
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field, ConfigDict

from ..courses import list_courses, get_course, save_course, delete_course, compare_course
from ..course_deletion import preview_course_deletion, delete_reviewed_course
from ..playlists import preview_playlist
from ..course_episodes import course_episodes, prepare_course_episode, bind_course_episode

course_router = APIRouter(prefix="/api/courses", tags=["courses"])


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


class CourseDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal["delete_course"]
    revision: int = Field(ge=1)
    snapshot: str = Field(pattern=r"^[a-f0-9]{64}$")
    task_ids: list[Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]] = Field(default_factory=list, max_length=200)


@course_router.get("/{course_id}/deletion-preview")
def api_course_deletion_preview(course_id: str):
    try:
        return preview_course_deletion(course_id)
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise HTTPException(status_code=409, detail={"code": "course_unavailable", "message": "课程或来源暂不可用，请刷新后重试。"}) from exc


@course_router.delete("/{course_id}")
def api_delete_course(course_id: str, request: CourseDeletionRequest | None = Body(default=None)):
    try:
        if request is not None:
            return delete_reviewed_course(course_id, revision=request.revision, snapshot=request.snapshot, task_ids=request.task_ids)
        # Compatibility for collection-only callers: never infer child removal.
        delete_course(course_id)
        return {"deleted": True, "sources_deleted": False}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc), "message": "课程、任务状态或引用已变化，未执行删除。请重新查看删除范围后确认。"}) from exc
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(status_code=409, detail={"code": "course_cleanup_failed", "message": "课程清理未完成，请刷新后重试。"}) from exc


@course_router.get("/{course_id}/compare")
def api_compare_course(course_id: str, q: str = Query(min_length=1, max_length=200), source_id: str = Query(default="", max_length=128), source_kind: Literal["", "task", "material"] = "", start: float | None = Query(default=None, ge=0), end: float | None = Query(default=None, ge=0)):
    try:
        return compare_course(course_id, q, source_id=source_id, source_kind=source_kind, start=start, end=end)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Course unavailable") from exc


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
