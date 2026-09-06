from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict

from ..courses import list_courses, get_course, save_course, delete_course, compare_course
from ..playlists import preview_playlist

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
        return {"course": save_course(request.title, [item.model_dump() for item in request.sources], request.paused)}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@course_router.get("/{course_id}")
def api_course(course_id: str):
    try:
        return {"course": get_course(course_id)}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Course unavailable") from exc


@course_router.put("/{course_id}")
def api_save_course(course_id: str, request: CourseRequest):
    try:
        return {"course": save_course(request.title, [item.model_dump() for item in request.sources], request.paused, course_id, request.revision)}
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
def api_compare_course(course_id: str, q: str = Query(min_length=1, max_length=200)):
    try:
        return compare_course(course_id, q)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Course unavailable") from exc
