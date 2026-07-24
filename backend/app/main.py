from __future__ import annotations

from importlib.util import find_spec
from io import BytesIO
import base64
import hmac
import json
import mimetypes
import re
import shutil
import tempfile
import threading
import time
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import API_VERSION, APP_VERSION, TASK_SCHEMA_VERSION, UX_PROTOCOL_VERSION
from .config import BACKEND_ORIGIN, DATA_DIR, DEPLOYMENT_MODE, LLM_API_KEY, LLM_BASE_URL, LLM_MAX_RETRIES, LLM_MODEL, LLM_REQUEST_TIMEOUT_SECONDS, MODEL_CACHE_DIR, PUBLIC_DEPLOYMENT, PUBLIC_PASSWORD, PUBLIC_USERNAME, STATIC_DIR, TASK_DIR, TEMP_DIR, UPLOAD_DIR, WEB_DIR, ensure_dirs
from .downloader import MediaDownloader, effective_resource_kind, fallback_page_contexts, media_file_video_signature, preflight_media_resource, rank_media_candidates
from .media import MediaProcessingError, extract_video_clip, probe_duration, probe_media_integrity
from .models import CurrentPageTaskRequest, MediaIntegrity, MediaPreflightRequest, MediaPreflightResult, PagePreflightRequest, RerunFromMediaRequest, ResourceCandidate, SourceInputRequest, StorageCleanupRequest, TaskOptions, TaskQuestionRequest, TaskRecord, now_iso
from .processor import browser_subtitle_text_is_player_ui, enrich_resource_candidates_with_active_video, process_current_page_task, process_local_video_task, read_note, read_transcript, read_visual_index, redacted_request_dump, redacted_resource
from .reliability import current_page_source_identity, local_source_identity
from .runtime import ffmpeg_bin, ffprobe_bin
from .source_input import SourceInputError, clean_task_title, normalize_source_input
from .storage import atomic_write_text, cleanup_tasks, create_task, delete_all_tasks, delete_task, get_task, list_tasks, read_json, request_task_cancel, storage_summary, task_dir, update_task, write_json
from .summarizer import chat_completion_provider_kwargs, llm_base_host, llm_model_supports_vision, llm_provider_name, visual_window_review_question_lines

ensure_dirs()

app = FastAPI(title="LearnNote Assistant", version=APP_VERSION)
_extension_heartbeat_at = 0.0
_extension_version = ""
_extension_protocol_version = 0
_deferred_handoffs: dict[str, CurrentPageTaskRequest] = {}
_deferred_handoffs_lock = threading.RLock()
# Side Panel heartbeats arrive every 10 seconds. The MV3 background worker also
# wakes on a 30-second alarm so the desktop can report a loaded extension even
# when its panel is closed.
EXTENSION_HEARTBEAT_TTL_SECONDS = 75.0
TRUSTED_BROWSER_ORIGIN_RE = re.compile(r"^(chrome-extension://[a-z]+|moz-extension://[a-z0-9-]+|https?://(localhost|127\.0\.0\.1)(:\d+)?)$")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=TRUSTED_BROWSER_ORIGIN_RE.pattern,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_public_access(request: Request, call_next):
    if not PUBLIC_DEPLOYMENT or request.url.path == "/health":
        return await call_next(request)
    authorization = (request.headers.get("authorization") or "").strip()
    expected = base64.b64encode(f"{PUBLIC_USERNAME}:{PUBLIC_PASSWORD}".encode("utf-8")).decode("ascii")
    valid = authorization.lower().startswith("basic ") and hmac.compare_digest(authorization[6:].strip(), expected)
    if not valid:
        return Response(
            "Authentication required",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="LearnNote", charset="UTF-8"'},
        )
    return await call_next(request)


def request_origin_matches_host(request: Request, origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    forwarded_host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",", 1)[0].strip()
    forwarded_proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").split(",", 1)[0].strip().lower()
    return bool(parsed.netloc and parsed.netloc.lower() == forwarded_host.lower() and parsed.scheme.lower() == forwarded_proto)


@app.middleware("http")
async def enforce_trusted_write_origin(request: Request, call_next):
    origin = (request.headers.get("origin") or "").strip()
    trusted_origin = bool(TRUSTED_BROWSER_ORIGIN_RE.fullmatch(origin) or request_origin_matches_host(request, origin))
    if request.method.upper() in WRITE_METHODS and request.url.path.startswith("/api/") and origin and not trusted_origin:
        return Response("Forbidden origin", status_code=403)
    return await call_next(request)

app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")
app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")


_FILENAME_RESERVED_RE = re.compile(r'[\\/:*?"<>|\r\n]+')
LOCAL_VIDEO_EXTENSIONS = {".mp4", ".m4s", ".m4v", ".mov", ".mkv", ".webm", ".flv", ".avi"}
LOCAL_VIDEO_MIME_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/iso.segment": ".m4s",
    "video/x-m4v": ".m4v",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/webm": ".webm",
    "video/x-flv": ".flv",
    "video/avi": ".avi",
    "video/x-msvideo": ".avi",
}
LOCAL_UPLOAD_CHUNK_SIZE = 1024 * 1024
STAGED_UPLOAD_MAX_AGE_SECONDS = 24 * 60 * 60
QA_HISTORY_FILE = "qa_history.json"


def local_upload_filename(filename: str | None, content_type: str | None = "") -> str:
    raw_name = Path(filename or "").name or "local-video"
    safe_name = _FILENAME_RESERVED_RE.sub("_", raw_name).strip(" ._") or "local-video"
    suffix = Path(safe_name).suffix.lower()
    if not suffix:
        suffix = LOCAL_VIDEO_MIME_EXTENSIONS.get((content_type or "").split(";")[0].lower(), "")
        if suffix:
            safe_name = f"{safe_name}{suffix}"
    if suffix not in LOCAL_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_local_file",
                "message": "本地视频仅支持 mp4、m4s、m4v、mov、mkv、webm、flv、avi。",
            },
        )
    stem = Path(safe_name).stem[:120].strip(" ._") or "local-video"
    return f"{stem}{suffix}"


def local_upload_error(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def validate_local_upload_file(path: Path) -> MediaIntegrity:
    if not path.exists() or path.stat().st_size <= 0:
        raise local_upload_error("empty_local_file", "本地视频文件为空，请重新选择有效的视频文件。")
    integrity = probe_media_integrity(path)
    if integrity.status in {"invalid", "no_media"}:
        raise local_upload_error("invalid_local_video", "文件中没有可读取的音视频轨道或有效时长。")
    return integrity


def cleanup_expired_staged_uploads(now: float | None = None) -> int:
    cutoff = float(now if now is not None else time.time()) - STAGED_UPLOAD_MAX_AGE_SECONDS
    removed = 0
    for path in UPLOAD_DIR.glob("staged_*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def merge_task_options(base: TaskOptions | None, overrides: TaskOptions | None) -> TaskOptions:
    merged = (base or TaskOptions()).model_dump(mode="json")
    if overrides is not None:
        explicit_fields = getattr(overrides, "model_fields_set", set()) or set()
        override_values = overrides.model_dump(mode="json")
        for field in explicit_fields:
            if field in override_values:
                merged[field] = override_values[field]
    return TaskOptions.model_validate(merged)


def build_handoff_integrity(request: CurrentPageTaskRequest) -> MediaIntegrity:
    active = request.active_video
    has_video = bool(active and (active.src or active.src_object_video_tracks > 0))
    has_audio = bool(active and active.src_object_audio_tracks > 0)
    duration_candidates = [float(active.duration or 0)] if active else []
    has_subtitles = any(
        str(cue.text or "").strip() and not browser_subtitle_text_is_player_ui(cue.text)
        for cue in request.browser_subtitles
    )
    for resource in request.resources:
        kind = effective_resource_kind(resource)
        declared_kind = str(resource.kind or "").strip().lower()
        mime = str(resource.mime or "").lower()
        if kind in {"video", "hls", "dash"} or declared_kind in {"video", "hls", "dash"} or mime.startswith("video/"):
            has_video = True
        if kind == "audio" or declared_kind == "audio" or mime.startswith("audio/") or bool(resource.audio_url):
            has_audio = True
        if kind == "subtitle" or declared_kind == "subtitle":
            has_subtitles = True
        if resource.duration:
            duration_candidates.append(float(resource.duration))
    duration = max((value for value in duration_candidates if value > 0), default=0.0)
    if has_video and has_audio:
        status = "ready"
        blocking_reasons = []
    elif has_video:
        status = "video_only"
        blocking_reasons = ["audio_track_not_yet_confirmed"]
    elif has_audio:
        status = "audio_only"
        blocking_reasons = ["video_track_not_yet_confirmed"]
    else:
        status = "no_media"
        blocking_reasons = ["media_tracks_not_yet_confirmed"]
    return MediaIntegrity(
        status=status,
        probe_backend="browser-handoff",
        provisional=True,
        duration=duration,
        stream_count=int(has_video) + int(has_audio) + int(has_subtitles),
        video_stream_count=int(has_video),
        audio_stream_count=int(has_audio),
        subtitle_stream_count=int(has_subtitles),
        has_video=has_video,
        has_audio=has_audio,
        has_subtitles=has_subtitles,
        blocking_reasons=blocking_reasons,
    )


def rerun_options_from_body(body: RerunFromMediaRequest | TaskOptions | None) -> TaskOptions | None:
    if body is None:
        return None
    if isinstance(body, RerunFromMediaRequest):
        return body.options
    return body


def task_media_path(task: TaskRecord) -> Path | None:
    for raw_path in (task.media_path, task.source_media_path):
        if not raw_path:
            continue
        try:
            path = Path(raw_path)
        except (OSError, ValueError):
            continue
        if path.is_file():
            return path
    return None


def task_media_file_exists(task: TaskRecord) -> bool:
    return task_media_validation(task)[0] == "verified"


def task_media_source_is_definitively_non_video(task: TaskRecord) -> bool:
    successful_attempts = [attempt for attempt in task.download_attempts if attempt.status == "success"]
    sources = successful_attempts or ([task.selected_resource] if task.selected_resource else [])
    if not sources:
        return False

    def is_non_video(source: object) -> bool:
        mime = str(getattr(source, "mime", "") or "").split(";", 1)[0].strip().lower()
        if mime.startswith("image/") or mime in {"application/json", "application/xml", "text/html", "text/plain"}:
            return True
        resolved_url = str(getattr(source, "resolved_url", "") or getattr(source, "url", "") or "")
        path = urlsplit(resolved_url).path.lower()
        return path.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".json", ".html"))

    return all(is_non_video(source) for source in sources)


def task_media_validation(task: TaskRecord) -> tuple[str, str]:
    media_path = task_media_path(task)
    if media_path is None:
        return "missing", ""
    signature = media_file_video_signature(media_path)
    if not signature or task_media_source_is_definitively_non_video(task):
        return "invalid", signature
    return "verified", signature


def task_media_ready_for_rerun(task: TaskRecord, *, allow_existing_note: bool = False) -> bool:
    if task.status not in {"success", "failed"}:
        return False
    if task.note_path and not allow_existing_note:
        return False
    return task_media_file_exists(task)


def task_media_display_name(task: TaskRecord) -> str:
    media_path = task_media_path(task)
    if media_path:
        return media_path.name
    raw_path = task.media_path or task.source_media_path
    if not raw_path:
        return "本地媒体"
    try:
        return Path(raw_path).name or "本地媒体"
    except (OSError, ValueError):
        return "本地媒体"


def markdown_filename(task_id: str, title: str) -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    return f"{stem}.md"


def bundle_filename(task_id: str, title: str) -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    return f"{stem}.zip"


def media_filename(task_id: str, title: str) -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    return f"{stem}.mp4"


def media_download_filename(task: TaskRecord, path: Path) -> str:
    name = _FILENAME_RESERVED_RE.sub("_", path.name or "").strip(" ._")
    if name and name.lower() != "media.mp4":
        return name[:160]
    return media_filename(task.id, task.title)


def media_content_type(path: Path) -> str:
    stable_types = {
        ".avi": "video/x-msvideo",
        ".flv": "video/x-flv",
        ".m4v": "video/x-m4v",
        ".mkv": "video/x-matroska",
        ".mov": "video/quicktime",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
    }
    return stable_types.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def diagnostics_filename(task_id: str, title: str) -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    return f"{stem}-diagnostics.md"


def evidence_json_filename(task_id: str, title: str, suffix: str) -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    return f"{stem}-{suffix}.json"


def audit_filename(task_id: str, title: str) -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    return f"{stem}-audit.md"


def visual_windows_filename(task_id: str, title: str) -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    return f"{stem}-visual-windows.md"


def clip_filename(task_id: str, title: str, window_id: str) -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:100] or f"learnnote-{task_id}"
    safe_window = _FILENAME_RESERVED_RE.sub("_", window_id or "").strip(" ._") or "window"
    return f"{stem}-{safe_window}.mp4"


def subtitles_filename(task_id: str, title: str, suffix: str = ".srt") -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    suffix = suffix if suffix.lower() in {".srt", ".vtt", ".ass", ".ssa"} else ".srt"
    return f"{stem}-subtitles{suffix}"


