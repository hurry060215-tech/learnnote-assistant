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
    user_selected: bool = False
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
    mse_append_bytes: int | None = None
    mse_append_total_bytes: int | None = None
    mse_append_count: int | None = None
    mse_append_magic: str = ""
    mse_append_mime: str = ""
    mse_append_detected_kind: str = ""
    initiator: str = ""
    time_stamp: float | None = None
    resolved_url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_body: dict[str, str] = Field(default_factory=dict)


class DrmSignal(BaseModel):
    source: str = "unknown"
    key_system: str = ""
    init_data_type: str = ""
    label: str = ""
    page_url: str = ""
    frame_id: int | None = None
    time_stamp: float | None = None


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
    note_template: str = "standard"
    summary_depth: str = "standard"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None


class ActiveVideoInfo(BaseModel):
    src: str = ""
    src_object: bool = False
    src_object_type: str = ""
    src_object_track_count: int = 0
    src_object_video_tracks: int = 0
    src_object_audio_tracks: int = 0
    current_time: float = 0
    duration: float = 0
    paused: bool = True
    width: int = 0
    height: int = 0
    frame_id: int | None = None
    label: str = ""
    drm_detected: bool = False
    drm_key_system: str = ""
    encrypted_events: int = 0
    time_stamp: float | None = None


class BrowserSubtitleCue(BaseModel):
    start: float
    end: float
    text: str


class CurrentPageTaskRequest(BaseModel):
    mode: Literal["video", "page_text", "download_only"] = "video"
    page_url: str
    title: str = ""
    page_text: str = ""
    active_video: ActiveVideoInfo | None = None
    browser_subtitles: list[BrowserSubtitleCue] = Field(default_factory=list)
    resources: list[ResourceCandidate] = Field(default_factory=list)
    drm_detected: bool = False
    drm_signals: list[DrmSignal] = Field(default_factory=list)
    cookies: list[BrowserCookie] = Field(default_factory=list)
    options: TaskOptions = Field(default_factory=TaskOptions)


class MediaPreflightRequest(BaseModel):
    page_url: str = ""
    resource: ResourceCandidate
    cookies: list[BrowserCookie] = Field(default_factory=list)


class PagePreflightRequest(BaseModel):
    page_url: str = ""
    resources: list[ResourceCandidate] = Field(default_factory=list)
    cookies: list[BrowserCookie] = Field(default_factory=list)
    drm_detected: bool = False
    probe_limit: int = Field(default=3, ge=0, le=8)


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
    content_disposition: str = ""
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
    frame_timestamps: list[float] = Field(default_factory=list)


class VisualWindow(BaseModel):
    id: str
    index: int
    start: float
    end: float
    duration: float = 0
    frame_count: int
    frame_timestamps: list[float] = Field(default_factory=list)
    grid_url: str
    grid_path: str = ""
    transcript_excerpt: str = ""
    segments: list[TranscriptSegment] = Field(default_factory=list)


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
    resolved_url: str = ""


class TaskRecord(BaseModel):
    id: str
    source_type: Literal["current_page", "local", "page_text"]
    mode: str = "video"
    title: str
    page_url: str = ""
    phase: TaskPhase = "queued"
    status: Literal["queued", "running", "success", "failed"] = "queued"
    progress: int = 0
    message: str = "Queued"
    error_code: str = ""
    error_detail: str = ""
    source_task_id: str = ""
    source_media_path: str = ""
    created_at: str
    updated_at: str
    options: TaskOptions = Field(default_factory=TaskOptions)
    selected_resource: ResourceCandidate | None = None
    download_attempts: list[DownloadAttempt] = Field(default_factory=list)
    cookie_summary: dict[str, Any] = Field(default_factory=dict)
    drm_detected: bool = False
    drm_signals: list[DrmSignal] = Field(default_factory=list)
    active_video: ActiveVideoInfo | None = None
    browser_subtitles: list[BrowserSubtitleCue] = Field(default_factory=list)
    media_path: str = ""
    audio_path: str = ""
    subtitle_path: str = ""
    transcript_path: str = ""
    visual_index_path: str = ""
    note_path: str = ""
    summary_source: str = ""
    summary_warning: str = ""
    summary_diagnostics_path: str = ""
    summary_diagnostics: dict[str, Any] = Field(default_factory=dict)
    frame_grids: list[FrameGrid] = Field(default_factory=list)
    visual_windows: list[VisualWindow] = Field(default_factory=list)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_dump_jsonable(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
