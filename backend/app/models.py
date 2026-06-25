from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


TaskPhase = Literal[
    "queued",
    "detecting",
    "downloading",
    "processing_video",
    "transcribing",
    "extracting_frames",
    "summarizing",
    "completed",
    "failed",
]


class ResourceCandidate(BaseModel):
    url: str
    source: str = "unknown"
    kind: str = "unknown"
    mime: str = ""
    score: int = 0
    label: str = ""
    tab_id: int | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class BrowserCookie(BaseModel):
    name: str
    value: str
    domain: str = ""
    path: str = "/"
    secure: bool = False
    httpOnly: bool = False
    expirationDate: float | None = None


class TaskOptions(BaseModel):
    transcriber: str = "faster-whisper"
    whisper_model: str = "small"
    visual_understanding: bool = True
    frame_interval: int = 20
    grid_columns: int = 3
    grid_rows: int = 3
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None


class CurrentPageTaskRequest(BaseModel):
    mode: Literal["video", "page_text"] = "video"
    page_url: str
    title: str = ""
    page_text: str = ""
    resources: list[ResourceCandidate] = Field(default_factory=list)
    cookies: list[BrowserCookie] = Field(default_factory=list)
    options: TaskOptions = Field(default_factory=TaskOptions)


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptResult(BaseModel):
    language: str = "unknown"
    segments: list[TranscriptSegment] = Field(default_factory=list)
    full_text: str = ""
    source: str = "unknown"
    warning: str = ""


class FrameGrid(BaseModel):
    path: str
    url: str
    start: float
    end: float
    frame_count: int


class TaskRecord(BaseModel):
    id: str
    source_type: Literal["current_page", "local", "page_text"]
    title: str
    page_url: str = ""
    phase: TaskPhase = "queued"
    status: Literal["queued", "running", "success", "failed"] = "queued"
    progress: int = 0
    message: str = "Queued"
    error_code: str = ""
    error_detail: str = ""
    created_at: str
    updated_at: str
    selected_resource: ResourceCandidate | None = None
    media_path: str = ""
    audio_path: str = ""
    transcript_path: str = ""
    note_path: str = ""
    frame_grids: list[FrameGrid] = Field(default_factory=list)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_dump_jsonable(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