def _srt_timestamp(seconds: float) -> str:
    millis = round(max(0.0, float(seconds or 0)) * 1000)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def render_transcript_srt(transcript: dict) -> str:
    blocks = []
    for index, segment in enumerate(transcript.get("segments") or [], start=1):
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        start = float(segment.get("start") or 0)
        end = float(segment.get("end") or 0)
        if end <= start:
            end = start + 0.001
        blocks.append(f"{index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def qa_filename(task_id: str, title: str) -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    return f"{stem}-qa.md"


def manifest_filename(task_id: str, title: str) -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    return f"{stem}-manifest.json"


def _format_bytes(value: int | None) -> str:
    if not value:
        return "-"
    if value >= 1024 * 1024 * 1024:
        return f"{value / 1024 / 1024 / 1024:.1f} GB"
    if value >= 1024 * 1024:
        return f"{value / 1024 / 1024:.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value} B"


def _safe_header_names(values: dict[str, str]) -> str:
    names = sorted(name for name in values if "cookie" not in name.lower() and "authorization" not in name.lower())
    return ", ".join(names) or "-"


def _has_range_header(values: dict[str, str]) -> bool:
    return any(name.lower() == "range" for name in values)


def mse_append_evidence(resource: ResourceCandidate | None) -> dict:
    if not resource:
        return {}
    evidence = {
        "append_count": resource.mse_append_count,
        "append_bytes": resource.mse_append_bytes,
        "append_total_bytes": resource.mse_append_total_bytes,
        "append_magic": resource.mse_append_magic,
        "append_mime": resource.mse_append_mime,
        "append_detected_kind": resource.mse_append_detected_kind,
        "blob_url": resource.blob_url,
    }
    return {key: value for key, value in evidence.items() if value not in (None, "")}


def _mse_append_boundary_summary(resource: ResourceCandidate | None) -> str:
    evidence = mse_append_evidence(resource)
    if not evidence:
        return ""
    kind = evidence.get("append_detected_kind") or "unknown"
    magic = evidence.get("append_magic") or "-"
    count = evidence.get("append_count") or 0
    total = _format_bytes(evidence.get("append_total_bytes"))
    return (
        "扩展已看到 MSE appendBuffer 播放证据"
        f"（类型 {kind}，magic {magic}，append {count} 次，总量 {total}），"
        "说明页面确实在播放媒体；但 appendBuffer 字节不是可下载 URL。"
    )


def _format_cookie_summary(summary: dict) -> list[str]:
    if not summary or not summary.get("total"):
        return ["- Cookie：未同步或未匹配到当前页/媒体域 Cookie"]
    domains = summary.get("domains") or {}
    domain_text = ", ".join(f"{domain} ({count})" for domain, count in sorted(domains.items())) or "-"
    return [
        f"- Cookie 总数：{summary.get('total', 0)}",
        f"- Cookie 域：{domain_text}",
        f"- Secure / HttpOnly：{summary.get('secure_count', 0)} / {summary.get('http_only_count', 0)}",
        f"- Partitioned：{summary.get('partitioned_count', 0)}（{summary.get('partition_key_count', 0)} 个 partition key）",
    ]


def _transcriber_label(value: str | None) -> str:
    return {
        "faster-whisper": "本地 faster-whisper",
        "openai-compatible": "OpenAI-compatible ASR",
        "openai-compatible-asr": "OpenAI-compatible ASR",
        "openai": "OpenAI ASR",
        "groq": "Groq ASR",
        "groq-asr": "Groq ASR",
    }.get((value or "faster-whisper").lower(), value or "ASR")


def _asr_option_text(task: TaskRecord) -> str:
    options = task.options
    return f"{_transcriber_label(options.transcriber)} · {options.whisper_model or 'small'}"


def _transcript_source_text(source: str | None) -> str:
    return {
        "browser-subtitle": "浏览器字幕",
        "page-subtitle": "页面字幕",
        "embedded-subtitle": "视频内嵌字幕",
        "faster-whisper": "本地 faster-whisper",
        "openai-compatible-asr": "OpenAI-compatible ASR",
        "groq-asr": "Groq ASR",
    }.get((source or "").lower(), source or "-")


def _task_transcript_source_text(task: TaskRecord) -> str:
    if not task.transcript_path:
        return "-"
    try:
        transcript = read_transcript(task.id)
    except Exception:
        return "-"
    source = transcript.get("source") if isinstance(transcript, dict) else None
    return _transcript_source_text(source)


def _task_transcript_source(task: TaskRecord) -> str:
    if not task.transcript_path:
        return ""
    try:
        transcript = read_transcript(task.id)
    except Exception:
        return ""
    source = transcript.get("source") if isinstance(transcript, dict) else None
    return str(source or "")


def _format_id_list(values: list[str] | tuple[str, ...] | None, limit: int = 12) -> str:
    ids = [str(value) for value in (values or []) if str(value)]
    if not ids:
        return "-"
    visible = ids[:limit]
    suffix = f" 等 {len(ids)} 个" if len(ids) > limit else ""
    return f"{', '.join(visible)}{suffix}"


def _format_timestamp(seconds: float | int | None) -> str:
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _safe_seconds(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bundle_grid_ref(path_value: str, fallback_url: str = "") -> str:
    if path_value:
        filename = Path(path_value).name
        if filename:
            return f"grids/{filename}"
    return fallback_url or "-"


def _visual_window_clip_ref(task: TaskRecord, label: str) -> str:
    if not (task.media_path or task.source_media_path):
        return "-"
    return f"/api/tasks/{quote(task.id, safe='')}/exports/clips/{quote(label, safe='')}"


def _visual_window_checkpoint_lines(window, limit: int = 3) -> list[str]:
    segments = getattr(window, "segments", []) or []
    lines: list[str] = []
    for segment in segments[:limit]:
        text = " ".join(str(getattr(segment, "text", "") or "").split())
        if not text:
            continue
        if len(text) > 96:
            text = text[:96].rstrip() + "..."
        lines.append(
            f"  - `{_format_timestamp(getattr(segment, 'start', 0) or 0)}` {text}；对照画面确认对应的板书、PPT、代码或操作步骤。"
        )
    return lines or ["  - 无同步字幕；先描述画面网格中的标题、公式、代码或界面状态，再回看原视频确认上下文。"]


def _safe_browser_request_header_names(selected: ResourceCandidate | None) -> list[str]:
    if not selected:
        return []
    return _safe_request_header_names((selected.request_headers or {}).keys())


def _safe_request_header_names(names) -> list[str]:
    return [
        name
        for name in sorted(str(name) for name in names if str(name or "").strip())
        if not re.search(r"cookie|authorization", name, re.I)
    ]


def _direct_extraction_route(task: TaskRecord) -> str:
    media_exists = task_media_file_exists(task)
    if task.source_type == "local":
        return "local_video_pipeline"
    if task.source_type == "page_text" or task.mode == "page_text":
        return "page_text_only"
    if task.mode == "download_only" and media_exists:
        return "download_only_to_local_media"
    if media_exists and task.selected_resource:
        return "browser_candidate_to_local_media"
    if media_exists:
        return "resolver_to_local_media"
    if task.download_attempts:
        return "attempted_direct_extraction"
    return "pending_or_no_media"


def direct_extraction_evidence(task: TaskRecord) -> dict:
    selected = task.selected_resource
    attempts = task.download_attempts or []
    cookie_summary = task.cookie_summary or {}
    cookie_count = cookie_summary.get("total", cookie_summary.get("cookie_count", 0))
    media_exists = task_media_file_exists(task)
    successful_attempts = [attempt for attempt in attempts if attempt.status == "success"]
    failed_attempts = [attempt for attempt in attempts if attempt.status == "failed"]
    strategy_order: list[str] = []
    for attempt in attempts:
        if attempt.strategy and attempt.strategy not in strategy_order:
            strategy_order.append(attempt.strategy)

    active = task.active_video
    active_source_type = "-"
    if active:
        if active.src_object and not active.src:
            active_source_type = active.src_object_type or "MediaStream/srcObject"
        elif active.src.startswith("blob:"):
            active_source_type = "blob"
        elif active.src.startswith(("http://", "https://")):
            active_source_type = "visible_url"
        elif active.src:
            active_source_type = "player_source"

    drm_detected = bool(task.drm_detected or (active and active.drm_detected))
    route = _direct_extraction_route(task)
    boundary = "normal_accessible_media_only"
    if drm_detected:
        boundary = "drm_or_encrypted_not_bypassed"
    elif active and active.src_object and not active.src:
        boundary = "mediastream_not_recorded"
    elif selected and selected.kind in {"blob", "fragment"} and not media_exists:
        boundary = "unresolved_blob_or_fragment_not_recorded"
    elif task.error_code:
        boundary = task.error_code

    return {
        "no_tab_recording": True,
        "no_drm_bypass": True,
        "route": route,
        "media_landed": media_exists,
        "media_reusable": media_exists,
        "selected_candidate": {
            "present": bool(selected),
            "kind": selected.kind if selected else "",
            "source": selected.source if selected else "",
            "user_selected": selected.user_selected if selected else False,
            "is_main_video": selected.is_main_video if selected else False,
            "playback_match": selected.playback_match if selected else "",
            "request_type": selected.request_type if selected else "",
            "status_code": selected.status_code if selected else None,
            "content_length": selected.content_length if selected else None,
            "has_resolved_url": bool(selected and selected.resolved_url),
            "has_blob_mapping": bool(selected and selected.blob_url and selected.url and selected.url != selected.blob_url),
            "has_replay_body": bool(selected and (selected.request_body or {}).get("content")),
            "safe_request_header_names": _safe_browser_request_header_names(selected),
        },
        "browser_context": {
            "active_source_type": active_source_type,
            "active_frame_id": active.frame_id if active else None,
            "active_time_seconds": active.current_time if active else None,
            "browser_subtitle_count": len(task.browser_subtitles or []),
            "cookie_domain_count": int(cookie_summary.get("domain_count") or 0),
            "cookie_count": int(cookie_count or 0),
            "partitioned_cookie_count": int(cookie_summary.get("partitioned_count") or 0),
            "partition_key_count": int(cookie_summary.get("partition_key_count") or 0),
        },
        "download": {
            "attempt_count": len(attempts),
            "successful_attempt_count": len(successful_attempts),
            "failed_attempt_count": len(failed_attempts),
            "strategy_order": strategy_order,
            "latest_code": attempts[-1].code if attempts else "",
            "latest_status": attempts[-1].status if attempts else "",
        },
        "processing": {
            "download_only": task.mode == "download_only",
            "transcript_ready": bool(task.transcript_path),
            "frame_grid_count": len(task.frame_grids),
            "visual_window_count": len(task.visual_windows),
            "note_ready": bool(task.note_path),
        },
        "boundary": boundary,
        "fallback_available": bool(media_exists or task.page_url or task.source_type == "local"),
    }


def playback_evidence(task: TaskRecord) -> dict:
    active = task.active_video
    selected = task.selected_resource
    return {
        "active_video": {
            "present": bool(active),
            "source_type": "srcObject" if active and active.src_object else "url" if active and active.src else "",
            "current_time": active.current_time if active else None,
            "duration": active.duration if active else None,
            "paused": active.paused if active else None,
            "frame_id": active.frame_id if active else None,
            "width": active.width if active else None,
            "height": active.height if active else None,
            "label": active.label if active else "",
            "drm_detected": active.drm_detected if active else False,
        },
        "selected_resource": {
            "present": bool(selected),
            "is_main_video": selected.is_main_video if selected else False,
            "playback_match": selected.playback_match if selected else "",
            "current_time": selected.current_time if selected else None,
            "duration": selected.duration if selected else None,
            "width": selected.width if selected else None,
            "height": selected.height if selected else None,
            "frame_id": selected.frame_id if selected else None,
            "blob_mapped": bool(selected and selected.blob_url and selected.url and selected.url != selected.blob_url),
        },
        "matched_current_playback": bool(selected and (selected.is_main_video or selected.playback_match)),
    }


def _render_study_manifest(task: TaskRecord) -> dict:
    visual_windows = task.visual_windows or []
    diagnostics = task.summary_diagnostics or {}
    sent_ids = set(str(value) for value in diagnostics.get("vision_image_window_ids") or [])
    missing_ids = set(str(value) for value in diagnostics.get("missing_vision_image_window_ids") or [])
    omitted_ids = set(str(value) for value in diagnostics.get("omitted_vision_window_ids") or [])
    windows_with_transcript = sum(1 for window in visual_windows if str(window.transcript_excerpt or "").strip())
    windows = []
    checkpoint_count = 0
    review_question_count = 0

    for index, window in enumerate(visual_windows, start=1):
        window_id = window.id or f"W{index:03d}"
        checkpoints = _visual_window_checkpoint_lines(window)
        review_questions = visual_window_review_question_lines(window)
        checkpoint_count += len(checkpoints)
        review_question_count += len(review_questions)
        if window_id in sent_ids:
            vision_status = "sent_to_vision"
        elif window_id in missing_ids:
            vision_status = "missing_grid_image"
        elif window_id in omitted_ids:
            vision_status = "omitted_by_limit"
        elif diagnostics:
            vision_status = "not_sent"
        else:
            vision_status = "unknown"
        windows.append({
            "id": window_id,
            "start": window.start,
            "end": window.end,
            "grid_entry": _bundle_grid_ref(window.grid_path, window.grid_url),
            "frame_count": window.frame_count,
            "frame_timestamps": window.frame_timestamps,
            "transcript_segment_count": len(window.segments or []),
            "has_transcript_excerpt": bool(str(window.transcript_excerpt or "").strip()),
            "vision_status": vision_status,
            "checkpoint_count": len(checkpoints),
            "review_question_count": len(review_questions),
            "checkpoints": checkpoints,
            "review_questions": review_questions,
        })

    return {
        "review_deck": "visual_windows.md" if visual_windows or task.frame_grids else "",
        "window_count": len(visual_windows),
        "windows_with_transcript": windows_with_transcript,
        "windows_without_transcript": max(0, len(visual_windows) - windows_with_transcript),
        "checkpoint_count": checkpoint_count,
        "review_question_count": review_question_count,
        "vision_sent_count": len(sent_ids),
        "vision_missing_image_count": len(missing_ids),
        "vision_omitted_count": len(omitted_ids),
        "windows": windows,
    }


def _visual_window_vision_status_text(task: TaskRecord, label: str) -> str:
    diagnostics = task.summary_diagnostics or {}
    if not diagnostics:
        return "未知（未生成 summary_diagnostics）"
    if label in set(str(value) for value in diagnostics.get("vision_image_window_ids") or []):
        return "已送入视觉模型"
    if label in set(str(value) for value in diagnostics.get("missing_vision_image_window_ids") or []):
        return "未送入：缺少网格图片"
    if label in set(str(value) for value in diagnostics.get("omitted_vision_window_ids") or []):
        return "未送入：超过视觉窗口上限"
    if diagnostics.get("used_vision_llm"):
        return "未送入视觉模型"
    if diagnostics.get("visual_understanding") is False:
        return "未启用图文理解"
    return "未送入视觉模型"


def render_visual_windows_markdown(task: TaskRecord) -> str:
    direct = direct_extraction_evidence(task)
    selected = direct.get("selected_candidate") or {}
    route = direct.get("route") or "-"
    boundary = direct.get("boundary") or "-"
    media_state = "yes" if direct.get("media_landed") else "no"
    candidate = " / ".join(
        str(value)
        for value in [
            selected.get("kind") or "",
            selected.get("source") or "",
            selected.get("playback_match") or "",
        ]
        if value
    ) or "-"
    lines = [
        "# LearnNote 画面切片索引",
        "",
        f"- 任务：{task.title}",
        f"- ID：{task.id}",
        f"- 页面：{task.page_url or '-'}",
        "- 说明：本索引对应资料包 `grids/` 目录中的网格图，可和 `transcript.json`、`visual_index.json` 交叉回看。",
        "",
        "## 资料包导览",
        "- 先看本文件的 W 编号和时间段，再打开 `grids/` 中对应网格图核对 PPT、板书、代码或操作步骤。",
        "- 字幕摘录来自同一时间窗口；需要完整上下文时查看 `transcript.json` 或 `note.md`。",
        "- `manifest.json` 记录任务路线、直取证据、审计门和产物列表，便于复盘这次总结是否用了当前页直取或本地视频。",
        "",
        "## 直取边界",
        "- 不录制标签页：yes",
        "- 不绕过 DRM/EME：yes",
        f"- 任务路线：{route}",
        f"- 边界说明：{boundary}",
        f"- 媒体落地：{media_state}",
        f"- 已选候选：{candidate}",
        "",
    ]

    if task.visual_windows:
        for index, window in enumerate(task.visual_windows, start=1):
            label = window.id or f"W{index:03d}"
            grid_ref = _bundle_grid_ref(window.grid_path, window.grid_url)
            lines.extend([
                f"## {label} `{_format_timestamp(window.start)} - {_format_timestamp(window.end)}`",
                f"- 画面网格：{grid_ref}",
                f"- 视频片段：{_visual_window_clip_ref(task, label)}",
                f"- 视觉模型：{_visual_window_vision_status_text(task, label)}",
                f"- 帧数：{window.frame_count}",
                f"- 帧时间：{', '.join(_format_timestamp(value) for value in window.frame_timestamps) or '-'}",
            ])
            if window.transcript_excerpt.strip():
                lines.extend(["", window.transcript_excerpt.strip()])
            else:
                lines.append("- 字幕摘录：-")
            lines.append("")
            lines.append("- 回看检查点：")
            lines.extend(_visual_window_checkpoint_lines(window))
            lines.append("- 自测问题：")
            lines.extend(visual_window_review_question_lines(window))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    if task.frame_grids:
        for index, grid in enumerate(task.frame_grids, start=1):
            label = f"W{index:03d}"
            lines.extend([
                f"## {label} `{_format_timestamp(grid.start)} - {_format_timestamp(grid.end)}`",
                f"- 画面网格：{_bundle_grid_ref(grid.path, grid.url)}",
                f"- 视频片段：{_visual_window_clip_ref(task, label)}",
                f"- 帧数：{grid.frame_count}",
                f"- 帧时间：{', '.join(_format_timestamp(value) for value in grid.frame_timestamps) or '-'}",
                "",
            ])
        return "\n".join(lines).rstrip() + "\n"

    lines.append("- 暂无画面切片。")
    return "\n".join(lines) + "\n"


def _audit_report_text(value: object) -> str:
    text = str(value or "-")
    text = text.replace("Authorization", "鉴权类敏感请求头")
    return text


def render_task_audit_markdown(task: TaskRecord) -> str:
    audit = task_audit_summary(task)
    direct = direct_extraction_evidence(task)
    reuse = task_reuse_evidence(task)
    recovery = diagnostic_recovery_profile(task)
    selected = direct.get("selected_candidate") or {}
    browser = direct.get("browser_context") or {}
    download = direct.get("download") or {}
    processing = direct.get("processing") or {}
    playback = playback_evidence(task)
    active_playback = playback.get("active_video") or {}
    selected_playback = playback.get("selected_resource") or {}
    safe_headers = selected.get("safe_request_header_names") or []
    gates = audit.get("gates") or []
    lines = [
        "# LearnNote 任务审计报告",
        "",
        "## 任务",
        f"- ID：{task.id}",
        f"- 标题：{task.title or '-'}",
        f"- 来源：{task.source_type or '-'} / {task.mode or '-'}",
        f"- 页面：{task.page_url or '-'}",
        f"- 状态：{task.status} / {task.phase} / {task.progress or 0}%",
        f"- 错误：{task.error_code or '-'} / {task.error_detail or '-'}",
        "",
        "## 直取边界",
        f"- 不录制标签页：{'yes' if direct.get('no_tab_recording') else 'no'}",
        f"- 不绕过 DRM：{'yes' if direct.get('no_drm_bypass') else 'no'}",
        f"- 路线：{direct.get('route') or '-'}",
        f"- 边界：{direct.get('boundary') or '-'}",
        f"- 媒体落地：{'yes' if direct.get('media_landed') else 'no'}",
        f"- 媒体可复用：{'yes' if direct.get('media_reusable') else 'no'}",
        "",
        "## 浏览器证据",
        f"- 候选：{selected.get('kind') or '-'} / {selected.get('source') or '-'} / {selected.get('playback_match') or '-'}",
        f"- 用户选择：{'yes' if selected.get('user_selected') else 'no'}",
        f"- 安全请求头名：{', '.join(safe_headers) if safe_headers else '-'}",
        f"- 播放源：{browser.get('active_source_type') or '-'}",
        f"- 当前播放：{active_playback.get('source_type') or '-'} / {_format_timestamp(active_playback.get('current_time'))}"
        f" / {_format_timestamp(active_playback.get('duration'))} / paused {'yes' if active_playback.get('paused') else 'no'}"
        f" / frame {active_playback.get('frame_id') if active_playback.get('frame_id') is not None else '-'}"
        f" / {active_playback.get('width') or 0}x{active_playback.get('height') or 0}",
        f"- 选中资源播放匹配：{'yes' if playback.get('matched_current_playback') else 'no'}"
        f" / {selected_playback.get('playback_match') or '-'}"
        f" / {_format_timestamp(selected_playback.get('current_time'))}"
        f" / {_format_timestamp(selected_playback.get('duration'))}",
        f"- 浏览器字幕：{browser.get('browser_subtitle_count') or 0} 条",
        f"- Cookie：{browser.get('cookie_count') or 0} / {browser.get('cookie_domain_count') or 0} 域",
        f"- 分区 Cookie：{browser.get('partitioned_cookie_count') or 0} / {browser.get('partition_key_count') or 0} partition key",
        "",
        "## 下载与处理",
        f"- 下载尝试：成功 {download.get('successful_attempt_count') or 0} / 失败 {download.get('failed_attempt_count') or 0}",
        f"- 策略顺序：{', '.join(download.get('strategy_order') or []) or '-'}",
        f"- 转写：{'yes' if processing.get('transcript_ready') else 'no'}",
        f"- 画面网格：{processing.get('frame_grid_count') or 0}",
        f"- 视觉窗口：{processing.get('visual_window_count') or 0}",
        f"- 笔记：{'yes' if processing.get('note_ready') else 'no'}",
        "",
        "## 阶段审计门",
        f"- 放行：{audit.get('released_count', 0)}/{audit.get('gate_count', len(gates))}",
        f"- 阻塞阶段：{audit.get('blocked_gate') or '-'}",
    ]
    for gate in gates:
        lines.append(
            "- "
            f"{_audit_report_text(gate.get('label') or gate.get('key'))}: "
            f"{_audit_report_text(gate.get('state'))} / "
            f"{_audit_report_text(gate.get('value'))} / "
            f"{_audit_report_text(gate.get('detail'))}"
        )

    lines.extend([
        "",
        "## 复用证据",
        f"- 媒体存在：{'yes' if reuse.get('media_available') else 'no'}",
        f"- 媒体路径记录：{reuse.get('media_path_recorded') or '-'}",
        f"- 来源任务：{reuse.get('source_task_id') or '-'}",
        f"- 来源媒体：{reuse.get('source_media_path') or '-'}",
        f"- 浏览器字幕跨度：{reuse.get('browser_subtitle_span_seconds') or 0}s",
        f"- 可从媒体继续：{'yes' if reuse.get('rerun_from_media_ready') else 'no'}",
        f"- 建议下一步：{reuse.get('suggested_next_step') or '-'}",
        "",
        "## 恢复建议",
        f"- 判断：{recovery.get('diagnosis') or '-'}",
        f"- 推荐动作：{recovery.get('next_action') or '-'}",
    ])
    for step in recovery.get("steps", []):
        lines.append(f"- {_audit_report_text(step)}")

    lines.extend([
        "",
        "## 敏感信息处理",
        "- 本报告不包含 Cookie 值。",
        "- 鉴权类敏感请求头不会写入审计报告。",
        "- 当前页直取失败时，本工具不会改用标签页录制、破解 DRM 或伪造学习进度。",
        "",
    ])
    return "\n".join(lines)


def read_resource_inventory(task: TaskRecord) -> dict:
    path_value = task.resource_inventory_path or ""
    if path_value:
        path = Path(path_value)
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
    return read_json(task.id, "resource_inventory.json", {}) or {}


def read_page_preflight_report(task: TaskRecord) -> dict:
    path_value = task.page_preflight_report_path or ""
    if path_value:
        path = Path(path_value)
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
    return read_json(task.id, "page_preflight_report.json", {}) or {}


def render_bundle_manifest(task: TaskRecord, transcript: dict, visual_index: dict) -> dict:
    selected = task.selected_resource
    resource_inventory = read_resource_inventory(task)
    page_preflight = read_page_preflight_report(task)
    chaoxing_profile = chaoxing_evidence_profile(task)
    append_evidence = mse_append_evidence(selected)
    options_payload = task.options.model_dump(mode="json")
    if options_payload.get("llm_api_key"):
        options_payload["llm_api_key"] = "<redacted>"
    segments = transcript.get("segments") if isinstance(transcript, dict) else []
    if not isinstance(segments, list):
        segments = []
    first_segment = segments[0] if segments else {}
    last_segment = segments[-1] if segments else {}
    visual_windows = task.visual_windows or []
    first_window = visual_windows[0] if visual_windows else None
    last_window = visual_windows[-1] if visual_windows else None
    request_header_names = _safe_browser_request_header_names(selected)
    response_header_names = sorted((selected.headers or {}).keys()) if selected else []
    grid_entries = [
        f"grids/{Path(grid.path).name}"
        for grid in task.frame_grids
        if Path(grid.path).name
    ]
    qa_history = read_task_qa_history(task.id)
    source_quality, evidence_quality = task_source_evidence_quality(task)
    source_media_integrity = task.media_integrity.model_dump(mode="json")
    exported_media_integrity: dict = {}
    exported_media = task_media_path(task)
    if exported_media and exported_media.is_file():
        try:
            exported_media_integrity = probe_media_integrity(exported_media).model_dump(mode="json")
        except (MediaProcessingError, OSError):
            exported_media_integrity = {}

    return {
        "schema_version": 1,
        "generator": "learnnote-assistant",
        "task": {
            "id": task.id,
            "title": task.title,
            "source_type": task.source_type,
            "mode": task.mode,
            "status": task.status,
            "phase": task.phase,
            "progress": task.progress,
            "page_url": task.page_url,
            "source_task_id": task.source_task_id,
            "source_media_path": task.source_media_path,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "error_code": task.error_code,
            "error_detail": task.error_detail,
        },
        "options": options_payload,
        "source_quality": source_quality,
        "evidence_quality": evidence_quality,
        "media_integrity": {
            "source": source_media_integrity,
            "exported": exported_media_integrity,
            "same_file": bool(
                source_media_integrity.get("sha256")
                and source_media_integrity.get("sha256") == exported_media_integrity.get("sha256")
            ),
        },
        "source": {
            "resource_inventory": {
                "export": "resource_inventory.json" if resource_inventory else "",
                "candidate_count": int(resource_inventory.get("candidate_count") or 0) if resource_inventory else 0,
                "downloadable_candidate_count": int(resource_inventory.get("downloadable_candidate_count") or 0) if resource_inventory else 0,
                "replayable_candidate_count": int(resource_inventory.get("replayable_candidate_count") or 0) if resource_inventory else 0,
                "kind_counts": resource_inventory.get("kind_counts", {}) if resource_inventory else {},
                "source_counts": resource_inventory.get("source_counts", {}) if resource_inventory else {},
            },
            "page_preflight_report": {
                "export": "page_preflight_report.json" if page_preflight else "",
                "ready": bool(page_preflight.get("ready")) if page_preflight else False,
                "code": page_preflight.get("code", "") if page_preflight else "",
                "selected_url": page_preflight.get("selected_url", "") if page_preflight else "",
                "candidate_count": int(page_preflight.get("candidate_count") or 0) if page_preflight else 0,
                "probed_count": int(page_preflight.get("probed_count") or 0) if page_preflight else 0,
                "downloadable_count": int(page_preflight.get("downloadable_count") or 0) if page_preflight else 0,
                "page_scan_attempted": bool((page_preflight.get("page_scan") or {}).get("attempted")) if page_preflight else False,
            },
            "selected_resource": {
                "url": selected.url if selected else "",
                "resolved_url": selected.resolved_url if selected else "",
                "kind": selected.kind if selected else "",
                "source": selected.source if selected else "",
                "mime": selected.mime if selected else "",
                "score": selected.score if selected else 0,
                "is_main_video": selected.is_main_video if selected else False,
                "playback_match": selected.playback_match if selected else "",
                "blob_url": selected.blob_url if selected else "",
                "frame_url": selected.frame_url if selected else "",
                "request_type": selected.request_type if selected else "",
                "method": selected.method if selected else "",
                "status_code": selected.status_code if selected else None,
                "content_length": selected.content_length if selected else None,
                "mse_append_evidence": append_evidence,
                "request_header_names": request_header_names,
                "response_header_names": response_header_names,
            } if selected else None,
            "download_attempts": [
                {
                    "strategy": attempt.strategy,
                    "source": attempt.source,
                    "kind": attempt.kind,
                    "status": attempt.status,
                    "code": attempt.code,
                    "status_code": attempt.status_code,
                    "content_length": attempt.content_length,
                    "bytes_downloaded": attempt.bytes_downloaded,
                    "mime": attempt.mime,
                    "url": attempt.url,
                    "resolved_url": attempt.resolved_url,
                    "request_header_names": _safe_request_header_names(attempt.request_header_names),
                    "companion_audio_url": attempt.companion_audio_url,
                    "companion_audio_mime": attempt.companion_audio_mime,
                }
                for attempt in task.download_attempts
            ],
            "drm_detected": task.drm_detected,
            "drm_signal_count": len(task.drm_signals),
            "playback": playback_evidence(task),
        },
        "transcript": {
            "source": transcript.get("source", "") if isinstance(transcript, dict) else "",
            "language": transcript.get("language", "") if isinstance(transcript, dict) else "",
            "warning": transcript.get("warning", "") if isinstance(transcript, dict) else "",
            "segment_count": len(segments),
            "start": first_segment.get("start") if isinstance(first_segment, dict) else None,
            "end": last_segment.get("end") if isinstance(last_segment, dict) else None,
        },
        "visual": {
            "window_count": len(visual_windows),
            "frame_grid_count": len(task.frame_grids),
            "start": first_window.start if first_window else None,
            "end": last_window.end if last_window else None,
            "visual_index_window_count": len(visual_index.get("windows", [])) if isinstance(visual_index, dict) else 0,
            "summary_diagnostics": task.summary_diagnostics,
        },
        "study": _render_study_manifest(task),
        "next_actions": task_next_actions(task),
        "qa": {
            "history_count": len(qa_history),
            "export": "qa.md" if qa_history else "",
            "history": QA_HISTORY_FILE if qa_history else "",
            "last_question": qa_history[-1].get("question", "") if qa_history else "",
            "last_source": qa_history[-1].get("source", "") if qa_history else "",
            "suggestions": task_qa_suggestions(task),
        },
        "artifacts": {
            "note": "note.md" if task.note_path else "",
            "subtitles": (
                f"subtitles/{Path(task.subtitle_path).name}"
                if task.subtitle_path
                else "subtitles/generated-transcript.srt"
                if task.transcript_path and transcript.get("segments")
                else ""
            ),
            "audit": "audit.md",
            "diagnostics": "diagnostics.md",
            "qa": "qa.md" if qa_history else "",
            "qa_history": QA_HISTORY_FILE if qa_history else "",
            "visual_windows": "visual_windows.md" if task.visual_windows or task.frame_grids else "",
            "task": "task.json",
            "transcript": "transcript.json",
            "visual_index": "visual_index.json",
            "summary_diagnostics": "summary_diagnostics.json" if task.summary_diagnostics else "",
            "resource_inventory": "resource_inventory.json" if resource_inventory else "",
            "page_preflight_report": "page_preflight_report.json" if page_preflight else "",
            "media_available": task_media_file_exists(task),
            "grid_entries": grid_entries,
        },
        "direct_extraction": direct_extraction_evidence(task),
        "site_profiles": {
            "chaoxing": chaoxing_profile,
        },
        "audit": task_audit_summary(task),
        "recovery": diagnostic_recovery_profile(task),
        "reuse": task_reuse_evidence(task),
    }


def _is_chaoxing_task(task: TaskRecord) -> bool:
    values = [
        task.page_url,
        task.title,
        task.error_detail,
        task.selected_resource.url if task.selected_resource else "",
        task.selected_resource.resolved_url if task.selected_resource else "",
        task.selected_resource.initiator if task.selected_resource else "",
        task.selected_resource.label if task.selected_resource else "",
    ]
    for attempt in task.download_attempts:
        values.extend([attempt.url, attempt.resolved_url, attempt.source, attempt.message])
    text = " ".join(str(value or "").lower() for value in values)
    return bool(re.search(r"chaoxing|xuexitong|fanya|mooc1|mooc2|ananas|学习通|超星", text, re.I))


def _string_contains_chaoxing_signal(value: object) -> bool:
    return bool(re.search(r"chaoxing|xuexitong|fanya|mooc1|mooc2|ananas|objectid|dtoken|httpmd", str(value or ""), re.I))


def _candidate_entries_for_site_profile(task: TaskRecord) -> list[dict]:
    entries: list[dict] = []

    def add(value: object, source: str) -> None:
        if not value:
            return
        if hasattr(value, "model_dump"):
            payload = value.model_dump(mode="json")
        elif isinstance(value, dict):
            payload = dict(value)
        else:
            return
        payload["_profile_source"] = source
        entries.append(payload)

    add(task.selected_resource, "selected_resource")
    for attempt in task.download_attempts or []:
        add(attempt, "download_attempt")

    inventory = read_resource_inventory(task)
    for candidate in inventory.get("candidates") or []:
        add(candidate, "resource_inventory")

    page_preflight = read_page_preflight_report(task)
    for item in page_preflight.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        resource = item.get("resource") or {}
        if isinstance(resource, dict):
            payload = dict(resource)
            preflight = item.get("preflight") or {}
            payload["_profile_source"] = "page_preflight"
            payload["_preflight_rank"] = item.get("rank")
            payload["_preflight_code"] = preflight.get("code") if isinstance(preflight, dict) else ""
            payload["_preflight_strategy"] = preflight.get("strategy") if isinstance(preflight, dict) else ""
            entries.append(payload)

    return entries


def chaoxing_evidence_profile(task: TaskRecord) -> dict:
    entries = _candidate_entries_for_site_profile(task)
    page_preflight = read_page_preflight_report(task)
    cookie_summary = task.cookie_summary or {}
    text_parts = [
        task.page_url,
        task.title,
        task.error_detail,
        json.dumps(page_preflight, ensure_ascii=False) if page_preflight else "",
        json.dumps(cookie_summary, ensure_ascii=False) if cookie_summary else "",
    ]
    text_parts.extend(json.dumps(entry, ensure_ascii=False) for entry in entries)
    all_text = " ".join(text_parts).lower()
    detected = _is_chaoxing_task(task) or _string_contains_chaoxing_signal(all_text)

    safe_header_names: set[str] = set()
    all_header_names: set[str] = set()
    candidate_sources: set[str] = set()
    candidate_kinds: set[str] = set()
    ananas_candidate_count = 0
    replay_body_count = 0
    iframe_context_count = 0

    for entry in entries:
        url_text = " ".join(str(entry.get(key) or "") for key in ("url", "resolved_url", "frame_url", "page_url", "initiator", "label"))
        if re.search(r"ananas|objectid|dtoken|httpmd", url_text, re.I):
            ananas_candidate_count += 1
        if entry.get("request_body"):
            replay_body_count += 1
        if entry.get("frame_url") or entry.get("frame_id") is not None or entry.get("initiator"):
            iframe_context_count += 1
        source = str(entry.get("source") or entry.get("strategy") or entry.get("_profile_source") or "")
        kind = str(entry.get("kind") or "")
        if source:
            candidate_sources.add(source)
        if kind:
            candidate_kinds.add(kind)
        request_headers = entry.get("request_headers") or {}
        if isinstance(request_headers, dict):
            all_header_names.update(str(name) for name in request_headers)
            safe_header_names.update(_safe_request_header_names(request_headers.keys()))
        request_header_names = entry.get("request_header_names") or []
        if isinstance(request_header_names, list):
            all_header_names.update(str(name) for name in request_header_names)
            safe_header_names.update(_safe_request_header_names(request_header_names))

    lower_header_names = {name.lower() for name in all_header_names}
    page_scan = page_preflight.get("page_scan") if isinstance(page_preflight, dict) else {}
    if not isinstance(page_scan, dict):
        page_scan = {}

    issue = "no_chaoxing_signal"
    codes = _task_failure_codes(task)
    if detected:
        if not ananas_candidate_count and not page_preflight:
            issue = "playback_api_not_observed"
        elif not cookie_summary.get("total"):
            issue = "login_cookie_not_synced"
        elif "download_forbidden" in codes:
            issue = "anti_hotlink_or_expired_signature"
        elif "auth_required" in codes:
            issue = "auth_required"
        elif task.error_code:
            issue = task.error_code
        else:
            issue = "evidence_ready"

    return {
        "detected": bool(detected),
        "candidate_count": len(entries),
        "ananas_candidate_count": ananas_candidate_count,
        "has_ananas_candidate": ananas_candidate_count > 0,
        "has_playurl": bool(re.search(r"play_?url|playURL", all_text, re.I)),
        "has_objectid": "objectid" in all_text,
        "has_dtoken": "dtoken" in all_text,
        "has_httpmd": "httpmd" in all_text,
        "has_replay_body": replay_body_count > 0,
        "replay_body_count": replay_body_count,
        "has_referer": "referer" in lower_header_names,
        "has_origin": "origin" in lower_header_names,
        "has_x_requested_with": "x-requested-with" in lower_header_names,
        "has_iframe_context": iframe_context_count > 0,
        "iframe_context_count": iframe_context_count,
        "cookie_count": int(cookie_summary.get("total") or 0),
        "cookie_domain_count": int(cookie_summary.get("domain_count") or 0),
        "partitioned_cookie_count": int(cookie_summary.get("partitioned_count") or 0),
        "partition_key_count": int(cookie_summary.get("partition_key_count") or 0),
        "has_partitioned_cookies": int(cookie_summary.get("partitioned_count") or 0) > 0,
        "safe_request_header_names": sorted(safe_header_names),
        "candidate_sources": sorted(candidate_sources),
        "candidate_kinds": sorted(candidate_kinds),
        "page_preflight": {
            "present": bool(page_preflight),
            "ready": bool(page_preflight.get("ready")) if isinstance(page_preflight, dict) else False,
            "candidate_count": int(page_preflight.get("candidate_count") or 0) if isinstance(page_preflight, dict) else 0,
            "probed_count": int(page_preflight.get("probed_count") or 0) if isinstance(page_preflight, dict) else 0,
            "downloadable_count": int(page_preflight.get("downloadable_count") or 0) if isinstance(page_preflight, dict) else 0,
            "page_scan_attempted": bool(page_scan.get("attempted")),
            "page_scan_discovered_count": int(page_scan.get("discovered_count") or 0),
        },
        "likely_issue": issue,
        "boundary": "no_recording_no_progress_forgery",
    }


def _task_failure_codes(task: TaskRecord) -> set[str]:
    codes = {task.error_code} if task.error_code else set()
    codes.update(attempt.code for attempt in task.download_attempts if attempt.code)
    return codes


def diagnostic_recovery_steps(task: TaskRecord) -> list[str]:
    codes = _task_failure_codes(task)
    steps: list[str] = []

    def add(text: str) -> None:
        if text and text not in steps:
            steps.append(text)

    if _is_chaoxing_task(task):
        add("检测到学习通/超星页面线索：请先在原课程页真实播放几秒，让 ananas/播放接口暴露 m3u8、mp4 或带 Referer 的媒体请求；本工具只复用你当前登录态可访问的资源，不刷课、不伪造进度、不自动答题。")
    if "drm_or_encrypted" in codes or task.drm_detected:
        add("页面触发 DRM/EME 或只暴露不可还原 blob 时，本工具不会录制、破解或绕过 DRM；请改用本地视频入口。")
    mse_boundary_summary = _mse_append_boundary_summary(task.selected_resource)
    if mse_boundary_summary:
        add(f"{mse_boundary_summary} 请继续播放几秒并重新检测真实 manifest/mp4 请求；如果仍只有 blob/MSE 证据，就使用本地视频入口。")
    if "auth_required" in codes:
        add("重新打开课程页面并确认登录有效，播放几秒后立刻从扩展侧栏重新创建任务，让 Cookie 和媒体请求保持新鲜。")
    if "download_forbidden" in codes:
        add("媒体服务器拒绝下载时，优先检查 Referer/Origin、登录态和时效签名；回到原页面继续播放后重新检测，或选择另一个候选资源。")
    if "unsupported_manifest" in codes:
        add("如果只有分片或无法合并的 manifest，继续播放后重新检测，优先选择完整 mp4/FLV/m3u8/mpd 候选。")
    if "no_media_found" in codes or (task.status == "failed" and not task.download_attempts):
        add("当前页没有暴露可直取媒体时，先让视频实际播放几秒再重检；仍失败就使用本地视频上传。")
    if task.selected_resource and task.selected_resource.request_headers:
        add(f"已捕获可复用请求头名：{_safe_header_names(task.selected_resource.request_headers)}；诊断中不会保存 Cookie 或 Authorization 值。")
    if task.selected_resource and _has_range_header(task.selected_resource.request_headers):
        add("Range 只作为浏览器播放证据；正式下载会去掉播放 Range，避免只保存一个视频片段。")
    if len(task.download_attempts) > 1:
        add(f"后端已尝试 {len(task.download_attempts)} 条路线；查看上方下载尝试，优先处理第一个失败的直接媒体候选。")
    if task.status == "failed" and task.note_path:
        add("视频直取失败但已有兜底笔记时，可先导出 Markdown/资料包复习，再根据诊断重新尝试直取。")
    if not steps:
        add("如果任务未完成，先查看下载尝试的错误码；当前页直取失败时可以改用本地视频入口走同一套切片总结。")
    return steps


def _recovery_action(action: str, *, detail: str = "", priority: str = "secondary", task: TaskRecord | None = None) -> dict[str, str]:
    media_name = task_media_display_name(task) if task is not None else "本地媒体"
    action_map = {
        "local_upload": {
            "label": "上传本地视频",
            "ui_intent": "local_upload",
            "detail": "改用本地文件，继续走同一套转写、切片、视觉窗口和总结管线。",
        },
        "refresh_login_and_retry": {
            "label": "重新登录后重检",
            "ui_intent": "retry_current_page",
            "detail": "回到原课程页确认登录有效，播放几秒后从扩展重新检测并创建任务。",
        },
        "refresh_playback_and_retry": {
            "label": "继续播放后重检",
            "ui_intent": "retry_current_page",
            "detail": "回到原页面继续播放，让 Referer、Cookie 和时效签名保持新鲜后重试。",
        },
        "play_longer_and_redetect": {
            "label": "播放更久后重检",
            "ui_intent": "retry_current_page",
            "detail": "让播放器继续加载完整 manifest，再从扩展重新检测候选资源。",
        },
        "play_and_redetect": {
            "label": "播放几秒后重检",
            "ui_intent": "retry_current_page",
            "detail": "先让视频真实播放，等待 mp4、m3u8、mpd 或播放接口请求暴露。",
        },
        "inspect_diagnostics": {
            "label": "查看下载诊断",
            "ui_intent": "inspect_diagnostics",
            "detail": "查看每条下载路线的 URL、状态码、错误码和请求头证据。",
        },
        "continue_from_media": {
            "label": "继续切片总结",
            "ui_intent": "continue_from_media",
            "detail": f"复用已下载到本地的 {media_name}，继续生成字幕、画面网格和笔记。",
        },
        "inspect_audit": {
            "label": "查看阶段审计",
            "ui_intent": "inspect_audit",
            "detail": "检查媒体、转写、切片、总结各阶段产物是否齐全。",
        },
        "export_markdown": {
            "label": "导出 Markdown",
            "ui_intent": "export_markdown",
            "detail": "先导出现有笔记复习，再按诊断重新尝试直取。",
        },
        "export_diagnostics": {
            "label": "导出诊断",
            "ui_intent": "export_diagnostics",
            "detail": "导出诊断文件，便于复现登录态、签名或 manifest 问题。",
        },
        "export_audit": {
            "label": "导出审计",
            "ui_intent": "export_audit",
            "detail": "导出阶段门报告，确认失败发生在哪个处理阶段。",
        },
    }
    base = dict(action_map.get(action, action_map["inspect_diagnostics"]))
    base["key"] = action
    base["priority"] = priority
    if detail:
        base["detail"] = detail
    return base


def _diagnostic_recovery_actions(task: TaskRecord, primary_action_key: str) -> list[dict[str, str]]:
    actions = [_recovery_action(primary_action_key, priority="primary", task=task)]
    existing = {primary_action_key}
    codes = _task_failure_codes(task)

    def add(action_key: str) -> None:
        if action_key not in existing:
            actions.append(_recovery_action(action_key, task=task))
            existing.add(action_key)

    if task_media_ready_for_rerun(task, allow_existing_note=True):
        add("continue_from_media")
    if primary_action_key == "export_markdown":
        if "auth_required" in codes:
            add("refresh_login_and_retry")
        elif "unsupported_manifest" in codes:
            add("play_longer_and_redetect")
        elif "no_media_found" in codes:
            add("play_and_redetect")
        else:
            add("refresh_playback_and_retry")
    if primary_action_key != "local_upload":
        add("local_upload")
    add("inspect_diagnostics")
    if task.note_path:
        add("export_markdown")
    add("export_audit")
    if task.summary_diagnostics_path or task.download_attempts or task.selected_resource or task.error_code:
        add("export_diagnostics")
    return actions


def diagnostic_recovery_profile(task: TaskRecord) -> dict:
    codes = _task_failure_codes(task)
    selected = task.selected_resource
    selected_kind = selected.kind if selected else ""
    selected_source = selected.source if selected else ""
    selected_url = selected.resolved_url or selected.url if selected else ""
    latest_attempt = task.download_attempts[-1] if task.download_attempts else None
    chaoxing_profile = chaoxing_evidence_profile(task)
    is_chaoxing = bool(chaoxing_profile.get("detected"))
    boundary_notes: list[str] = []
    primary_code = task.error_code or (latest_attempt.code if latest_attempt else "")
    media_ready_for_rerun = task_media_ready_for_rerun(task)
    mse_boundary_summary = _mse_append_boundary_summary(selected)

    if task.mode == "download_only" and task_media_file_exists(task):
        primary_code = "download_ready"
        diagnosis = f"{task_media_display_name(task)} 已按只下载模式保存到本地；下一步可复用该视频生成字幕、画面网格和图文笔记。"
        confidence = "high"
        severity = "ok"
        next_action = "continue_from_media"
    elif media_ready_for_rerun:
        primary_code = "media_ready_for_rerun"
        diagnosis = f"视频已保存到本地，但完整笔记尚未生成；优先复用 {task_media_display_name(task)} 继续转写、切片和图文总结。"
        confidence = "high"
        severity = "recoverable" if task.status == "failed" else "ok"
        next_action = "continue_from_media"
    elif task.status == "failed" and task.note_path and task.summary_diagnostics.get("used_page_text_fallback"):
        primary_code = "fallback_note_ready"
        diagnosis = "视频直取失败，但已用页面文本和浏览器字幕生成兜底学习笔记；可以先导出 Markdown 复习，再按诊断重新尝试直取或改用本地视频。"
        confidence = "high"
        severity = "partial"
        next_action = "export_markdown"
    elif "drm_or_encrypted" in codes or task.drm_detected:
        primary_code = "drm_or_encrypted"
        diagnosis = (
            f"{mse_boundary_summary} 需要继续播放并重新检测真实 manifest/mp4 请求，"
            "否则改用本地视频入口。"
        ) if mse_boundary_summary else "页面没有暴露可还原的直接媒体资源，或触发了 DRM/EME 边界。"
        confidence = "high" if task.drm_detected else "medium"
        severity = "hard_boundary"
        next_action = "local_upload"
    elif "auth_required" in codes:
        primary_code = "auth_required"
        diagnosis = "登录态或 Cookie 已失效，后端无法复用浏览器当前权限下载。"
        confidence = "high"
        severity = "recoverable"
        next_action = "refresh_login_and_retry"
    elif "download_forbidden" in codes:
        primary_code = "download_forbidden"
        diagnosis = "媒体地址被防盗链、时效签名、Referer/Origin 或服务端策略拒绝。"
        confidence = "medium"
        severity = "recoverable"
        next_action = "refresh_playback_and_retry"
    elif "unsupported_manifest" in codes:
        primary_code = "unsupported_manifest"
        diagnosis = "已看到媒体线索，但 manifest 或分片不足以在本地合并。"
        confidence = "medium"
        severity = "recoverable"
        next_action = "play_longer_and_redetect"
    elif selected_kind == "blob":
        primary_code = "no_media_found"
        diagnosis = (
            f"{mse_boundary_summary} 需要继续播放并重新检测真实 manifest/mp4 请求。"
            if mse_boundary_summary
            else "当前只有 blob 播放线索，尚未发现可直接下载的 manifest 或媒体文件。"
        )
        confidence = "high" if mse_boundary_summary else "medium"
        severity = "recoverable"
        next_action = "play_and_redetect"
    elif "no_media_found" in codes or (task.status == "failed" and not task.download_attempts):
        primary_code = "no_media_found"
        diagnosis = "当前页还没有暴露 mp4、m3u8、mpd 或 yt-dlp 可解析的下载入口。"
        confidence = "medium"
        severity = "recoverable"
        next_action = "play_and_redetect"
    elif task.status == "failed":
        primary_code = primary_code or "processing_failed"
        diagnosis = task.error_detail or "任务失败，需要查看下载尝试和阶段审计定位。"
        confidence = "low"
        severity = "recoverable"
        next_action = "inspect_diagnostics"
    else:
        primary_code = primary_code or ""
        diagnosis = "任务仍可继续按阶段审计检查媒体、转写、切片和总结产物。"
        confidence = "medium"
        severity = "ok"
        next_action = "inspect_audit"

    if is_chaoxing:
        boundary_notes.append("学习通/超星第一版只复用当前页面暴露的真实媒体 URL、Referer 和 Cookie，不刷课、不伪造学习进度、不自动答题。")
    if "drm_or_encrypted" in codes or task.drm_detected:
        boundary_notes.append("不会录制、破解或绕过 DRM/EME；blob 只有在扩展捕获到真实 manifest/媒体请求时才可直取。")
    if mse_boundary_summary:
        boundary_notes.append(f"{mse_boundary_summary} 这只能作为播放证据，不能替代直接媒体下载。")
    if selected and selected.request_headers:
        boundary_notes.append(f"已捕获可复用请求头名：{_safe_header_names(selected.request_headers)}；不会保存 Cookie 或 Authorization 值。")
    if selected and _has_range_header(selected.request_headers):
        boundary_notes.append("Range 请求只作为播放证据，正式下载会去掉 Range，避免只保存片段。")
    if not boundary_notes:
        boundary_notes.append("当前页直取失败时，本地视频上传会复用同一套转写、切片和图文总结管线。")

    actions = _diagnostic_recovery_actions(task, next_action)

    return {
        "code": primary_code,
        "diagnosis": diagnosis,
        "severity": severity,
        "confidence": confidence,
        "next_action": next_action,
        "primary_action": actions[0],
        "actions": actions,
        "is_chaoxing": is_chaoxing,
        "chaoxing_profile": chaoxing_profile,
        "selected_kind": selected_kind,
        "selected_source": selected_source,
        "selected_url": selected_url,
        "attempt_count": len(task.download_attempts),
        "latest_attempt": {
            "strategy": latest_attempt.strategy,
            "code": latest_attempt.code,
            "status": latest_attempt.status,
            "status_code": latest_attempt.status_code,
            "message": latest_attempt.message,
        } if latest_attempt else None,
        "steps": diagnostic_recovery_steps(task),
        "boundary_notes": boundary_notes,
    }


def _audit_gate_state(task: TaskRecord, passed: bool, *, skipped: bool = False) -> str:
    if skipped:
        return "skip"
    if passed:
        return "pass"
    if task.status == "failed":
        return "fail"
    if task.status == "success":
        return "warn"
    return "wait"


def task_audit_gates(task: TaskRecord) -> list[dict[str, str]]:
    selected = task.selected_resource
    attempts = task.download_attempts or []
    diagnostics = task.summary_diagnostics or {}
    is_page_text = task.source_type == "page_text" or bool(diagnostics.get("used_page_text_fallback"))
    is_local = task.source_type == "local"
    is_download_only = task.mode == "download_only"
    has_route = bool(selected and (selected.url or selected.kind)) or is_local or is_page_text
    has_media = task_media_file_exists(task)
    has_transcript = bool(task.transcript_path)
    has_visuals = bool(task.visual_windows or task.frame_grids or diagnostics.get("frame_grid_count"))
    has_note = bool(task.note_path)
    visual_disabled = task.options.visual_understanding is False or is_page_text
    selected_kind = selected.kind if selected else ""
    selected_source = selected.source if selected else ""
    selected_match = selected.playback_match if selected else ""
    transcript_value = (
        "browser subtitles saved"
        if is_download_only and has_transcript
        else "download-only route"
        if is_download_only
        else "transcript ready"
        if has_transcript
        else ("browser/page text fallback" if is_page_text and has_note else task.phase or "waiting")
    )
    transcript_detail = (
        "timestamped browser subtitles are available; rerun from media can reuse them"
        if is_download_only and has_transcript
        else "media saved; rerun from media to transcribe"
        if is_download_only
        else "timestamped transcript is available"
        if has_transcript
        else (task.summary_warning or "subtitle first, ASR fallback")
    )
    visual_count = len(task.visual_windows) or len(task.frame_grids) or diagnostics.get("frame_grid_count")
    visual_value = (
        "download-only route"
        if is_download_only
        else ("disabled" if visual_disabled else (f"{visual_count} windows" if has_visuals else task.phase or "waiting"))
    )
    visual_detail = (
        "media saved; rerun from media to slice frames"
        if is_download_only
        else (
            "visual route disabled for this task"
            if visual_disabled
            else (
                f"{diagnostics.get('vision_image_count', 0)}/{diagnostics.get('vision_grid_count', visual_count or 0)} sent to vision"
                if has_visuals
                else "waiting for ffmpeg frame grids"
            )
        )
    )
    summary_value = (
        "download-only route"
        if is_download_only
        else (task.summary_source or ("note ready" if has_note else task.phase or "waiting"))
    )
    summary_detail = (
        "media saved; generate full note from media when needed"
        if is_download_only
        else (task.summary_warning or f"{task.options.note_style} / {task.options.note_template} / {task.options.summary_depth}")
    )

    return [
        {
            "key": "source",
            "label": "Source gate",
            "state": _audit_gate_state(task, has_route or bool(attempts) or has_media or has_note),
            "value": selected_source or selected_kind or task.source_type or "-",
            "detail": selected_match or (f"{len(attempts)} download attempts" if attempts else "waiting for browser, URL, or local source"),
        },
        {
            "key": "media",
            "label": "Media gate",
            "state": _audit_gate_state(task, has_media, skipped=is_page_text),
            "value": "page text route" if is_page_text else ("media.mp4" if has_media else task.error_code or "waiting"),
            "detail": "downloaded media is reusable" if has_media else (f"{len(attempts)} download attempts" if attempts else "waiting for direct download or resolver"),
        },
        {
            "key": "transcript",
            "label": "Transcript gate",
            "state": _audit_gate_state(
                task,
                has_transcript or (is_page_text and has_note),
                skipped=is_download_only and not has_transcript,
            ),
            "value": transcript_value,
            "detail": transcript_detail,
        },
        {
            "key": "visual",
            "label": "Visual slicing gate",
            "state": _audit_gate_state(task, has_visuals, skipped=visual_disabled or is_download_only),
            "value": visual_value,
            "detail": visual_detail,
        },
        {
            "key": "summary",
            "label": "Summary gate",
            "state": _audit_gate_state(task, has_note, skipped=is_download_only),
            "value": summary_value,
            "detail": summary_detail,
        },
    ]


def task_audit_summary(task: TaskRecord) -> dict:
    gates = task_audit_gates(task)
    released = [gate for gate in gates if gate["state"] in {"pass", "skip"}]
    blocked = [gate for gate in gates if gate["state"] in {"fail", "warn"}]
    return {
        "gates": gates,
        "released_count": len(released),
        "gate_count": len(gates),
        "blocked_gate": blocked[0]["key"] if blocked else "",
        "ok": len(released) == len(gates),
    }


def task_reuse_evidence(task: TaskRecord) -> dict:
    browser_subtitle_count = len(task.browser_subtitles or [])
    browser_subtitle_span = 0.0
    if task.browser_subtitles:
        starts = [cue.start for cue in task.browser_subtitles]
        ends = [cue.end for cue in task.browser_subtitles]
        browser_subtitle_span = max(0.0, max(ends) - min(starts))

    subtitle_available = bool(task.subtitle_path and Path(task.subtitle_path).is_file())
    transcript_ready = bool(task.transcript_path and Path(task.transcript_path).is_file())
    note_ready = bool(task.note_path and Path(task.note_path).is_file())
    has_visual_slices = bool(task.frame_grids or task.visual_windows)
    media_validation, media_signature = task_media_validation(task)
    media_available = media_validation == "verified"
    is_download_only = task.mode == "download_only"
    rerun_ready = task_media_ready_for_rerun(task)
    if media_validation == "invalid":
        suggested_next_step = "download_media"
    elif rerun_ready:
        suggested_next_step = "rerun_from_media"
    elif note_ready and has_visual_slices:
        suggested_next_step = "review_visual_windows"
    elif note_ready:
        suggested_next_step = "review_note"
    elif has_visual_slices:
        suggested_next_step = "review_visual_windows"
    elif media_available:
        suggested_next_step = "inspect_media"
    else:
        suggested_next_step = "download_media"

    return {
        "media_available": media_available,
        "media_validation": media_validation,
        "media_signature": media_signature,
        "media_path_recorded": task.media_path,
        "source_task_id": task.source_task_id,
        "source_media_path": task.source_media_path,
        "subtitle_available": subtitle_available,
        "subtitle_path_recorded": task.subtitle_path,
        "transcript_ready": transcript_ready,
        "transcript_path_recorded": task.transcript_path,
        "transcript_source": _task_transcript_source(task) if transcript_ready else "",
        "transcript_source_text": _task_transcript_source_text(task) if transcript_ready else "-",
        "note_ready": note_ready,
        "browser_subtitle_count": browser_subtitle_count,
        "browser_subtitle_span_seconds": round(browser_subtitle_span, 3),
        "download_attempt_count": len(task.download_attempts),
        "selected_resource_url": task.selected_resource.url if task.selected_resource else "",
        "selected_resource_kind": task.selected_resource.kind if task.selected_resource else "",
        "mse_append_evidence": mse_append_evidence(task.selected_resource),
        "frame_grid_count": len(task.frame_grids),
        "visual_window_count": len(task.visual_windows),
        "has_visual_slices": has_visual_slices,
        "download_only": is_download_only,
        "rerun_from_media_ready": rerun_ready,
        "suggested_next_step": suggested_next_step,
    }


def task_source_evidence_quality(task: TaskRecord) -> tuple[dict, dict]:
    diagnostics = task.summary_diagnostics or {}
    media_validation, media_signature = task_media_validation(task)
    has_media = media_validation == "verified"
    media_path_exists = media_validation != "missing"
    invalid_media = media_validation == "invalid"
    invalid_media_source = invalid_media and task_media_source_is_definitively_non_video(task)
    transcript_source = _task_transcript_source(task)
    has_timed_transcript = bool(
        task.transcript_path
        and transcript_source
        and transcript_source not in {"unknown", "page-text", "no-audio"}
        and not transcript_source.endswith(("-error", "-missing-key", "-missing-sdk"))
    )
    has_visual_evidence = bool(
        task.frame_grids
        or task.visual_windows
        or diagnostics.get("extracted_frame_count")
        or diagnostics.get("frame_grid_count")
    )
    submitted_browser_cue_count = len(task.browser_subtitles or [])
    browser_cue_count = int(diagnostics.get("browser_subtitle_count") or 0)
    if transcript_source == "browser-subtitle" and task.transcript_path:
        try:
            transcript_payload = read_transcript(task.id)
            browser_cue_count = len(transcript_payload.get("segments") or [])
        except (OSError, ValueError, TypeError):
            browser_cue_count = 0
    page_text_only = task.source_type == "page_text" or bool(diagnostics.get("used_page_text_fallback"))

    if invalid_media:
        source_kind = "invalid_media"
    elif task.source_type == "local":
        source_kind = "local_media"
    elif has_media:
        source_kind = "current_page_media"
    elif browser_cue_count or submitted_browser_cue_count:
        source_kind = "browser_subtitle_cues"
    elif page_text_only:
        source_kind = "page_text"
    else:
        source_kind = "unresolved_current_page"

    if invalid_media:
        source_level = "none"
        source_reason = "The saved file came from a definitively non-video source." if invalid_media_source else "A saved media path exists, but the file is not a recognized video container."
    elif has_media:
        source_level = "high"
        source_reason = "A reusable media file is available."
    elif browser_cue_count:
        source_level = "low"
        source_reason = "Filtered browser subtitle cues are available, but no media file was verified."
    elif submitted_browser_cue_count:
        source_level = "low"
        source_reason = "Browser cues were submitted but have not been validated or verified against media."
    elif page_text_only:
        source_level = "low"
        source_reason = "Only page DOM text is available; it may contain player controls or other UI text."
    else:
        source_level = "none"
        source_reason = "No reusable media or content evidence is available."

    if has_media and has_timed_transcript and has_visual_evidence:
        evidence_level = "high"
    elif has_media and (has_timed_transcript or has_visual_evidence):
        evidence_level = "medium"
    elif has_media or browser_cue_count:
        evidence_level = "low"
    else:
        evidence_level = "none"

    can_claim_video_content = bool(has_media and (has_timed_transcript or has_visual_evidence))
    if invalid_media:
        evidence_reason = "The download resolved to an image or page asset; existing note claims must not be treated as video evidence." if invalid_media_source else "The saved file is not a recognized video container; existing note claims must not be treated as video evidence."
    elif can_claim_video_content:
        evidence_reason = "Video claims are backed by verified media and transcript or visual evidence."
    elif has_media:
        evidence_reason = "Media exists, but no usable transcript or visual evidence supports a video note yet."
    elif browser_cue_count:
        evidence_reason = "Browser subtitle cues are partial and are not independently verified against media."
    elif page_text_only:
        evidence_reason = "Page text is context only and must not be presented as video subtitles or a video note."
    else:
        evidence_reason = "Trusted video evidence is missing."

    source_quality = {
        "kind": source_kind,
        "level": source_level,
        "reason": source_reason,
    }
    evidence_quality = {
        "level": evidence_level,
        "video_evidence": "invalid" if invalid_media else "verified" if can_claim_video_content else "partial" if has_media or browser_cue_count else "missing",
        "has_media": has_media,
        "media_path_exists": media_path_exists,
        "media_validation": media_validation,
        "media_signature": media_signature,
        "has_timed_transcript": has_timed_transcript,
        "transcript_source": transcript_source,
        "has_visual_evidence": has_visual_evidence,
        "browser_subtitle_cue_count": browser_cue_count,
        "submitted_browser_subtitle_cue_count": submitted_browser_cue_count,
        "can_claim_video_content": can_claim_video_content,
        "degraded": not can_claim_video_content,
        "reason": evidence_reason,
    }
    return source_quality, evidence_quality


def task_workflow_stage(task: TaskRecord) -> str:
    phase = task.failed_phase if task.phase == "failed" and task.failed_phase else task.phase
    if phase in {"queued", "detecting", "downloading"}:
        return "acquire_media"
    if phase == "processing_video":
        return "check_content"
    if phase == "transcribing":
        return "generate_transcript"
    if phase == "extracting_frames":
        return "understand_visuals"
    return "compose_note"


def task_eta_seconds(task: TaskRecord) -> int:
    if task.status in {"success", "failed", "cancelled"}:
        return 0
    duration = float(task.media_integrity.duration or 0)
    estimated_total = max(30, round(duration * 0.65 + 45))
    return max(0, round(estimated_total * (100 - max(0, min(100, task.progress))) / 100))


def task_payload(task: TaskRecord) -> dict:
    payload = task.model_dump(mode="json")
    payload["media_integrity"] = task.media_integrity.model_dump(mode="json")
    payload["handoff_integrity"] = task.handoff_integrity.model_dump(mode="json")
    payload["evidence_coverage"] = task.evidence_coverage.model_dump(mode="json")
    payload["source_identity"] = task.source_identity.model_dump(mode="json")
    payload["workflow_stage"] = task_workflow_stage(task)
    payload["eta_seconds"] = task_eta_seconds(task)
    source_quality, evidence_quality = task_source_evidence_quality(task)
    payload["source_quality"] = source_quality
    payload["evidence_quality"] = evidence_quality
    payload["direct_extraction"] = direct_extraction_evidence(task)
    payload["audit"] = task_audit_summary(task)
    payload["recovery"] = diagnostic_recovery_profile(task)
    payload["reuse"] = task_reuse_evidence(task)
    payload["next_actions"] = task_next_actions(task)
    qa_history = read_task_qa_history(task.id)
    payload["qa"] = {
        "history_count": len(qa_history),
        "last_question": qa_history[-1].get("question", "") if qa_history else "",
        "last_source": qa_history[-1].get("source", "") if qa_history else "",
        "recent": qa_history_preview(qa_history),
        "suggestions": task_qa_suggestions(task),
    }
    return payload


def resource_with_preflight_result(candidate: ResourceCandidate, result: MediaPreflightResult) -> ResourceCandidate:
    resource = candidate.model_copy(deep=True)
    if result.resolved_url:
        resource.resolved_url = result.resolved_url
    if result.kind and result.kind != "unknown":
        resource.kind = result.kind
    if result.content_type:
        resource.mime = result.content_type
    if result.content_length:
        resource.content_length = result.content_length
    if result.status_code:
        resource.status_code = result.status_code
    return resource


def _should_scan_page_for_preflight(request: PagePreflightRequest, ranked: list[ResourceCandidate], *, after_failed_probe: bool = False) -> bool:
    if request.probe_limit <= 0 or not request.page_url:
        return False
    if len(ranked) >= request.probe_limit and not after_failed_probe:
        return False
    if not request.resources:
        return True
    if request.drm_detected and all(effective_resource_kind(item) == "blob" for item in request.resources):
        return False
    for item in request.resources:
        kind = effective_resource_kind(item)
        if kind == "blob":
            continue
        if kind == "unknown":
            return True
        if item.frame_url or item.page_url or item.request_headers.get("Referer") or item.initiator:
            return True
    return False


def _preflight_page_scan_resources(request: PagePreflightRequest, ranked: list[ResourceCandidate], *, after_failed_probe: bool = False) -> tuple[list[ResourceCandidate], list[dict]]:
    if not _should_scan_page_for_preflight(request, ranked, after_failed_probe=after_failed_probe):
        return [], []
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    discovered: list[ResourceCandidate] = []
    seen = {item.url for item in request.resources if item.url}
    with tempfile.TemporaryDirectory(prefix="page-preflight-", dir=str(TEMP_DIR)) as workspace:
        downloader = MediaDownloader(Path(workspace))
        for fallback_url, context_candidate in fallback_page_contexts(request.page_url, request.resources):
            for item in downloader._discover_page_resources(fallback_url, request.cookies, context_candidate):
                if not item.url or item.url in seen:
                    continue
                seen.add(item.url)
                discovered.append(item)
    attempts = [attempt.model_dump(mode="json") for attempt in downloader.attempts]
    return discovered, attempts


def page_preflight_report(request: PagePreflightRequest) -> dict:
    request.resources = enrich_resource_candidates_with_active_video(request.active_video, request.resources)
    initial_ranked = rank_media_candidates(request.resources)
    discovered_resources, discovery_attempts = _preflight_page_scan_resources(request, initial_ranked)
    ranked = rank_media_candidates([*request.resources, *discovered_resources]) if discovered_resources else initial_ranked
    preflight_cache: dict[str, MediaPreflightResult] = {}

    def evaluate_candidates(
        candidate_list: list[ResourceCandidate],
        *,
        extra_probe_urls: set[str] | None = None,
    ) -> tuple[int, int, str, list[dict]]:
        probed = 0
        downloadable_count = 0
        selected_url = ""
        candidates: list[dict] = []
        extra_probe_urls = extra_probe_urls or set()

        for index, candidate in enumerate(candidate_list, start=1):
            should_probe = probed < request.probe_limit or candidate.url in extra_probe_urls
            if should_probe:
                result = preflight_cache.get(candidate.url)
                if result is None:
                    result = preflight_media_resource(candidate, request.cookies, request.page_url)
                    preflight_cache[candidate.url] = result
                probed += 1
                resource = resource_with_preflight_result(candidate, result)
                if result.downloadable:
                    downloadable_count += 1
                    if not selected_url:
                        selected_url = resource.url
                        resource.user_selected = True
                        resource.score = 100
            else:
                result = MediaPreflightResult(
                    ok=True,
                    downloadable=False,
                    strategy="not-probed",
                    kind=effective_resource_kind(candidate),
                    url=candidate.url,
                    resolved_url=candidate.resolved_url or candidate.url,
                    code="not_probed",
                    message="候选排序靠后，本次整页预检未发起网络探测；启动任务时仍可作为后续下载候选。",
                )
                resource = resource_with_preflight_result(candidate, result)

            candidates.append({
                "rank": index,
                "resource": resource.model_dump(mode="json"),
                "preflight": result.model_dump(mode="json"),
            })
        return probed, downloadable_count, selected_url, candidates

    probed, downloadable_count, selected_url, candidates = evaluate_candidates(ranked)
    if not selected_url:
        fallback_resources, fallback_attempts = _preflight_page_scan_resources(request, ranked, after_failed_probe=True)
        if fallback_resources:
            existing_urls = {item.url for item in discovered_resources}
            new_resources = [item for item in fallback_resources if item.url not in existing_urls]
            discovered_resources.extend(new_resources)
            discovery_attempts.extend(fallback_attempts)
            ranked = rank_media_candidates([*request.resources, *discovered_resources])
            probed, downloadable_count, selected_url, candidates = evaluate_candidates(
                ranked,
                extra_probe_urls={item.url for item in new_resources if item.url},
            )

    direct_candidate_count = sum(1 for item in ranked if effective_resource_kind(item) in {"video", "hls", "dash"})
    has_drm_boundary = request.drm_detected

    if selected_url:
        code = ""
        message = f"整页预检通过：{downloadable_count} 个候选可访问，默认选择排序最靠前的可下载资源。"
    elif has_drm_boundary and not direct_candidate_count:
        code = "drm_or_encrypted"
        message = "页面只暴露 blob/DRM 播放线索，没有可交给后端下载的 mp4、m3u8 或 mpd。"
    elif ranked:
        preflight_codes = [str(item["preflight"].get("code") or "") for item in candidates]
        code = (
            "no_media_found"
            if preflight_codes and all(item in {"no_media_found", "not_probed"} for item in preflight_codes)
            else "download_forbidden"
        )
        message = "整页预检没有发现可直接下载的候选；可继续播放后重新检测，或改用本地视频上传。"
    elif has_drm_boundary:
        code = "drm_or_encrypted"
        message = "页面只暴露 blob/DRM 播放线索，没有可交给后端下载的 mp4、m3u8 或 mpd。"
    else:
        code = "no_media_found"
        message = "当前页没有发现可预检的 mp4、m3u8 或 mpd 候选。"

    return {
        "ok": True,
        "ready": bool(selected_url),
        "code": code,
        "message": message,
        "selected_url": selected_url,
        "candidate_count": len(ranked),
        "probed_count": probed,
        "downloadable_count": downloadable_count,
        "page_scan": {
            "attempted": bool(discovery_attempts),
            "discovered_count": len(discovered_resources),
            "attempts": discovery_attempts,
        },
        "candidates": candidates,
    }


def render_diagnostics_markdown(task: TaskRecord) -> str:
    selected = task.selected_resource
    resource_inventory = read_resource_inventory(task)
    page_preflight = read_page_preflight_report(task)
    chaoxing_profile = chaoxing_evidence_profile(task)
    lines = [
        "# LearnNote 任务诊断报告",
        "",
        f"- 任务：{task.title}",
        f"- ID：{task.id}",
        f"- 状态：{task.status} / {task.phase} / {task.progress}%",
        f"- 来源：{task.source_type}",
        f"- 模式：{task.mode}",
        f"- 页面：{task.page_url or '-'}",
        f"- 消息：{task.error_detail or task.message or '-'}",
        f"- 错误码：{task.error_code or '-'}",
        "",
        "## 已选资源",
    ]
    if selected:
        lines.extend([
            f"- 类型：{selected.kind or '-'}",
            f"- 来源：{selected.source or '-'}",
            f"- URL：{selected.url or '-'}",
            f"- 最终 URL：{selected.resolved_url or '-'}",
            f"- 播放匹配：{selected.playback_match or '-'}",
            f"- Blob：{selected.blob_url or '-'}",
            f"- Frame：{selected.frame_url or selected.frame_id or '-'}",
            f"- HTTP：{selected.status_code or '-'}",
            f"- MIME：{selected.mime or '-'}",
            f"- 大小：{_format_bytes(selected.content_length)}",
            f"- Content-Disposition：{selected.headers.get('content-disposition') or '-'}",
            f"- 可复用请求头名：{_safe_header_names(selected.request_headers)}",
        ])
        append_evidence = mse_append_evidence(selected)
        if append_evidence:
            lines.extend([
                "",
                "### MSE Append Evidence",
                f"- Append count: {append_evidence.get('append_count', '-')}",
                f"- Last append bytes: {_format_bytes(append_evidence.get('append_bytes'))}",
                f"- Total append bytes: {_format_bytes(append_evidence.get('append_total_bytes'))}",
                f"- Magic: {append_evidence.get('append_magic', '-')}",
                f"- Append MIME: {append_evidence.get('append_mime', '-')}",
                f"- Detected kind: {append_evidence.get('append_detected_kind', '-')}",
                f"- Blob URL: {append_evidence.get('blob_url', '-')}",
            ])
    else:
        lines.append("- 未选择直接媒体资源，可能使用页面解析或 yt-dlp fallback。")

    if resource_inventory:
        candidates = resource_inventory.get("candidates") or []
        if not isinstance(candidates, list):
            candidates = []
        lines.extend([
            "",
            "## Resource Inventory",
            f"- Candidate count: {resource_inventory.get('candidate_count', len(candidates))}",
            f"- Downloadable candidates: {resource_inventory.get('downloadable_candidate_count', 0)}",
            f"- Replayable candidates: {resource_inventory.get('replayable_candidate_count', 0)}",
            f"- Kind counts: {resource_inventory.get('kind_counts', {})}",
            f"- Source counts: {resource_inventory.get('source_counts', {})}",
        ])
        for index, candidate in enumerate(candidates[:5], start=1):
            headers = candidate.get("request_headers") or {}
            header_names = sorted(headers.keys()) if isinstance(headers, dict) else []
            lines.extend([
                f"### Candidate {index}",
                f"- URL: {candidate.get('url') or '-'}",
                f"- Kind/source: {candidate.get('kind') or '-'} / {candidate.get('source') or '-'}",
                f"- Score: {candidate.get('score', '-')}",
                f"- Playback match: {candidate.get('playback_match') or '-'}",
                f"- MIME: {candidate.get('mime') or '-'}",
                f"- Safe request header names: {', '.join(_safe_request_header_names(header_names)) if header_names else '-'}",
            ])
        if len(candidates) > 5:
            lines.append(f"- Omitted candidates in Markdown: {len(candidates) - 5}; see resource_inventory.json.")

    if page_preflight:
        page_scan = page_preflight.get("page_scan") or {}
        candidates = page_preflight.get("candidates") or []
        if not isinstance(candidates, list):
            candidates = []
        lines.extend([
            "",
            "## Page Preflight Report",
            f"- Ready: {'yes' if page_preflight.get('ready') else 'no'}",
            f"- Code: {page_preflight.get('code') or '-'}",
            f"- Selected URL: {page_preflight.get('selected_url') or '-'}",
            f"- Candidates/probed/downloadable: {page_preflight.get('candidate_count', 0)} / {page_preflight.get('probed_count', 0)} / {page_preflight.get('downloadable_count', 0)}",
            f"- Page scan attempted: {'yes' if page_scan.get('attempted') else 'no'}",
            f"- Page scan discoveries: {page_scan.get('discovered_count', 0)}",
        ])
        for item in candidates[:5]:
            resource = item.get("resource") or {}
            preflight = item.get("preflight") or {}
            lines.append(
                f"- Rank {item.get('rank', '-')}: {resource.get('kind') or '-'} / {resource.get('source') or '-'} / "
                f"{preflight.get('code') or preflight.get('strategy') or '-'} / {resource.get('url') or '-'}"
            )
        if len(candidates) > 5:
            lines.append(f"- Omitted preflight candidates in Markdown: {len(candidates) - 5}; see page_preflight_report.json.")

    if chaoxing_profile.get("detected"):
        lines.extend([
            "",
            "## Chaoxing Profile",
            f"- Detected: yes",
            f"- Likely issue: {chaoxing_profile.get('likely_issue') or '-'}",
            f"- ananas/playurl/objectid/dtoken: {'yes' if chaoxing_profile.get('has_ananas_candidate') else 'no'} / {'yes' if chaoxing_profile.get('has_playurl') else 'no'} / {'yes' if chaoxing_profile.get('has_objectid') else 'no'} / {'yes' if chaoxing_profile.get('has_dtoken') else 'no'}",
            f"- Replay body: {'yes' if chaoxing_profile.get('has_replay_body') else 'no'} ({chaoxing_profile.get('replay_body_count', 0)})",
            f"- Referer/Origin/X-Requested-With: {'yes' if chaoxing_profile.get('has_referer') else 'no'} / {'yes' if chaoxing_profile.get('has_origin') else 'no'} / {'yes' if chaoxing_profile.get('has_x_requested_with') else 'no'}",
            f"- iframe/player context: {'yes' if chaoxing_profile.get('has_iframe_context') else 'no'} ({chaoxing_profile.get('iframe_context_count', 0)})",
            f"- Cookie domains/count: {chaoxing_profile.get('cookie_domain_count', 0)} / {chaoxing_profile.get('cookie_count', 0)}",
            f"- Partitioned cookies: {chaoxing_profile.get('partitioned_cookie_count', 0)} / {chaoxing_profile.get('partition_key_count', 0)} partition keys",
            f"- Safe request header names: {', '.join(chaoxing_profile.get('safe_request_header_names') or []) or '-'}",
            f"- Candidate kinds: {', '.join(chaoxing_profile.get('candidate_kinds') or []) or '-'}",
            "- Boundary: direct downloadable resources only; no recording, no progress forgery, no auto-answering.",
        ])

    lines.extend(["", "## Cookie 同步"])
    lines.extend(_format_cookie_summary(task.cookie_summary))

    lines.extend(["", "## 下载尝试"])
    if task.download_attempts:
        for index, attempt in enumerate(task.download_attempts, start=1):
            lines.extend([
                f"### {index}. {attempt.strategy} · {attempt.status}",
                f"- URL：{attempt.url or '-'}",
                f"- 最终 URL：{attempt.resolved_url or '-'}",
                f"- 类型：{attempt.kind or '-'}",
                f"- 来源：{attempt.source or '-'}",
                f"- 错误码：{attempt.code or '-'}",
                f"- HTTP：{attempt.status_code or '-'}",
                f"- MIME：{attempt.mime or '-'}",
                f"- 大小：{_format_bytes(attempt.bytes_downloaded or attempt.content_length)}",
                f"- 请求头名：{', '.join(_safe_request_header_names(attempt.request_header_names)) if attempt.request_header_names else '-'}",
                f"- 伴随音频：{attempt.companion_audio_url or '-'}"
                f"{f' ({attempt.companion_audio_mime})' if attempt.companion_audio_mime else ''}",
                f"- 输出：{attempt.output_path or '-'}",
                f"- 信息：{attempt.message or '-'}",
                "",
            ])
    else:
        lines.append("- 暂无下载尝试记录。")

    recovery = diagnostic_recovery_profile(task)
    latest_attempt = recovery.get("latest_attempt") or {}
    lines.extend([
        "",
        "## 恢复档案",
        f"- 归类：{recovery.get('code') or '-'}",
        f"- 判断：{recovery.get('diagnosis') or '-'}",
        f"- 严重度：{recovery.get('severity') or '-'}",
        f"- 置信度：{recovery.get('confidence') or '-'}",
        f"- 推荐动作：{recovery.get('next_action') or '-'}",
        f"- 学习通/超星：{'yes' if recovery.get('is_chaoxing') else 'no'}",
        f"- 已选候选：{recovery.get('selected_kind') or '-'} / {recovery.get('selected_source') or '-'}",
        f"- 尝试次数：{recovery.get('attempt_count') or 0}",
    ])
    if latest_attempt:
        lines.append(
            "- 最近尝试："
            f"{latest_attempt.get('strategy') or '-'} / "
            f"{latest_attempt.get('code') or '-'} / "
            f"{latest_attempt.get('status') or '-'} / "
            f"HTTP {latest_attempt.get('status_code') or '-'}"
        )
    lines.append("- 边界说明：")
    lines.extend(f"  - {note}" for note in recovery.get("boundary_notes", []))

    lines.extend(["", "## 下一步建议"])
    lines.extend(f"- {step}" for step in recovery.get("steps", []))

    direct = direct_extraction_evidence(task)
    selected_direct = direct.get("selected_candidate") or {}
    browser_context = direct.get("browser_context") or {}
    download_direct = direct.get("download") or {}
    processing_direct = direct.get("processing") or {}
    playback_direct = playback_evidence(task)
    active_playback = playback_direct.get("active_video") or {}
    selected_playback = playback_direct.get("selected_resource") or {}
    safe_headers = selected_direct.get("safe_request_header_names") or []
    lines.extend([
        "",
        "## Direct Extraction Evidence",
        f"- No tab recording: {'yes' if direct.get('no_tab_recording') else 'no'}",
        f"- No DRM bypass: {'yes' if direct.get('no_drm_bypass') else 'no'}",
        f"- Route: {direct.get('route') or '-'}",
        f"- Boundary: {direct.get('boundary') or '-'}",
        f"- Media landed: {'yes' if direct.get('media_landed') else 'no'}",
        f"- Candidate: {selected_direct.get('kind') or '-'} / {selected_direct.get('source') or '-'} / {selected_direct.get('playback_match') or '-'}"
        f" / user selected {'yes' if selected_direct.get('user_selected') else 'no'}",
        f"- Safe request headers: {', '.join(safe_headers) if safe_headers else '-'}",
        f"- Browser context: {browser_context.get('active_source_type') or '-'} / subtitles {browser_context.get('browser_subtitle_count') or 0}"
        f" / cookie domains {browser_context.get('cookie_domain_count') or 0} / cookies {browser_context.get('cookie_count') or 0}",
        f"- Active playback: {active_playback.get('source_type') or '-'} / {_format_timestamp(active_playback.get('current_time'))}"
        f" / {_format_timestamp(active_playback.get('duration'))} / paused {'yes' if active_playback.get('paused') else 'no'}"
        f" / frame {active_playback.get('frame_id') if active_playback.get('frame_id') is not None else '-'}"
        f" / {active_playback.get('width') or 0}x{active_playback.get('height') or 0}",
        f"- Selected playback match: {'yes' if playback_direct.get('matched_current_playback') else 'no'}"
        f" / {selected_playback.get('playback_match') or '-'}"
        f" / {_format_timestamp(selected_playback.get('current_time'))}"
        f" / {_format_timestamp(selected_playback.get('duration'))}",
        f"- Download attempts: {download_direct.get('successful_attempt_count') or 0} success / {download_direct.get('failed_attempt_count') or 0} failed / {', '.join(download_direct.get('strategy_order') or []) or '-'}",
        f"- Processing: transcript {'yes' if processing_direct.get('transcript_ready') else 'no'} / grids {processing_direct.get('frame_grid_count') or 0} / windows {processing_direct.get('visual_window_count') or 0} / note {'yes' if processing_direct.get('note_ready') else 'no'}",
    ])

    audit = task_audit_summary(task)
    lines.extend([
        "",
        "## Stage Audit Gates",
        f"- Released: {audit['released_count']}/{audit['gate_count']}",
        f"- Blocked gate: {audit['blocked_gate'] or '-'}",
    ])
    for gate in audit["gates"]:
        lines.append(f"- {gate['key']}: {gate['state']} / {gate['value']} / {gate['detail']}")

    reuse = task_reuse_evidence(task)
    lines.extend([
        "",
        "## Reuse Evidence",
        f"- Media available: {'yes' if reuse['media_available'] else 'no'}",
        f"- Source task: {reuse.get('source_task_id') or '-'}",
        f"- Source media: {reuse.get('source_media_path') or '-'}",
        f"- Saved subtitles: {'yes' if reuse['subtitle_available'] else 'no'} / {reuse.get('subtitle_path_recorded') or '-'}",
        f"- Reusable transcript: {'yes' if reuse['transcript_ready'] else 'no'} / {reuse.get('transcript_source') or '-'}",
        f"- Browser subtitles: {reuse['browser_subtitle_count']} cues / {reuse['browser_subtitle_span_seconds']}s",
        f"- Visual slices: {reuse['frame_grid_count']} frame grids / {reuse['visual_window_count']} windows",
        f"- Rerun from media ready: {'yes' if reuse['rerun_from_media_ready'] else 'no'}",
        f"- Suggested next step: {reuse['suggested_next_step']}",
    ])

    lines.extend([
        "",
        "## 处理产物",
        f"- 媒体：{task.media_path or '-'}",
        f"- 音频：{task.audio_path or '-'}",
        f"- 转写引擎：{_asr_option_text(task)}",
        f"- 转写来源：{_task_transcript_source_text(task)}",
        f"- 字幕：{task.subtitle_path or '-'}",
        f"- 转写：{task.transcript_path or '-'}",
        f"- 视觉索引：{task.visual_index_path or '-'}",
        f"- 笔记：{task.note_path or '-'}",
        f"- 画面网格：{len(task.frame_grids)}",
        f"- 视觉窗口：{len(task.visual_windows)}",
        "",
        "## 图文总结",
        f"- 来源：{task.summary_source or '-'}",
        f"- 提示：{task.summary_warning or '-'}",
    ])
    if task.summary_diagnostics:
        lines.extend([
            f"- 视觉窗口数：{task.summary_diagnostics.get('visual_window_count', '-')}",
            f"- LLM Provider：{task.summary_diagnostics.get('llm_provider', '-')}",
            f"- LLM Base：{task.summary_diagnostics.get('llm_base_host', '-')}",
            f"- LLM Model：{task.summary_diagnostics.get('llm_model', '-')}",
            f"- LLM Failure：{task.summary_diagnostics.get('llm_failure_stage', '-')}"
            f" / {task.summary_diagnostics.get('llm_failure_code', '-')}"
            f" / {task.summary_diagnostics.get('llm_failure_reason', '-')}",
            f"- LLM Events：{task.summary_diagnostics.get('llm_event_count', 0)}",
            f"- LLM Last Failure：{task.summary_diagnostics.get('llm_last_failure', {})}",
            f"- 送入视觉图片：{task.summary_diagnostics.get('vision_image_count', '-')}/{task.summary_diagnostics.get('vision_grid_count', '-')}",
            f"- 视觉调用状态：{task.summary_diagnostics.get('vision_call_status', '-')}",
            f"- 视觉失败批次：{task.summary_diagnostics.get('vision_failed_batch_count', 0)}",
            f"- 视觉图片输入被拒：{'yes' if task.summary_diagnostics.get('vision_model_rejected_image') else 'no'}",
            f"- 视觉批次计划：{task.summary_diagnostics.get('vision_expected_batch_count', '-')}"
            f" 批，每批最多 {task.summary_diagnostics.get('vision_batch_size', '-')} 张网格",
            f"- 省略网格：{task.summary_diagnostics.get('omitted_frame_grid_count', '-')}",
            f"- 已送入视觉窗口：{_format_id_list(task.summary_diagnostics.get('vision_image_window_ids'))}",
            f"- 缺少图片窗口：{_format_id_list(task.summary_diagnostics.get('missing_vision_image_window_ids'))}",
            f"- 超限省略窗口：{_format_id_list(task.summary_diagnostics.get('omitted_vision_window_ids'))}",
        ])
        if task.summary_diagnostics.get("used_page_text_fallback"):
            lines.extend([
                f"- 页面文本字符：{task.summary_diagnostics.get('page_text_char_count', '-')}",
                f"- 浏览器字幕条数：{task.summary_diagnostics.get('browser_subtitle_count', '-')}",
                f"- 合并文本字符：{task.summary_diagnostics.get('combined_text_char_count', '-')}",
                "- 页面文本兜底：是",
            ])

    lines.extend([
        "",
        "## 边界说明",
        "- 本报告不会包含 Cookie 或 Authorization 值。",
        "- 如果结果是 `drm_or_encrypted`、未映射 `blob:`、孤立分片，当前版本不会录制、破解或绕过 DRM。",
        "- `media.mp4` 通过单独的“导出本地视频”接口下载，资料包默认不内嵌大视频文件。",
        "",
    ])
    return "\n".join(lines)


def _write_file_if_exists(archive: ZipFile, path_value: str, archive_name: str) -> None:
    if not path_value:
        return
    path = Path(path_value)
    if path.is_file():
        archive.write(path, archive_name)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    path = WEB_DIR / "index.html"
    return HTMLResponse(path.read_text(encoding="utf-8"))


def data_paths_payload() -> dict:
    root = DATA_DIR.resolve()
    paths = {
        "data": root,
        "uploads": UPLOAD_DIR.resolve(),
        "tasks": TASK_DIR.resolve(),
        "static": STATIC_DIR.resolve(),
        "model_cache": MODEL_CACHE_DIR.resolve(),
        "temp": TEMP_DIR.resolve(),
    }
    under_data = {}
    for key, path in paths.items():
        try:
            under_data[key] = path == root or path.is_relative_to(root)
        except ValueError:
            under_data[key] = False
    drives = {key: path.drive for key, path in paths.items()}
    return {
        "root": str(root),
        "paths": {key: str(path) for key, path in paths.items()},
        "under_data_dir": under_data,
        "all_under_data_dir": all(under_data.values()),
        "drives": drives,
        "all_on_data_drive": all(drive == root.drive for drive in drives.values()),
        "data_drive": root.drive,
    }


MODEL_PROVIDER_PRESETS = [
    {
        "key": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "transcriber": "openai-compatible",
        "whisper_model": "whisper-1",
        "tier": "mainstream",
        "recommended": True,
        "capabilities": ["text", "vision", "asr"],
    },
    {
        "key": "groq",
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "transcriber": "groq",
        "whisper_model": "whisper-large-v3",
        "tier": "mainstream",
        "recommended": True,
        "capabilities": ["text", "vision", "asr"],
    },
    {
        "key": "gemini",
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-3.5-flash",
        "transcriber": "faster-whisper",
        "whisper_model": "small",
        "tier": "mainstream",
        "recommended": True,
        "capabilities": ["text", "vision"],
    },
    {
        "key": "dashscope",
        "label": "通义千问 Qwen",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-max",
        "transcriber": "faster-whisper",
        "whisper_model": "small",
        "tier": "mainstream",
        "recommended": True,
        "capabilities": ["text", "vision"],
    },
    {
        "key": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "transcriber": "faster-whisper",
        "whisper_model": "small",
        "tier": "mainstream",
        "recommended": True,
        "capabilities": ["text"],
    },
    {
        "key": "kimi",
        "label": "Kimi 月之暗面",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "kimi-k2.6",
        "transcriber": "faster-whisper",
        "whisper_model": "small",
        "tier": "mainstream",
        "recommended": True,
        "capabilities": ["text", "vision"],
    },
    {
        "key": "zhipu",
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5v-turbo",
        "transcriber": "faster-whisper",
        "whisper_model": "small",
        "tier": "mainstream",
        "recommended": True,
        "capabilities": ["text", "vision"],
    },
    {
        "key": "doubao",
        "label": "豆包 火山方舟",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-seed-2-0-lite-260215",
        "transcriber": "faster-whisper",
        "whisper_model": "small",
        "tier": "mainstream",
        "recommended": True,
        "capabilities": ["text"],
    },
    {
        "key": "minimax",
        "label": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M2.7",
        "transcriber": "faster-whisper",
        "whisper_model": "small",
        "tier": "mainstream",
        "recommended": True,
        "capabilities": ["text"],
    },
    {
        "key": "qianfan",
        "label": "百度千帆 ERNIE",
        "base_url": "https://qianfan.baidubce.com/v2",
        "model": "ernie-4.5-8k-preview",
        "transcriber": "faster-whisper",
        "whisper_model": "small",
        "tier": "mainstream",
        "recommended": True,
        "capabilities": ["text", "vision"],
    },
]


ASSISTANT_CAPABILITIES = {
    "routes": ["current_page_direct", "local_upload", "download_only", "rerun_from_media", "page_text", "task_qa"],
    "direct_media": {
        "file_extensions": ["mp4", "m4v", "mov", "mkv", "webm", "flv", "avi"],
        "manifests": ["m3u8", "mpd"],
        "detectors": ["dom_video", "performance_resource", "web_request", "player_runtime", "yt_dlp"],
        "cookie_policy": "on_click_domains_only",
    },
    "study_pipeline": {
        "default_frame_interval": 20,
        "default_grid": "3x3",
        "outputs": ["media.mp4", "transcript.json", "visual_index.json", "note.md", "qa.md", "bundle.zip"],
    },
    "non_goals": ["tab_recording", "drm_bypass", "progress_spoofing", "auto_answering"],
}


def health_payload() -> dict:
    ffmpeg = ffmpeg_bin()
    ffprobe = ffprobe_bin()
    duration_probe = "ffprobe" if ffprobe else "ffmpeg" if ffmpeg else ""
    local_asr_available = find_spec("faster_whisper") is not None
    ytdlp_package_available = find_spec("yt_dlp") is not None
    ytdlp_cli = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe") or ""
    return {
        "ok": True,
        "app_version": APP_VERSION,
        "backend_version": APP_VERSION,
        "api_version": API_VERSION,
        "protocol_version": UX_PROTOCOL_VERSION,
        "task_schema_version": TASK_SCHEMA_VERSION,
        "extension_version": _extension_version,
        "extension_protocol_version": _extension_protocol_version,
        "extension_compatible": not _extension_protocol_version or _extension_protocol_version == UX_PROTOCOL_VERSION,
        "ffmpeg": bool(ffmpeg),
        "ffmpeg_path": ffmpeg or "",
        "ffprobe": bool(ffprobe),
        "ffprobe_path": ffprobe or "",
        "duration_probe": duration_probe,
        "duration_probe_available": bool(duration_probe),
        "ffprobe_optional": bool(ffmpeg and not ffprobe),
        "backend_origin": BACKEND_ORIGIN,
        "deployment_mode": DEPLOYMENT_MODE,
        "public_access_protected": bool(PUBLIC_DEPLOYMENT and PUBLIC_PASSWORD),
        "extension_connected": bool(_extension_heartbeat_at and time.monotonic() - _extension_heartbeat_at <= EXTENSION_HEARTBEAT_TTL_SECONDS),
        "local_asr_available": local_asr_available,
        "local_asr_package": "faster-whisper",
        "local_asr_install_hint": "pip install faster-whisper" if not local_asr_available else "",
        "yt_dlp_available": ytdlp_package_available or bool(ytdlp_cli),
        "yt_dlp_package_available": ytdlp_package_available,
        "yt_dlp_cli_path": ytdlp_cli,
        "yt_dlp_install_hint": "pip install yt-dlp" if not (ytdlp_package_available or ytdlp_cli) else "",
        "llm_model_configured": bool(LLM_API_KEY),
        "vision_model_configured": bool(LLM_API_KEY) and llm_model_supports_vision(LLM_BASE_URL, LLM_MODEL),
        "default_llm_model": LLM_MODEL,
        "default_llm_base_url": LLM_BASE_URL,
        "default_llm_base_host": llm_base_host(LLM_BASE_URL),
        "default_llm_provider": llm_provider_name(LLM_BASE_URL),
        "data_paths": data_paths_payload(),
        "model_provider_presets": MODEL_PROVIDER_PRESETS,
        "assistant_capabilities": ASSISTANT_CAPABILITIES,
    }


def _clip_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _question_terms(question: str) -> set[str]:
    text = str(question or "").lower()
    focus_text = re.split(r"(?:不要|别再?|无需|不必|避免|排除|不讨论)", text, maxsplit=1)[0].strip() or text
    terms = {item for item in re.findall(r"[a-z0-9_]{2,}", focus_text, re.I) if item.strip()}
    for phrase in re.findall(r"[\u4e00-\u9fff]+", focus_text):
        if len(phrase) <= 8:
            terms.add(phrase)
        for size in range(2, min(4, len(phrase)) + 1):
            terms.update(phrase[index:index + size] for index in range(len(phrase) - size + 1))
    if re.search(r"原话|说话|讲了|讲的|字幕|转写|台词|transcript", text):
        terms.add("__source_transcript__")
    if re.search(r"画面|截图|视觉|演示|操作|界面|切片|ppt|slide", text):
        terms.add("__source_visual__")
    terms.difference_update({
        "什么", "怎么", "如何", "一下", "这个", "那个", "哪些", "是否", "可以", "请问",
        "视频", "回答", "根据", "只根", "只根据", "介绍", "说话人",
        "the", "and", "what", "how", "this", "that", "with", "from",
    })
    if not terms:
        terms.update(char for char in focus_text if char.strip())
    return terms


def _score_excerpt(text: str, terms: set[str]) -> int:
    lowered = str(text or "").lower()
    return sum(lowered.count(term.lower()) * min(4, max(1, len(term))) for term in terms)


def _strict_transcript_evidence_requested(question: str) -> bool:
    text = re.sub(r"\s+", "", str(question or "").lower())
    transcript_source = r"(?:字幕|转写|原话|台词|transcript)"
    return bool(
        re.search(rf"(?:只|仅|必须|务必).{{0,8}}{transcript_source}", text)
        or re.search(rf"{transcript_source}(?:证据|为准|回答)", text)
        or (
            re.search(transcript_source, text)
            and re.search(r"不要(?:使用|依据|根据|看|用)?.{0,4}(?:笔记|总结|画面)", text)
        )
    )


def _citation_is_trusted(citation: dict) -> bool:
    if not isinstance(citation, dict):
        return False
    text = _clip_text(str(citation.get("text") or ""), 1800)
    if not text:
        return False
    return not browser_subtitle_text_is_player_ui(text)


def _sanitize_citations(citations: list[dict]) -> list[dict]:
    return [citation for citation in citations if _citation_is_trusted(citation)]


def _note_evidence_chunks(note: str, limit: int = 80) -> list[dict]:
    chunks: list[dict] = []
    heading = ""
    for raw_block in re.split(r"\n{2,}|(?=^#{1,6}\s)", note, flags=re.M):
        block = raw_block.strip()
        if not block:
            continue
        heading_match = re.match(r"^#{1,6}\s+(.+)", block)
        if heading_match:
            heading = _clip_text(heading_match.group(1), 100)
            if "\n" not in block:
                continue
        text = _clip_text(block, 900)
        if len(text) < 2:
            continue
        chunks.append({
            "source": "note",
            "label": heading or f"笔记片段 {len(chunks) + 1}",
            "text": text,
            "target_tab": "note",
        })
        if len(chunks) >= limit:
            break
    return chunks


def _transcript_window_chunks(segments: list[dict], window_seconds: int = 120, step_seconds: int = 60) -> list[dict]:
    valid_segments = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = _clip_text(str(segment.get("text") or ""), 700)
        if not text or browser_subtitle_text_is_player_ui(text):
            continue
        valid_segments.append({
            "start": _safe_seconds(segment.get("start")),
            "end": _safe_seconds(segment.get("end")),
            "text": text,
        })
    if not valid_segments:
        return []

    groups: list[list[dict]] = []
    for item in valid_segments:
        if not groups or item["start"] - groups[-1][-1]["end"] > 30:
            groups.append([item])
        else:
            groups[-1].append(item)

    chunks = []
    for group in groups:
        first_start = int(group[0]["start"] // step_seconds) * step_seconds
        final_end = max(item["end"] for item in group)
        window_start = first_start
        while window_start < final_end:
            window_end = window_start + window_seconds
            members = [
                item for item in group
                if item["end"] > window_start and item["start"] < window_end
            ]
            if members:
                text = _clip_text(" ".join(item["text"] for item in members), 1800)
                if browser_subtitle_text_is_player_ui(text):
                    window_start += step_seconds
                    continue
                start = _format_timestamp(window_start)
                end = _format_timestamp(min(window_end, final_end))
                chunks.append({
                    "source": "transcript",
                    "granularity": "window",
                    "label": f"字幕 {start}-{end}",
                    "text": text,
                    "start": float(window_start),
                    "end": float(min(window_end, final_end)),
                    "time_range": f"{start}-{end}",
                    "target_tab": "transcript",
                })
            window_start += step_seconds
    return chunks


def _task_qa_context(task: TaskRecord) -> tuple[str, list[dict]]:
    citations: list[dict] = []
    try:
        note = read_note(task.id)
    except Exception:
        note = ""
    if note.strip():
        citations.extend(_note_evidence_chunks(note))

    try:
        transcript = read_transcript(task.id)
    except Exception:
        transcript = {}
    segments = transcript.get("segments") if isinstance(transcript, dict) else []
    if isinstance(segments, list) and segments:
        citations.extend(_transcript_window_chunks(segments))
        for segment in segments[:3000]:
            if not isinstance(segment, dict):
                continue
            text = _clip_text(str(segment.get("text") or ""), 700)
            if not text or browser_subtitle_text_is_player_ui(text):
                continue
            start_seconds = _safe_seconds(segment.get("start"))
            end_seconds = _safe_seconds(segment.get("end"))
            start = _format_timestamp(start_seconds)
            end = _format_timestamp(end_seconds)
            citations.append({
                "source": "transcript",
                "label": f"字幕 {start}",
                "text": text,
                "start": start_seconds,
                "end": end_seconds,
                "time_range": f"{start}-{end}",
                "target_tab": "transcript",
            })

    try:
        visual_index = read_visual_index(task.id)
    except Exception:
        visual_index = {}
    windows = visual_index.get("windows") if isinstance(visual_index, dict) else []
    if isinstance(windows, list) and windows:
        for window_index, window in enumerate(windows[:80], start=1):
            if not isinstance(window, dict):
                continue
            window_id = window.get("id") or f"W{window_index:03d}"
            start_seconds = _safe_seconds(window.get("start"))
            end_seconds = _safe_seconds(window.get("end"))
            start = _format_timestamp(start_seconds)
            end = _format_timestamp(end_seconds)
            excerpt = _clip_text(window.get("transcript_excerpt", ""), 260)
            citations.append({
                "source": "visual_window",
                "label": window_id,
                "text": _clip_text(excerpt or f"{window_id} {start}-{end}", 500),
                "window_id": window_id,
                "start": start_seconds,
                "end": end_seconds,
                "time_range": f"{start}-{end}",
                "grid_url": str(window.get("grid_url") or ""),
                "target_tab": "slices",
            })

    citations = _sanitize_citations(citations)
    context = "\n\n".join(
        f"[{item.get('source')}] {item.get('label')}: {item.get('text')}"
        for item in citations
    )
    return context, citations


def _rank_citations_for_question(
    citations: list[dict],
    terms: set[str],
    related_terms: set[str] | None = None,
    limit: int = 6,
) -> list[dict]:
    ranked = []
    related_terms = related_terms or set()
    citations = _sanitize_citations(citations)
    for index, citation in enumerate(citations):
        if not isinstance(citation, dict):
            continue
        text = " ".join([
            str(citation.get("label") or ""),
            str(citation.get("text") or ""),
            str(citation.get("window_id") or ""),
        ])
        current_score = _score_excerpt(text, terms)
        history_score = _score_excerpt(text, related_terms)
        score = current_score * 6 + history_score
        source = str(citation.get("source") or "")
        if "__source_transcript__" in terms and source == "transcript":
            score += 10000
        if "__source_visual__" in terms and source.startswith("visual"):
            score += 10000
        ranked.append((score, -index, citation))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    top_score = ranked[0][0] if ranked else 0
    relevance_floor = max(1, int(top_score * 0.2))
    relevant = [citation for score, _index, citation in ranked if score >= relevance_floor][:limit]
    if relevant:
        if "__source_transcript__" in terms:
            windows_by_start = {
                int(float(citation.get("start") or 0)): citation
                for citation in citations
                if citation.get("source") == "transcript" and citation.get("granularity") == "window"
            }
            expanded: list[dict] = []
            seen_ids: set[int] = set()
            for citation in relevant:
                for item in (citation, windows_by_start.get(int(float(citation.get("start") or -60)) + 60)):
                    if not item or id(item) in seen_ids:
                        continue
                    expanded.append(item)
                    seen_ids.add(id(item))
                    if len(expanded) >= limit:
                        return expanded
            if expanded:
                return expanded
        return relevant

    # Broad requests such as “总结一下” still need a small, source-diverse sample.
    fallback: list[dict] = []
    seen_sources: set[str] = set()
    for _score, _index, citation in ranked:
        source = str(citation.get("source") or "")
        if source in seen_sources and len(fallback) < 3:
            continue
        fallback.append(citation)
        seen_sources.add(source)
        if len(fallback) >= min(3, limit):
            break
    return fallback


def _recent_qa_history(task_id: str, limit: int = 4) -> list[dict]:
    return read_task_qa_history(task_id)[-limit:]


def _is_follow_up_question(question: str) -> bool:
    text = re.sub(r"\s+", "", str(question or "").lower())
    return bool(re.search(
        r"^(那|那么|所以|然后|还有|另外|刚才|前面|上面)|"
        r"(它|这个|那个|上述|前述|前面提到|刚才提到|继续说|展开说|为什么必须有它)",
        text,
    ))


def _qa_history_terms(history: list[dict]) -> set[str]:
    terms: set[str] = set()
    for item in history:
        terms.update(_question_terms(str(item.get("question") or "")))
        for citation in item.get("citations") or []:
            if isinstance(citation, dict):
                terms.update(_question_terms(str(citation.get("text") or "")))
    return terms


def _qa_history_messages(history: list[dict]) -> list[dict]:
    messages: list[dict] = []
    for item in history[-4:]:
        question = _clip_text(str(item.get("question") or ""), 600)
        if question:
            messages.append({"role": "user", "content": question})
    return messages


def _qa_evidence_prompt(citations: list[dict]) -> str:
    lines = []
    for index, citation in enumerate(citations, start=1):
        metadata = " · ".join(
            str(citation.get(key) or "") for key in ("window_id", "time_range") if citation.get(key)
        )
        suffix = f" ({metadata})" if metadata else ""
        lines.append(
            f"[E{index}] {citation.get('label') or citation.get('source')}{suffix}: "
            f"{_clip_text(str(citation.get('text') or ''), 900)}"
        )
    return "\n".join(lines)


def _local_task_answer(question: str, citations: list[dict]) -> tuple[str, list[dict]]:
    if not citations:
        return "现有笔记、字幕和画面索引中没有找到与这个问题相关的内容。", []
    excerpts = []
    for citation in citations[:3]:
        text = _clip_text(str(citation.get("text") or ""), 360)
        if text:
            excerpts.append(f"- {text}")
    if not excerpts:
        return "现有证据不足，暂时无法回答这个问题。", citations
    return "根据现有内容：\n" + "\n".join(excerpts), citations


def read_task_qa_history(task_id: str) -> list[dict]:
    data = read_json(task_id, QA_HISTORY_FILE, {"items": []})
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("items", [])
    else:
        items = []
    sanitized_items: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sanitized = dict(item)
        citations = item.get("citations") if isinstance(item.get("citations"), list) else []
        trusted_citations = _sanitize_citations(citations)
        # A historical answer whose entire evidence trail is player chrome or
        # danmaku should not remain visible after the evidence is rejected.
        if citations and not trusted_citations:
            continue
        sanitized["citations"] = trusted_citations
        sanitized_items.append(sanitized)
    return sanitized_items


def append_task_qa_history(task: TaskRecord, request: TaskQuestionRequest, result: dict) -> tuple[dict, list[dict]]:
    history = read_task_qa_history(task.id)
    item = {
        "id": uuid4().hex[:10],
        "created_at": now_iso(),
        "question": _clip_text(request.question, 1000),
        "answer": str(result.get("answer") or ""),
        "source": str(result.get("source") or ""),
        "warning": _clip_text(str(result.get("warning") or ""), 500),
        "provider": str(result.get("provider") or ""),
        "model": str(result.get("model") or ""),
        "citations": [
            {
                "source": _clip_text(str(citation.get("source") or ""), 120),
                "label": _clip_text(str(citation.get("label") or ""), 120),
                "text": _clip_text(str(citation.get("text") or ""), 800),
                "window_id": _clip_text(str(citation.get("window_id") or ""), 80),
                "time_range": _clip_text(str(citation.get("time_range") or ""), 80),
                "grid_url": _clip_text(str(citation.get("grid_url") or ""), 500),
                "target_tab": _clip_text(str(citation.get("target_tab") or ""), 40),
                "start": citation.get("start") if isinstance(citation.get("start"), (int, float)) else None,
                "end": citation.get("end") if isinstance(citation.get("end"), (int, float)) else None,
            }
            for citation in _sanitize_citations(result.get("citations") or [])[:12]
            if isinstance(citation, dict)
        ],
    }
    history.append(item)
    write_json(task.id, QA_HISTORY_FILE, {"schema_version": 1, "items": history})
    return item, history


def render_qa_history_markdown(task: TaskRecord, history: list[dict] | None = None) -> str:
    items = history if history is not None else read_task_qa_history(task.id)
    lines = [
        "# LearnNote 问答记录",
        "",
        f"- 任务：{task.title}",
        f"- ID：{task.id}",
        f"- 页面：{task.page_url or '-'}",
        f"- 问答数：{len(items)}",
        "",
    ]
    if not items:
        lines.append("暂无问答记录。")
        return "\n".join(lines)
    for index, item in enumerate(items, start=1):
        lines.extend([
            f"## Q{index}. {item.get('question') or '-'}",
            "",
            f"- 时间：{item.get('created_at') or '-'}",
            f"- 来源：{item.get('source') or '-'}",
            f"- 模型：{item.get('provider') or '-'} / {item.get('model') or '-'}",
        ])
        if item.get("warning"):
            lines.append(f"- 提示：{item.get('warning')}")
        lines.extend(["", str(item.get("answer") or "-"), ""])
        citations = item.get("citations") if isinstance(item.get("citations"), list) else []
        if citations:
            lines.append("### 证据")
            for citation in citations:
                if not isinstance(citation, dict):
                    continue
                label = citation.get("label") or citation.get("source") or "证据"
                text = citation.get("text") or ""
                meta = " · ".join(str(citation.get(key) or "") for key in ("window_id", "time_range") if citation.get(key))
                grid = citation.get("grid_url") or ""
                suffix = f"（{meta}）" if meta else ""
                lines.append(f"- **{label}**{suffix}：{text}")
                if grid:
                    lines.append(f"  - 画面网格：{grid}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def qa_history_preview(history: list[dict], limit: int = 5) -> list[dict]:
    preview = []
    for item in history[-limit:]:
        preview.append({
            "id": item.get("id", ""),
            "created_at": item.get("created_at", ""),
            "question": _clip_text(str(item.get("question") or ""), 180),
            "answer_excerpt": _clip_text(str(item.get("answer") or ""), 420),
            "source": item.get("source", ""),
            "warning": _clip_text(str(item.get("warning") or ""), 220),
            "provider": item.get("provider", ""),
            "model": item.get("model", ""),
            "citation_count": len(item.get("citations") or []) if isinstance(item.get("citations"), list) else 0,
        })
    return list(reversed(preview))


def task_next_actions(task: TaskRecord, limit: int = 9) -> list[dict]:
    actions: list[dict] = []
    seen: set[str] = set()

    def add(key: str, label: str, detail: str, intent: str, target: str = "") -> None:
        if not key or key in seen or len(actions) >= limit:
            return
        seen.add(key)
        actions.append({
            "key": key,
            "label": label,
            "detail": detail,
            "intent": intent,
            "target": target,
        })

    media_ready = task_media_file_exists(task)
    note_ready = bool(task.note_path)
    transcript_ready = bool(task.transcript_path or task.browser_subtitles)
    visual_ready = bool(task.visual_windows or task.frame_grids or task.visual_index_path)
    qa_ready = note_ready or transcript_ready or visual_ready
    has_diagnostics = bool(task.download_attempts or task.error_code or task.selected_resource or task.summary_diagnostics)
    can_continue_media = task_media_ready_for_rerun(task, allow_existing_note=True) and (
        task.mode == "download_only" or not note_ready or task.status == "failed"
    )
    media_name = task_media_display_name(task) if media_ready else "media.mp4"

    if can_continue_media:
        add(
            "continue_from_media",
            f"从 {media_name} 继续",
            "复用已下载视频进入转写、抽帧、视觉窗口和图文总结；不会录制页面。",
            "rerun_from_media",
        )
    if qa_ready:
        add(
            "ask_assistant",
            "打开 AI 助手",
            "在侧栏中基于当前任务的笔记、字幕和画面索引继续追问。",
            "open_assistant",
            "current_task",
        )
    if note_ready:
        add("export_markdown", "导出 Markdown", "保存当前学习笔记。", "export", "markdown")
    if visual_ready:
        add("review_slices", "复核学习切片", "按视觉窗口回看截图、字幕片段和复习问题。", "switch_tab", "slices")
        add("export_visual_windows", "导出切片索引", "保存画面窗口、截图网格和回看问题。", "export", "visual-windows")
    if transcript_ready:
        add("review_transcript", "核对字幕", "先检查平台字幕或 ASR 转写，再继续总结。", "switch_tab", "transcript")
    if media_ready:
        add("export_media", f"导出 {media_name}", "核对本地直取视频文件。", "export", "media")
    if note_ready or visual_ready or transcript_ready or has_diagnostics:
        add("export_bundle", "导出资料包", "打包笔记、字幕、视觉索引、审计和诊断。", "export", "bundle")
    if has_diagnostics:
        add("view_diagnostics", "看下载诊断", "查看候选资源、请求上下文、失败原因和边界说明。", "switch_tab", "diagnostics")
        add("export_diagnostics", "导出诊断", "保存直取证据和失败路径，方便复盘。", "export", "diagnostics")
    if not actions:
        add("wait_for_task", "等待任务产物", "任务完成后这里会出现继续学习、导出和诊断动作。", "status")
    return actions


def task_qa_suggestions(task: TaskRecord, limit: int = 7) -> list[dict]:
    suggestions: list[dict] = []
    seen: set[str] = set()

    def add(label: str, question: str, source: str) -> None:
        normalized = " ".join(question.split())
        if not normalized or normalized in seen or len(suggestions) >= limit:
            return
        seen.add(normalized)
        suggestions.append({"label": label, "question": normalized, "source": source})

    has_note = bool(task.note_path)
    has_transcript = bool(task.transcript_path or task.browser_subtitles)
    has_visual = bool(task.visual_index_path or task.visual_windows or task.frame_grids)

    if has_note:
        add("核心概念", "这节课最重要的 3 个概念是什么？请用适合复习的方式解释。", "note")
        add("时间轴重点", "按时间顺序列出这节课的重点、例题和操作步骤。", "note")
        add("易错点", "这节课有哪些容易混淆或考试容易错的地方？", "note")
    if has_transcript:
        add("字幕梳理", "根据字幕提取老师反复强调的关键词，并说明它们之间的关系。", "transcript")
        add("自测题", "基于这节课生成 5 道复习自测题，并附简短答案。", "transcript")
    if has_visual:
        add("画面线索", "结合画面索引，哪些 PPT、代码或演示步骤最值得回看？", "visual")
        first_window = task.visual_windows[0] if task.visual_windows else None
        if first_window:
            label = first_window.id or f"W{first_window.index + 1:03d}"
            add(
                label,
                f"请解释 {label}（{_format_timestamp(first_window.start)}-{_format_timestamp(first_window.end)}）这一段画面和字幕对应的学习重点。",
                "visual",
            )
    if not suggestions:
        add("页面文本", "如果当前任务没有视频结果，请先总结当前页面文本的主要内容。", "page")
    return suggestions


def _answer_task_question(task: TaskRecord, request: TaskQuestionRequest) -> dict:
    options = merge_task_options(task.options, request.options)
    context, all_citations = _task_qa_context(task)
    strict_transcript = _strict_transcript_evidence_requested(request.question)
    if strict_transcript:
        all_citations = [citation for citation in all_citations if citation.get("source") == "transcript"]
        if not all_citations:
            return {
                "answer": "没有找到可信的字幕或转写证据，无法只依据字幕回答这个问题。请先重新生成字幕或核对转写结果。",
                "source": "insufficient-evidence",
                "warning": "trusted_transcript_missing",
                "provider": "",
                "model": "",
                "citations": [],
            }
        context = "\n\n".join(
            f"[{item.get('source')}] {item.get('label')}: {item.get('text')}"
            for item in all_citations
        )
    if not context.strip():
        raise HTTPException(status_code=404, detail={"code": "task_context_missing", "message": "任务还没有可用于问答的笔记、字幕或画面索引。"})

    history = [] if strict_transcript else (_recent_qa_history(task.id) if _is_follow_up_question(request.question) else [])
    question_terms = _question_terms(request.question)
    citations = _rank_citations_for_question(
        all_citations,
        question_terms,
        related_terms=_qa_history_terms(history),
    )
    evidence_prompt = _qa_evidence_prompt(citations)

    api_key = options.llm_api_key or LLM_API_KEY
    base_url = options.llm_base_url or LLM_BASE_URL
    model = options.llm_model or LLM_MODEL
    if api_key:
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=LLM_REQUEST_TIMEOUT_SECONDS,
                max_retries=LLM_MAX_RETRIES,
            )
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是 LearnNote 的课程问答助手。只能依据当前消息中列出的 E 编号证据回答；"
                            "历史对话仅用于理解追问指代，不是事实证据。禁止补充常识、猜测或虚构内容。"
                            "不得编造证据中不存在的时间窗、W 编号、页码、步骤或原文引语；"
                            "只有证据逐字包含的内容才能使用引号。证据不足时直接说“现有证据不足”，"
                            "分析操作演示时要区分当前设置与假设示例：‘这里设为/达到/我们认为/我们设置的是 X’表示演示采用 X，"
                            "‘可以改成/比方说 X’仅表示替代示例；应综合相邻时间窗，不要因为 ASR 错写参数名而忽略明确的数值和含义。"
                            "不要假装知道，也不要推荐不存在的回看位置。默认用中文简洁直接回答，"
                            "通常 1-3 个短段落或不超过 5 个要点，不复述问题，不描述你的工作过程。"
                        ),
                    },
                    *_qa_history_messages(history),
                    {
                        "role": "user",
                        "content": (
                            f"任务：{task.title}\n"
                            f"问题：{request.question}\n\n"
                            "可用证据：\n"
                            f"{evidence_prompt or '（没有检索到相关证据）'}"
                        ),
                    },
                ],
                **chat_completion_provider_kwargs(base_url),
            )
            answer = response.choices[0].message.content or ""
            if answer.strip():
                return {
                    "answer": answer.strip(),
                    "source": "llm",
                    "warning": "",
                    "provider": llm_provider_name(base_url),
                    "model": model,
                    "citations": citations,
                }
        except Exception:
            local_answer, local_citations = _local_task_answer(request.question, citations)
            return {
                "answer": local_answer,
                "source": "local-extractive",
                "warning": "llm_qa_failed",
                "provider": llm_provider_name(base_url),
                "model": model,
                "citations": local_citations,
            }

    local_answer, local_citations = _local_task_answer(request.question, citations)
    return {
        "answer": local_answer,
        "source": "local-extractive",
        "warning": "missing_api_key",
        "provider": llm_provider_name(base_url),
        "model": model,
        "citations": local_citations,
    }


