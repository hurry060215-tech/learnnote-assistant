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
    is_main_video: bool = False
    playback_match: str = ""
    blob_url: str = ""
    frame_url: str = ""
    page_url: str = ""
    tab_id: int | None = None
    frame_id: int | None = None
    current_time: float | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    request_type: str = ""
    method: str = ""
    status_code: int | None = None
    content_length: int | None = None
    initiator: str = ""
    time_stamp: float | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    request_headers: dict[str, str] = Field(default_factory=dict)


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
    note_style: str = "study"
    summary_depth: str = "standard"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None


class ActiveVideoInfo(BaseModel):
    src: str = ""
    current_time: float = 0
    duration: float = 0
    paused: bool = True
    width: int = 0
    height: int = 0
    frame_id: int | None = None
    label: str = ""


class CurrentPageTaskRequest(BaseModel):
    mode: Literal["video", "page_text"] = "video"
    page_url: str
    title: str = ""
    page_text: str = ""
    active_video: ActiveVideoInfo | None = None
    resources: list[ResourceCandidate] = Field(default_factory=list)
    cookies: list[BrowserCookie] = Field(default_factory=list)
    options: TaskOptions = Field(default_factory=TaskOptions)


class MediaPreflightRequest(BaseModel):
    page_url: str = ""
    resource: ResourceCandidate
    cookies: list[BrowserCookie] = Field(default_factory=list)


class MediaPreflightResult(BaseModel):
    ok: bool = False
    downloadable: bool = False
    strategy: str = ""
    kind: str = ""
    url: str = ""
    resolved_url: str = ""
    code: str = ""
    message: str = ""
    status_code: int | None = None
    content_type: str = ""
    content_length: int | None = None
    bytes_checked: int = 0
    request_header_names: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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


class DownloadAttempt(BaseModel):
    strategy: str
    url: str = ""
    source: str = ""
    kind: str = ""
    score: int = 0
    status: Literal["success", "failed", "skipped"] = "failed"
    code: str = ""
    message: str = ""
    output_path: str = ""
    bytes_downloaded: int | None = None
    status_code: int | None = None
    content_length: int | None = None
    mime: str = ""


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
    options: TaskOptions = Field(default_factory=TaskOptions)
    selected_resource: ResourceCandidate | None = None
    download_attempts: list[DownloadAttempt] = Field(default_factory=list)
    media_path: str = ""
    audio_path: str = ""
    subtitle_path: str = ""
    transcript_path: str = ""
    note_path: str = ""
    frame_grids: list[FrameGrid] = Field(default_factory=list)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_dump_jsonable(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