@app.get("/health")
def health() -> dict:
    return health_payload()


def _hostname_matches(hostname: str, domain: str) -> bool:
    normalized_host = (hostname or "").lower().rstrip(".")
    normalized_domain = domain.lower().rstrip(".")
    return normalized_host == normalized_domain or normalized_host.endswith(f".{normalized_domain}")


def _automatic_diagnostic_rules(context: dict, task: TaskRecord | None) -> tuple[str, str, list[dict], list[dict]]:
    findings: list[dict] = []
    actions: list[dict] = []

    def finding(severity: str, title: str, detail: str) -> None:
        findings.append({"severity": severity, "title": title, "detail": detail})

    def action(key: str, label: str, detail: str) -> None:
        actions.append({"key": key, "label": label, "detail": detail})

    page_url = str(context.get("page_url") or "")
    tab_url = str(context.get("tab_url") or "")
    candidate_count = max(0, int(context.get("candidate_count") or 0))
    downloadable_count = max(0, int(context.get("downloadable_count") or 0))
    active_video = bool(context.get("active_video"))
    drm_detected = bool(context.get("drm_detected"))
    extension_version = str(context.get("extension_version") or "")
    backend_version = str(context.get("backend_version") or APP_VERSION)
    page_host = (urlsplit(tab_url or page_url).hostname or "").lower()
    page_resolver = any(
        _hostname_matches(page_host, domain)
        for domain in ("youtu.be", "youtube.com", "bilibili.com")
    )

    if page_url and tab_url and page_url.split("#", 1)[0] != tab_url.split("#", 1)[0]:
        finding("error", "当前页上下文已串页", "扩展缓存页面 URL 与 Chrome 当前标签 URL 不一致，可能总结上一条视频。")
        action("redetect", "重新检测当前页", "清空旧视频上下文并重新读取当前标签。")
    elif tab_url or page_url:
        finding("pass", "当前页 URL 已对齐", tab_url or page_url)

    if extension_version and extension_version != backend_version:
        finding("warn", "扩展与客户端版本不同", f"扩展 {extension_version}，客户端 {backend_version}。")
        action("reload_extension", "刷新浏览器扩展", "在扩展管理页重新加载 D:\\LearnNote\\Extension。")

    if drm_detected:
        finding("error", "检测到加密媒体信号", "当前页面可能只暴露 DRM/EME 流，不能通过普通下载路线还原。")
        action("local", "改用本地视频", "导入你有权访问的本地视频，继续同一套转写和切片流程。")
    elif downloadable_count:
        finding("pass", "发现可直取媒体", f"{downloadable_count}/{candidate_count} 个候选可进入预检。")
        action("preflight", "预检最佳候选", "确认本地后端可以访问媒体地址后再开始总结。")
    elif page_resolver:
        finding("pass", "当前站点支持页面解析", "即使没有媒体候选，也可以直接把视频页面交给 yt-dlp。")
        action("summarize", "直接总结当前视频", "按当前页面 URL 下载视频，不等待播放器 DOM 证据。")
    elif active_video:
        finding("warn", "播放器已出现但没有直链", "继续播放并重新检测，让扩展捕获 manifest、分片或播放接口。")
        action("redetect", "播放后重新检测", "保持视频播放数秒，再刷新当前页媒体上下文。")
    else:
        finding("warn", "尚未读取播放器", "当前页没有活动视频或媒体候选。")
        action("redetect", "重新读取当前页", "确认处于视频详情页并让播放器实际开始播放。")

    if task:
        if task.status == "failed":
            finding("error", "最近任务失败", f"{task.error_code or task.failed_phase or 'unknown'}：{_clip_text(task.error_detail or task.message, 220)}")
            action("task_diagnostics", "查看任务诊断", "打开最近任务的下载尝试、失败阶段和恢复建议。")
        elif task.status in {"queued", "running", "cancelling"}:
            finding("info", "任务仍在处理", f"{task.phase}：{_clip_text(task.message, 180)}")
        elif task.status == "success":
            finding("pass", "最近任务已完成", f"任务 {task.id} 已生成可用产物。")

    severity = "error" if any(item["severity"] == "error" for item in findings) else "warn" if any(item["severity"] == "warn" for item in findings) else "pass"
    summary = {
        "error": "发现会阻断或导致内容不一致的问题。",
        "warn": "主链路可继续，但有需要处理的风险。",
        "pass": "当前页、下载路线和客户端状态没有发现明显阻断。",
    }[severity]
    return severity, summary, findings, actions


@app.post("/api/diagnostics/auto")
def automatic_diagnostics(payload: dict | None = Body(default=None)) -> dict:
    body = payload or {}
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    task = None
    task_id = str(body.get("task_id") or "").strip()
    if re.fullmatch(r"[a-f0-9]{12}", task_id):
        try:
            task = get_task(task_id)
        except Exception:
            task = None

    severity, summary, findings, actions = _automatic_diagnostic_rules(context, task)
    ai_analysis = ""
    ai_source = "rules"
    options_payload = body.get("options") if isinstance(body.get("options"), dict) else {}
    try:
        options = TaskOptions.model_validate(options_payload)
    except ValidationError:
        options = TaskOptions()
    api_key = options.llm_api_key or LLM_API_KEY
    base_url = options.llm_base_url or LLM_BASE_URL
    model = options.llm_model or LLM_MODEL
    if api_key:
        try:
            from openai import OpenAI

            safe_context = {
                "page_url": context.get("page_url"),
                "tab_url": context.get("tab_url"),
                "active_video": bool(context.get("active_video")),
                "candidate_count": context.get("candidate_count"),
                "downloadable_count": context.get("downloadable_count"),
                "playback_matched_count": context.get("playback_matched_count"),
                "drm_detected": bool(context.get("drm_detected")),
                "extension_version": context.get("extension_version"),
                "backend_version": context.get("backend_version"),
                "task": {"id": task.id, "status": task.status, "phase": task.phase, "error_code": task.error_code, "error_detail": _clip_text(task.error_detail, 240)} if task else None,
                "rule_findings": findings,
            }
            response = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=LLM_REQUEST_TIMEOUT_SECONDS,
                max_retries=LLM_MAX_RETRIES,
            ).chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": (
                    "你是 LearnNote 本地客户端的故障诊断助手。请根据下面脱敏状态，用中文给出不超过 180 字的判断。"
                    "先说根因，再说用户下一步；不要猜测未提供的事实，不要要求绕过 DRM，不要输出 JSON。"
                    "candidate_count 为 0 只表示扩展没有抓到直链，不等于 yt-dlp 失败；B站和 YouTube 可以直接按页面解析。"
                    "如果 task.status 是 success，严禁声称下载、解析或任务失败。规则检查结果是事实，不能与其矛盾。\n\n"
                    + json.dumps(safe_context, ensure_ascii=False)
                )}],
                **chat_completion_provider_kwargs(base_url),
            )
            ai_analysis = _clip_text(response.choices[0].message.content or "", 600)
            contradicts_success = bool(
                task
                and task.status == "success"
                and re.search(r"(?:yt-dlp|下载|解析|任务).{0,12}(?:失败|未成功|异常)", ai_analysis, re.I)
            )
            if contradicts_success:
                ai_analysis = ""
            if ai_analysis:
                ai_source = "llm"
        except Exception as exc:
            ai_analysis = f"AI 分析暂不可用，已保留本地规则诊断：{type(exc).__name__}。"

    return {
        "ok": True,
        "severity": severity,
        "summary": summary,
        "findings": findings,
        "actions": actions,
        "ai_analysis": ai_analysis,
        "source": ai_source,
        "provider": llm_provider_name(base_url),
        "model": model,
    }


@app.get("/api/health")
def api_health() -> dict:
    return health_payload()


@app.post("/api/desktop/focus")
def desktop_focus(payload: dict | None = Body(default=None)) -> dict:
    callback = getattr(app.state, "desktop_focus", None)
    if not callable(callback):
        return {"ok": False, "available": False}
    callback(payload or {})
    return {"ok": True, "available": True}


@app.get("/api/preferences")
def get_preferences() -> dict:
    path = DATA_DIR / "preferences.json"
    if not path.is_file():
        return {"task_options": TaskOptions().model_dump(exclude={"llm_api_key", "llm_base_url", "llm_model"})}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        options = TaskOptions.model_validate(payload.get("task_options") or {})
    except (OSError, ValueError, ValidationError):
        options = TaskOptions()
    return {"task_options": options.model_dump(exclude={"llm_api_key", "llm_base_url", "llm_model"})}


@app.put("/api/preferences")
def put_preferences(payload: dict = Body(...)) -> dict:
    try:
        options = TaskOptions.model_validate(payload.get("task_options") or {})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid task preferences") from exc
    public_options = options.model_dump(exclude={"llm_api_key", "llm_base_url", "llm_model"})
    atomic_write_text(DATA_DIR / "preferences.json", json.dumps({"task_options": public_options}, ensure_ascii=False, indent=2))
    return {"ok": True, "task_options": public_options}


@app.post("/api/extension/heartbeat")
def extension_heartbeat(payload: dict | None = Body(default=None)) -> dict:
    global _extension_heartbeat_at, _extension_version, _extension_protocol_version
    _extension_heartbeat_at = time.monotonic()
    body = payload or {}
    _extension_version = str(body.get("extension_version") or _extension_version or "")[:32]
    try:
        _extension_protocol_version = int(body.get("protocol_version") or _extension_protocol_version or 0)
    except (TypeError, ValueError):
        _extension_protocol_version = 0
    compatible = not _extension_protocol_version or _extension_protocol_version == UX_PROTOCOL_VERSION
    return {
        "ok": True,
        "extension_connected": True,
        "extension_version": _extension_version,
        "protocol_version": UX_PROTOCOL_VERSION,
        "extension_compatible": compatible,
    }


@app.post("/api/tasks/from-current-page")
def create_from_current_page(request: CurrentPageTaskRequest, background_tasks: BackgroundTasks, defer: bool = False) -> dict:
    raw_page_url = request.page_url
    try:
        source = normalize_source_input(raw_page_url)
    except SourceInputError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_source_input", "message": str(exc)}) from exc
    explicit_title = request.title if request.title.strip() and request.title.strip() != raw_page_url.strip() else ""
    title = clean_task_title(explicit_title, source.url, source.default_title)
    request = request.model_copy(update={"page_url": source.url, "title": title})
    source_identity = current_page_source_identity(request)
    source_type = "page_text" if request.mode == "page_text" else "current_page"
    task = create_task(source_type=source_type, title=title, page_url=source.url, options=request.options, mode=request.mode)
    task = update_task(task.id, source_identity=source_identity)
    if request.browser_subtitles:
        task = update_task(task.id, browser_subtitles=request.browser_subtitles)
    if defer:
        highest_score_resource = max(request.resources, key=lambda item: item.score, default=None)
        handoff_integrity = build_handoff_integrity(request)
        task = update_task(
            task.id,
            awaiting_confirmation=True,
            status="queued",
            phase="queued",
            progress=0,
            message="Awaiting confirmation in LearnNote",
            active_video=request.active_video,
            browser_subtitles=request.browser_subtitles,
            selected_resource=redacted_resource(highest_score_resource) if highest_score_resource else None,
            handoff_integrity=handoff_integrity,
        )
        write_json(task.id, "deferred_preflight.json", redacted_request_dump(request))
        with _deferred_handoffs_lock:
            _deferred_handoffs[task.id] = request.model_copy(deep=True)
        return {"task_id": task.id, "task": task_payload(task)}
    background_tasks.add_task(process_current_page_task, task.id, request)
    return {"task_id": task.id, "task": task_payload(task)}


@app.post("/api/tasks/{task_id}/start")
def start_deferred_current_page_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    options: TaskOptions | None = Body(default=None),
) -> dict:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "Task not found"}) from exc
    if task.status != "queued" or not task.awaiting_confirmation:
        raise HTTPException(
            status_code=409,
            detail={"code": "not_awaiting_confirmation", "message": "Task is not waiting for confirmation."},
        )
    with _deferred_handoffs_lock:
        deferred_request = _deferred_handoffs.get(task_id)
    if deferred_request is None:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "handoff_expired",
                "message": "The browser handoff expired after the backend restarted. Send the current page again.",
            },
        )
    merged_options = merge_task_options(deferred_request.options, options)
    deferred_request = deferred_request.model_copy(update={"options": merged_options}, deep=True)
    public_options = merged_options.model_copy(update={"llm_api_key": None})
    task = update_task(
        task_id,
        awaiting_confirmation=False,
        options=public_options,
        message="Confirmed; queued for processing",
    )
    background_tasks.add_task(process_current_page_task, task.id, deferred_request)
    with _deferred_handoffs_lock:
        _deferred_handoffs.pop(task_id, None)
    return {"task_id": task.id, "task": task_payload(task)}


@app.post("/api/media/preflight")
def api_media_preflight(request: MediaPreflightRequest) -> dict:
    result = preflight_media_resource(request.resource, request.cookies, request.page_url)
    return {"preflight": result}


@app.post("/api/media/preflight-current-page")
def api_page_media_preflight(request: PagePreflightRequest) -> dict:
    try:
        source = normalize_source_input(request.page_url)
    except SourceInputError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_source_input", "message": str(exc)}) from exc
    normalized = request.model_copy(update={"page_url": source.url})
    return {"source": source.as_dict(), "report": page_preflight_report(normalized)}


@app.post("/api/source/normalize")
def api_normalize_source(request: SourceInputRequest) -> dict:
    try:
        return {"source": normalize_source_input(request.value).as_dict()}
    except SourceInputError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_source_input", "message": str(exc)}) from exc


@app.post("/api/media/preflight-local")
async def api_preflight_local(file: UploadFile = File(...)) -> dict:
    cleanup_expired_staged_uploads()
    safe_name = local_upload_filename(file.filename, file.content_type)
    staging_token = uuid4().hex
    staged_path = UPLOAD_DIR / f"staged_{staging_token}_{safe_name}"
    try:
        with staged_path.open("wb") as output:
            while True:
                chunk = await file.read(LOCAL_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
        integrity = validate_local_upload_file(staged_path)
    except HTTPException:
        staged_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        staged_path.unlink(missing_ok=True)
        raise local_upload_error("local_preflight_failed", f"本地媒体预检失败：{exc}", status_code=500) from exc
    estimated_seconds = max(30, round(integrity.duration * 0.65 + 45))
    return {
        "title": Path(safe_name).stem,
        "duration": integrity.duration,
        "estimated_seconds": estimated_seconds,
        "integrity": integrity.model_dump(mode="json"),
        "source_fingerprint": integrity.sha256,
        "staging_token": staging_token,
    }


@app.post("/api/tasks/from-local")
async def create_from_local(
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(default=None),
    title: str = Form(""),
    options: str = Form("{}"),
    staging_token: str = Form(""),
) -> dict:
    try:
        parsed_options = TaskOptions.model_validate(json.loads(options or "{}"))
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise local_upload_error("invalid_task_options", f"本地视频处理参数无效：{exc}", status_code=422) from exc

    token = staging_token.strip().lower()
    if token and file is not None:
        raise local_upload_error("ambiguous_local_source", "请使用预检 token 或直接上传文件，不要同时提交。")
    if token:
        if not re.fullmatch(r"[a-f0-9]{32}", token):
            raise local_upload_error("invalid_staging_token", "预检 token 无效。")
        staged_matches = list(UPLOAD_DIR.glob(f"staged_{token}_*"))
        if len(staged_matches) != 1 or not staged_matches[0].is_file():
            raise local_upload_error("staging_token_not_found", "预检文件不存在或已被使用。", status_code=404)
        pending_path = staged_matches[0]
        safe_name = pending_path.name.split(f"staged_{token}_", 1)[-1]
        integrity = validate_local_upload_file(pending_path)
    else:
        if file is None:
            raise local_upload_error("missing_local_file", "请选择本地媒体文件或提交 staging_token。")
        safe_name = local_upload_filename(file.filename, file.content_type)
        pending_path = UPLOAD_DIR / f"pending_{uuid4().hex}_{safe_name}"
        try:
            with pending_path.open("wb") as output:
                while True:
                    chunk = await file.read(LOCAL_UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
            integrity = validate_local_upload_file(pending_path)
        except HTTPException:
            pending_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            pending_path.unlink(missing_ok=True)
            raise local_upload_error("local_upload_failed", f"保存本地视频失败：{exc}", status_code=500) from exc

    effective_title = title or Path(safe_name).stem
    task = create_task(source_type="local", title=effective_title, options=parsed_options, mode="local")
    upload_path = UPLOAD_DIR / f"{task.id}_{safe_name}"
    pending_path.replace(upload_path)
    integrity_path = write_json(task.id, "media_integrity.json", integrity.model_dump(mode="json"))
    task = update_task(
        task.id,
        source_media_path=str(upload_path),
        media_integrity=integrity,
        media_integrity_path=str(integrity_path),
        source_identity=local_source_identity(effective_title, integrity),
        message="Local upload saved; queued for processing",
    )
    background_tasks.add_task(process_local_video_task, task.id, upload_path, effective_title, parsed_options)
    return {"task_id": task.id, "task": task_payload(task)}


@app.post("/api/tasks/{task_id}/rerun-from-media")
def create_from_existing_media(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: RerunFromMediaRequest | TaskOptions | None = Body(default=None),
) -> dict:
    try:
        source = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc

    media_path = task_media_path(source)
    if not media_path:
        raw_media_path = source.media_path or source.source_media_path
        if raw_media_path:
            try:
                recorded_path = Path(raw_media_path)
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=400, detail={"code": "media_not_found", "message": "Downloaded media path is invalid"}) from exc
            if not recorded_path.exists():
                raise HTTPException(status_code=404, detail={"code": "media_not_found", "message": "Downloaded media file is missing"})
            if not recorded_path.is_file():
                raise HTTPException(status_code=400, detail={"code": "media_not_found", "message": "Downloaded media path is not a file"})
        raise HTTPException(status_code=404, detail={"code": "media_not_found", "message": "Task has no downloaded media"})
    if not media_path.is_file():
        raise HTTPException(status_code=400, detail={"code": "media_not_found", "message": "Downloaded media path is not a file"})
    if media_path.stat().st_size <= 0:
        raise HTTPException(status_code=400, detail={"code": "media_not_found", "message": "Downloaded media file is empty"})
    try:
        rerun_integrity = validate_local_upload_file(media_path)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "invalid_local_video", "message": str(exc.detail)}
        detail["code"] = "media_not_found"
        raise HTTPException(status_code=400, detail=detail) from exc

    parsed_options = merge_task_options(source.options, rerun_options_from_body(request))
    task = create_task(
        source_type="local",
        title=source.title or f"Media from {source.id}",
        page_url=source.page_url,
        options=parsed_options,
        mode="rerun_from_media",
    )
    task = update_task(
        task.id,
        source_task_id=source.id,
        source_media_path=str(media_path),
        media_integrity=rerun_integrity,
        source_identity=local_source_identity(source.title or media_path.stem, rerun_integrity),
        selected_resource=source.selected_resource,
        download_attempts=source.download_attempts,
        active_video=source.active_video,
        browser_subtitles=source.browser_subtitles,
        drm_detected=source.drm_detected,
        drm_signals=source.drm_signals,
        message="Queued from downloaded media",
    )
    source_transcript_source = ""
    try:
        source_transcript_source = str(read_transcript(source.id).get("source") or "")
    except Exception:
        source_transcript_source = ""
    source_subtitle_path = Path(source.subtitle_path) if source.subtitle_path else None
    if source_subtitle_path and not source_subtitle_path.exists():
        source_subtitle_path = None
    source_browser_subtitles = source.browser_subtitles
    subtitle_source = "page-subtitle"
    if source_transcript_source == "browser-subtitle" and source_browser_subtitles:
        source_subtitle_path = None
    elif source_transcript_source == "browser-subtitle" and source_subtitle_path:
        subtitle_source = "browser-subtitle"
    background_tasks.add_task(
        process_local_video_task,
        task.id,
        media_path,
        task.title,
        parsed_options,
        source.page_url,
        source_browser_subtitles,
        source_subtitle_path,
        subtitle_source,
    )
    return {"task_id": task.id, "task": task_payload(task), "source_task_id": source.id}


@app.get("/api/tasks")
def api_list_tasks() -> dict:
    return {"tasks": [task_payload(task) for task in list_tasks()]}


@app.get("/api/storage")
def api_storage_summary() -> dict:
    return storage_summary()


@app.post("/api/storage/cleanup")
def api_storage_cleanup(request: StorageCleanupRequest) -> dict:
    return cleanup_tasks(request.retention_days, request.keep_recent, request.dry_run)


@app.delete("/api/tasks")
def api_delete_all_tasks(confirm: str = "") -> dict:
    if confirm != "delete_all_tasks":
        raise HTTPException(
            status_code=400,
            detail={"code": "confirmation_required", "message": "请先确认删除全部任务。"},
        )
    try:
        return delete_all_tasks()
    except RuntimeError as exc:
        if str(exc) == "active_tasks":
            raise HTTPException(
                status_code=409,
                detail={"code": "tasks_still_running", "message": "仍有任务正在处理，请停止或等待完成后再删除全部。"},
            ) from exc
        raise


@app.post("/api/tasks/{task_id}/cancel")
def api_cancel_task(task_id: str) -> dict:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "任务不存在"}) from exc
    if task.status in {"success", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail={"code": "task_not_running", "message": "任务已经结束"})
    task = request_task_cancel(task_id)
    return {"task": task_payload(task)}


@app.post("/api/tasks/{task_id}/retry")
def api_retry_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: RerunFromMediaRequest | TaskOptions | None = Body(default=None),
) -> dict:
    try:
        source = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "任务不存在"}) from exc
    if source.status in {"queued", "running", "cancelling"}:
        raise HTTPException(status_code=409, detail={"code": "task_still_running", "message": "请先停止当前任务"})
    if not task_media_path(source):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "recapture_required",
                "message": "需要重新从当前播放页发起，才能刷新登录状态和视频地址。",
            },
        )
    update_task(task_id, retry_count=source.retry_count + 1)
    return create_from_existing_media(task_id, background_tasks, request)


@app.delete("/api/tasks/{task_id}")
def api_delete_task(task_id: str) -> dict:
    try:
        return delete_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "任务不存在"}) from exc
    except RuntimeError as exc:
        if str(exc) == "active_task":
            raise HTTPException(status_code=409, detail={"code": "task_still_running", "message": "请先停止任务再删除"}) from exc
        raise


@app.get("/api/tasks/{task_id}")
def api_get_task(task_id: str) -> dict:
    try:
        task = get_task(task_id)
        payload = task_payload(task)
        return {"task": payload, "audit": payload["audit"]}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc


@app.get("/api/tasks/{task_id}/audit")
def api_task_audit(task_id: str) -> dict:
    try:
        task = get_task(task_id)
        return {"task_id": task.id, "audit": task_audit_summary(task)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc


@app.get("/api/tasks/{task_id}/transcript")
def api_transcript(task_id: str) -> dict:
    try:
        return read_transcript(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc


@app.get("/api/tasks/{task_id}/note", response_class=PlainTextResponse)
def api_note(task_id: str) -> str:
    try:
        return read_note(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc


@app.post("/api/tasks/{task_id}/qa")
def api_task_question(task_id: str, request: TaskQuestionRequest) -> dict:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    result = _answer_task_question(task, request)
    history_item, history = append_task_qa_history(task, request, result)
    result["history_item"] = history_item
    result["history_count"] = len(history)
    return result


@app.get("/api/tasks/{task_id}/qa")
def api_task_question_history(task_id: str) -> dict:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return {"task_id": task.id, "items": read_task_qa_history(task.id)}


@app.get("/api/tasks/{task_id}/visual-index")
def api_visual_index(task_id: str) -> dict:
    try:
        return read_visual_index(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc


@app.get("/api/tasks/{task_id}/exports/markdown")
def api_export_markdown(task_id: str) -> PlainTextResponse:
    try:
        task = get_task(task_id)
        note = read_note(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    if not note.strip():
        raise HTTPException(status_code=404, detail="Note not found")
    filename = markdown_filename(task.id, task.title)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}.md"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return PlainTextResponse(note, media_type="text/markdown; charset=utf-8", headers=headers)


@app.get("/api/tasks/{task_id}/exports/visual-windows")
def api_export_visual_windows(task_id: str) -> PlainTextResponse:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    if not task.visual_windows and not task.frame_grids:
        raise HTTPException(status_code=404, detail="Visual windows not found")
    report = render_visual_windows_markdown(task)
    filename = visual_windows_filename(task.id, task.title)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}-visual-windows.md"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return PlainTextResponse(report, media_type="text/markdown; charset=utf-8", headers=headers)


@app.get("/api/tasks/{task_id}/exports/qa")
def api_export_qa(task_id: str) -> PlainTextResponse:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    history = read_task_qa_history(task.id)
    if not history:
        raise HTTPException(status_code=404, detail="QA history not found")
    report = render_qa_history_markdown(task, history)
    filename = qa_filename(task.id, task.title)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}-qa.md"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return PlainTextResponse(report, media_type="text/markdown; charset=utf-8", headers=headers)


@app.get("/api/tasks/{task_id}/exports/manifest")
def api_export_manifest(task_id: str) -> Response:
    try:
        task = get_task(task_id)
        transcript = read_transcript(task_id)
        visual_index = read_visual_index(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc

    qa_history = read_task_qa_history(task.id)
    has_artifact = bool(
        task_media_file_exists(task)
        or task.note_path
        or task.subtitle_path
        or task.transcript_path
        or task.visual_windows
        or task.frame_grids
        or task.download_attempts
        or task.error_code
        or qa_history
    )
    if not has_artifact:
        raise HTTPException(status_code=404, detail="Task artifacts not found")

    manifest = render_bundle_manifest(task, transcript, visual_index)
    filename = manifest_filename(task.id, task.title)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}-manifest.json"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return Response(json.dumps(manifest, ensure_ascii=False, indent=2), media_type="application/json; charset=utf-8", headers=headers)


@app.get("/api/tasks/{task_id}/exports/bundle")
def api_export_bundle(task_id: str) -> Response:
    try:
        task = get_task(task_id)
        note = read_note(task_id)
        transcript = read_transcript(task_id)
        visual_index = read_visual_index(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc

    diagnostics = render_diagnostics_markdown(task)
    audit_report = render_task_audit_markdown(task)
    visual_windows = render_visual_windows_markdown(task)
    qa_history = read_task_qa_history(task.id)
    qa_report = render_qa_history_markdown(task, qa_history)
    manifest = render_bundle_manifest(task, transcript, visual_index)
    resource_inventory = read_resource_inventory(task)
    page_preflight = read_page_preflight_report(task)
    generated_subtitles = "" if task.subtitle_path else render_transcript_srt(transcript)
    has_artifact = bool(
        note.strip()
        or transcript.get("segments")
        or visual_index.get("windows")
        or task.frame_grids
        or task.subtitle_path
        or task_media_file_exists(task)
        or task.download_attempts
        or task.error_code
        or qa_history
    )
    if not has_artifact:
        raise HTTPException(status_code=404, detail="Task artifacts not found")

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("audit.md", audit_report)
        archive.writestr("diagnostics.md", diagnostics)
        archive.writestr("visual_windows.md", visual_windows)
        if qa_history:
            archive.writestr("qa.md", qa_report)
            archive.writestr(QA_HISTORY_FILE, json.dumps({"schema_version": 1, "items": qa_history}, ensure_ascii=False, indent=2))
        if note.strip():
            archive.writestr("note.md", note)
        archive.writestr("task.json", json.dumps(task.model_dump(mode="json"), ensure_ascii=False, indent=2))
        archive.writestr("transcript.json", json.dumps(transcript, ensure_ascii=False, indent=2))
        archive.writestr("visual_index.json", json.dumps(visual_index, ensure_ascii=False, indent=2))
        if resource_inventory:
            archive.writestr("resource_inventory.json", json.dumps(resource_inventory, ensure_ascii=False, indent=2))
        if page_preflight:
            archive.writestr("page_preflight_report.json", json.dumps(page_preflight, ensure_ascii=False, indent=2))
        if task.subtitle_path:
            _write_file_if_exists(archive, task.subtitle_path, f"subtitles/{Path(task.subtitle_path).name}")
        elif generated_subtitles:
            archive.writestr("subtitles/generated-transcript.srt", generated_subtitles)
        if task.summary_diagnostics:
            archive.writestr("summary_diagnostics.json", json.dumps(task.summary_diagnostics, ensure_ascii=False, indent=2))
        for index, grid in enumerate(task.frame_grids):
            filename = Path(grid.path).name or f"grid_{index:03d}.jpg"
            _write_file_if_exists(archive, grid.path, f"grids/{filename}")

    filename = bundle_filename(task.id, task.title)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}.zip"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return Response(buffer.getvalue(), media_type="application/zip", headers=headers)


@app.get("/api/tasks/{task_id}/exports/diagnostics")
def api_export_diagnostics(task_id: str) -> PlainTextResponse:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    report = render_diagnostics_markdown(task)
    if not report.strip():
        raise HTTPException(status_code=404, detail="Diagnostics not found")
    filename = diagnostics_filename(task.id, task.title)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}-diagnostics.md"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return PlainTextResponse(report, media_type="text/markdown; charset=utf-8", headers=headers)


@app.get("/api/tasks/{task_id}/exports/resource-inventory")
def api_export_resource_inventory(task_id: str) -> Response:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    inventory = read_resource_inventory(task)
    if not inventory:
        raise HTTPException(status_code=404, detail="Resource inventory not found")
    filename = evidence_json_filename(task.id, task.title, "resource-inventory")
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}-resource-inventory.json"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return Response(json.dumps(inventory, ensure_ascii=False, indent=2), media_type="application/json; charset=utf-8", headers=headers)


@app.get("/api/tasks/{task_id}/exports/page-preflight-report")
def api_export_page_preflight_report(task_id: str) -> Response:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    report = read_page_preflight_report(task)
    if not report:
        raise HTTPException(status_code=404, detail="Page preflight report not found")
    filename = evidence_json_filename(task.id, task.title, "page-preflight-report")
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}-page-preflight-report.json"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return Response(json.dumps(report, ensure_ascii=False, indent=2), media_type="application/json; charset=utf-8", headers=headers)


@app.get("/api/tasks/{task_id}/exports/audit")
def api_export_audit(task_id: str) -> PlainTextResponse:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    report = render_task_audit_markdown(task)
    if not report.strip():
        raise HTTPException(status_code=404, detail="Audit report not found")
    filename = audit_filename(task.id, task.title)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}-audit.md"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return PlainTextResponse(report, media_type="text/markdown; charset=utf-8", headers=headers)


@app.get("/api/tasks/{task_id}/exports/subtitles")
def api_export_subtitles(task_id: str) -> Response:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    path = Path(task.subtitle_path) if task.subtitle_path else None
    if path and path.is_file():
        suffix = path.suffix.lower() or ".srt"
        filename = subtitles_filename(task.id, task.title, suffix)
        headers = {
            "Content-Disposition": (
                f'attachment; filename="learnnote-{task.id}-subtitles{suffix}"; '
                f"filename*=UTF-8''{quote(filename)}"
            )
        }
        media_type = {
            ".vtt": "text/vtt",
            ".srt": "application/x-subrip",
            ".ass": "text/plain",
            ".ssa": "text/plain",
        }.get(suffix, "text/plain")
        return FileResponse(path, media_type=media_type, headers=headers)
    try:
        transcript = read_transcript(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Subtitles not found") from exc
    rendered = render_transcript_srt(transcript)
    if not rendered:
        raise HTTPException(status_code=404, detail="Subtitles not found")
    suffix = ".srt"
    filename = subtitles_filename(task.id, task.title, suffix)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}-subtitles{suffix}"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return PlainTextResponse(rendered, media_type="application/x-subrip", headers=headers)


@app.get("/api/tasks/{task_id}/exports/media")
def api_export_media(task_id: str) -> FileResponse:
    task, path = _task_media_file(task_id)
    filename = media_download_filename(task, path)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{quote(filename)}"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return FileResponse(path, media_type=media_content_type(path), headers=headers)


@app.get("/api/tasks/{task_id}/exports/clips/{window_id}")
def api_export_visual_clip(task_id: str, window_id: str) -> FileResponse:
    task, path, resolved_id = _task_visual_clip_file(task_id, window_id)
    filename = clip_filename(task.id, task.title, resolved_id)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}-{resolved_id}.mp4"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return FileResponse(path, media_type="video/mp4", headers=headers)


def _task_subtitle_file(task_id: str) -> tuple[TaskRecord, Path]:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    if not task.subtitle_path:
        raise HTTPException(status_code=404, detail="Subtitles not found")
    path = Path(task.subtitle_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Subtitles not found")
    return task, path


def _task_media_file(task_id: str) -> tuple[TaskRecord, Path]:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    path = task_media_path(task)
    if not path:
        raise HTTPException(status_code=404, detail="Media not found")
    return task, path


def _task_visual_clip_range(task: TaskRecord, window_id: str) -> tuple[str, float, float]:
    target = (window_id or "").strip().lower()
    windows = list(task.visual_windows or [])
    if windows:
        for index, window in enumerate(windows, start=1):
            current_id = str(window.id or f"W{index:03d}")
            if current_id.lower() == target:
                return current_id, float(window.start or 0), float(window.end or 0)
    for index, grid in enumerate(task.frame_grids or [], start=1):
        current_id = f"W{index:03d}"
        if current_id.lower() == target:
            return current_id, float(grid.start or 0), float(grid.end or 0)
    raise HTTPException(status_code=404, detail={"code": "visual_window_not_found", "message": "Visual window not found"})


def _task_visual_clip_file(task_id: str, window_id: str) -> tuple[TaskRecord, Path, str]:
    task, media_path = _task_media_file(task_id)
    resolved_id, start, end = _task_visual_clip_range(task, window_id)
    if end <= start:
        raise HTTPException(status_code=400, detail={"code": "invalid_visual_window", "message": "Visual window has no positive duration"})
    clips_dir = task_dir(task.id) / "clips"
    clip_path = clips_dir / f"{_FILENAME_RESERVED_RE.sub('_', resolved_id).strip(' ._') or 'window'}.mp4"
    if not clip_path.exists() or clip_path.stat().st_size <= 0:
        try:
            extract_video_clip(media_path, clip_path, start, end)
        except MediaProcessingError as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "clip_export_failed",
                    "message": str(exc),
                    "window_id": resolved_id,
                    "start": start,
                    "end": end,
                },
            ) from exc
    return task, clip_path, resolved_id


@app.get("/api/tasks/{task_id}/media")
def api_preview_media(task_id: str) -> FileResponse:
    task, path = _task_media_file(task_id)
    filename = media_download_filename(task, path)
    headers = {
        "Content-Disposition": (
            f'inline; filename="{quote(filename)}"; '
            f"filename*=UTF-8''{quote(filename)}"
        ),
        "Cache-Control": "private, max-age=60",
    }
    return FileResponse(path, media_type=media_content_type(path), headers=headers)


@app.get("/api/tasks/{task_id}/assets/{filename}")
def api_asset(task_id: str, filename: str) -> FileResponse:
    path = task_dir(task_id) / "grids" / Path(filename).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(path)


@app.get("/api/tasks/{task_id}/frames/{filename}")
def api_original_frame(task_id: str, filename: str) -> FileResponse:
    path = task_dir(task_id) / "frames" / Path(filename).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(path, media_type="image/jpeg")
