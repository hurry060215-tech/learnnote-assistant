from __future__ import annotations

from io import BytesIO
import json
import re
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import DATA_DIR, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, STATIC_DIR, UPLOAD_DIR, WEB_DIR, ensure_dirs
from .downloader import effective_resource_kind, preflight_media_resource, rank_media_candidates
from .media import probe_duration
from .models import CurrentPageTaskRequest, MediaPreflightRequest, MediaPreflightResult, PagePreflightRequest, TaskOptions, TaskRecord
from .processor import process_current_page_task, process_local_video_task, read_note, read_transcript, read_visual_index
from .runtime import ffmpeg_bin, ffprobe_bin
from .storage import create_task, get_task, list_tasks, task_dir, update_task
from .summarizer import visual_window_review_question_lines

ensure_dirs()

app = FastAPI(title="LearnNote Assistant", version="0.1.0")
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
async def enforce_trusted_write_origin(request: Request, call_next):
    origin = (request.headers.get("origin") or "").strip()
    if request.method.upper() in WRITE_METHODS and request.url.path.startswith("/api/") and origin and not TRUSTED_BROWSER_ORIGIN_RE.fullmatch(origin):
        return Response("Forbidden origin", status_code=403)
    return await call_next(request)

app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")
app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")


_FILENAME_RESERVED_RE = re.compile(r'[\\/:*?"<>|\r\n]+')
LOCAL_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".flv", ".avi"}
LOCAL_VIDEO_MIME_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/x-m4v": ".m4v",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/webm": ".webm",
    "video/x-flv": ".flv",
    "video/avi": ".avi",
    "video/x-msvideo": ".avi",
}
LOCAL_UPLOAD_CHUNK_SIZE = 1024 * 1024


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
                "message": "本地视频仅支持 mp4、m4v、mov、mkv、webm、flv、avi。",
            },
        )
    stem = Path(safe_name).stem[:120].strip(" ._") or "local-video"
    return f"{stem}{suffix}"


def local_upload_error(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def validate_local_upload_file(path: Path) -> None:
    if not path.exists() or path.stat().st_size <= 0:
        raise local_upload_error("empty_local_file", "本地视频文件为空，请重新选择有效的视频文件。")
    if ffprobe_bin() or ffmpeg_bin():
        duration = probe_duration(path)
        if duration <= 0:
            raise local_upload_error("invalid_local_video", "无法读取本地视频时长，请确认文件不是空壳或损坏的视频。")


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


def diagnostics_filename(task_id: str, title: str) -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    return f"{stem}-diagnostics.md"


def visual_windows_filename(task_id: str, title: str) -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    return f"{stem}-visual-windows.md"


def subtitles_filename(task_id: str, title: str, suffix: str = ".srt") -> str:
    stem = _FILENAME_RESERVED_RE.sub("_", title or "").strip(" ._")
    stem = stem[:120] or f"learnnote-{task_id}"
    suffix = suffix if suffix.lower() in {".srt", ".vtt", ".ass", ".ssa"} else ".srt"
    return f"{stem}-subtitles{suffix}"


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


def _format_cookie_summary(summary: dict) -> list[str]:
    if not summary or not summary.get("total"):
        return ["- Cookie：未同步或未匹配到当前页/媒体域 Cookie"]
    domains = summary.get("domains") or {}
    domain_text = ", ".join(f"{domain} ({count})" for domain, count in sorted(domains.items())) or "-"
    return [
        f"- Cookie 总数：{summary.get('total', 0)}",
        f"- Cookie 域：{domain_text}",
        f"- Secure / HttpOnly：{summary.get('secure_count', 0)} / {summary.get('http_only_count', 0)}",
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


def _bundle_grid_ref(path_value: str, fallback_url: str = "") -> str:
    if path_value:
        filename = Path(path_value).name
        if filename:
            return f"grids/{filename}"
    return fallback_url or "-"


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
    lines = [
        "# LearnNote 画面切片索引",
        "",
        f"- 任务：{task.title}",
        f"- ID：{task.id}",
        f"- 页面：{task.page_url or '-'}",
        "- 说明：本索引对应资料包 `grids/` 目录中的网格图，可和 `transcript.json`、`visual_index.json` 交叉回看。",
        "",
    ]

    if task.visual_windows:
        for index, window in enumerate(task.visual_windows, start=1):
            label = window.id or f"W{index:03d}"
            grid_ref = _bundle_grid_ref(window.grid_path, window.grid_url)
            lines.extend([
                f"## {label} `{_format_timestamp(window.start)} - {_format_timestamp(window.end)}`",
                f"- 画面网格：{grid_ref}",
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
                f"- 帧数：{grid.frame_count}",
                f"- 帧时间：{', '.join(_format_timestamp(value) for value in grid.frame_timestamps) or '-'}",
                "",
            ])
        return "\n".join(lines).rstrip() + "\n"

    lines.append("- 暂无画面切片。")
    return "\n".join(lines) + "\n"


def render_bundle_manifest(task: TaskRecord, transcript: dict, visual_index: dict) -> dict:
    selected = task.selected_resource
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
    request_header_names = sorted((selected.request_headers or {}).keys()) if selected else []
    response_header_names = sorted((selected.headers or {}).keys()) if selected else []
    grid_entries = [
        f"grids/{Path(grid.path).name}"
        for grid in task.frame_grids
        if Path(grid.path).name
    ]

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
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "error_code": task.error_code,
            "error_detail": task.error_detail,
        },
        "options": options_payload,
        "source": {
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
                }
                for attempt in task.download_attempts
            ],
            "drm_detected": task.drm_detected,
            "drm_signal_count": len(task.drm_signals),
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
        "artifacts": {
            "note": "note.md" if task.note_path else "",
            "subtitles": f"subtitles/{Path(task.subtitle_path).name}" if task.subtitle_path else "",
            "diagnostics": "diagnostics.md",
            "visual_windows": "visual_windows.md" if task.visual_windows or task.frame_grids else "",
            "task": "task.json",
            "transcript": "transcript.json",
            "visual_index": "visual_index.json",
            "summary_diagnostics": "summary_diagnostics.json" if task.summary_diagnostics else "",
            "media_available": bool(task.media_path),
            "grid_entries": grid_entries,
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


def diagnostic_recovery_profile(task: TaskRecord) -> dict:
    codes = _task_failure_codes(task)
    selected = task.selected_resource
    selected_kind = selected.kind if selected else ""
    selected_source = selected.source if selected else ""
    selected_url = selected.resolved_url or selected.url if selected else ""
    latest_attempt = task.download_attempts[-1] if task.download_attempts else None
    is_chaoxing = _is_chaoxing_task(task)
    boundary_notes: list[str] = []
    primary_code = task.error_code or (latest_attempt.code if latest_attempt else "")

    if "drm_or_encrypted" in codes or task.drm_detected or selected_kind == "blob":
        primary_code = "drm_or_encrypted"
        diagnosis = "页面没有暴露可还原的直接媒体资源，或触发了 DRM/EME 边界。"
        confidence = "high" if task.drm_detected or selected_kind == "blob" else "medium"
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
    elif task.mode == "download_only" and task.media_path:
        primary_code = "download_ready"
        diagnosis = "视频已保存到本地，当前任务按下载模式停止在媒体产物。"
        confidence = "high"
        severity = "ok"
        next_action = "continue_from_media"
    else:
        primary_code = primary_code or ""
        diagnosis = "任务仍可继续按阶段审计检查媒体、转写、切片和总结产物。"
        confidence = "medium"
        severity = "ok"
        next_action = "inspect_audit"

    if is_chaoxing:
        boundary_notes.append("学习通/超星第一版只复用当前页面暴露的真实媒体 URL、Referer 和 Cookie，不刷课、不伪造学习进度、不自动答题。")
    if "drm_or_encrypted" in codes or task.drm_detected or selected_kind == "blob":
        boundary_notes.append("不会录制、破解或绕过 DRM/EME；blob 只有在扩展捕获到真实 manifest/媒体请求时才可直取。")
    if selected and selected.request_headers:
        boundary_notes.append(f"已捕获可复用请求头名：{_safe_header_names(selected.request_headers)}；不会保存 Cookie 或 Authorization 值。")
    if selected and _has_range_header(selected.request_headers):
        boundary_notes.append("Range 请求只作为播放证据，正式下载会去掉 Range，避免只保存片段。")
    if not boundary_notes:
        boundary_notes.append("当前页直取失败时，本地视频上传会复用同一套转写、切片和图文总结管线。")

    return {
        "code": primary_code,
        "diagnosis": diagnosis,
        "severity": severity,
        "confidence": confidence,
        "next_action": next_action,
        "is_chaoxing": is_chaoxing,
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
    has_media = bool(task.media_path)
    has_transcript = bool(task.transcript_path)
    has_visuals = bool(task.visual_windows or task.frame_grids or diagnostics.get("frame_grid_count"))
    has_note = bool(task.note_path)
    visual_disabled = task.options.visual_understanding is False or is_page_text
    selected_kind = selected.kind if selected else ""
    selected_source = selected.source if selected else ""
    selected_match = selected.playback_match if selected else ""
    transcript_value = (
        "download-only route"
        if is_download_only
        else (
            "transcript ready"
            if has_transcript
            else ("browser/page text fallback" if is_page_text and has_note else task.phase or "waiting")
        )
    )
    transcript_detail = (
        "media saved; rerun from media to transcribe"
        if is_download_only
        else ("timestamped transcript is available" if has_transcript else (task.summary_warning or "subtitle first, ASR fallback"))
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
        else (task.summary_warning or f"{task.options.note_style} / {task.options.summary_depth}")
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
            "state": _audit_gate_state(task, has_transcript or (is_page_text and has_note), skipped=is_download_only),
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

    has_visual_slices = bool(task.frame_grids or task.visual_windows)
    media_available = bool(task.media_path)
    is_download_only = task.mode == "download_only"
    rerun_ready = media_available and not has_visual_slices
    if rerun_ready:
        suggested_next_step = "rerun_from_media"
    elif has_visual_slices:
        suggested_next_step = "review_visual_windows"
    elif media_available:
        suggested_next_step = "inspect_media"
    else:
        suggested_next_step = "download_media"

    return {
        "media_available": media_available,
        "media_path_recorded": task.media_path,
        "browser_subtitle_count": browser_subtitle_count,
        "browser_subtitle_span_seconds": round(browser_subtitle_span, 3),
        "download_attempt_count": len(task.download_attempts),
        "selected_resource_url": task.selected_resource.url if task.selected_resource else "",
        "selected_resource_kind": task.selected_resource.kind if task.selected_resource else "",
        "frame_grid_count": len(task.frame_grids),
        "visual_window_count": len(task.visual_windows),
        "has_visual_slices": has_visual_slices,
        "download_only": is_download_only,
        "rerun_from_media_ready": rerun_ready,
        "suggested_next_step": suggested_next_step,
    }


def task_payload(task: TaskRecord) -> dict:
    payload = task.model_dump(mode="json")
    payload["audit"] = task_audit_summary(task)
    payload["recovery"] = diagnostic_recovery_profile(task)
    payload["reuse"] = task_reuse_evidence(task)
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


def page_preflight_report(request: PagePreflightRequest) -> dict:
    ranked = rank_media_candidates(request.resources)
    probed = 0
    downloadable_count = 0
    selected_url = ""
    candidates = []
    direct_candidate_count = sum(1 for item in ranked if effective_resource_kind(item) in {"video", "hls", "dash"})
    has_drm_boundary = request.drm_detected or any(effective_resource_kind(item) == "blob" for item in request.resources)

    for index, candidate in enumerate(ranked, start=1):
        if probed < request.probe_limit:
            result = preflight_media_resource(candidate, request.cookies, request.page_url)
            probed += 1
            resource = resource_with_preflight_result(candidate, result)
            if result.downloadable:
                downloadable_count += 1
                if not selected_url:
                    selected_url = resource.url
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

    if selected_url:
        code = ""
        message = f"整页预检通过：{downloadable_count} 个候选可访问，默认选择排序最靠前的可下载资源。"
    elif has_drm_boundary and not direct_candidate_count:
        code = "drm_or_encrypted"
        message = "页面只暴露 blob/DRM 播放线索，没有可交给后端下载的 mp4、m3u8 或 mpd。"
    elif ranked:
        code = "download_forbidden"
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
        "candidates": candidates,
    }


def render_diagnostics_markdown(task: TaskRecord) -> str:
    selected = task.selected_resource
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
    else:
        lines.append("- 未选择直接媒体资源，可能使用页面解析或 yt-dlp fallback。")

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
            f"- 送入视觉图片：{task.summary_diagnostics.get('vision_image_count', '-')}/{task.summary_diagnostics.get('vision_grid_count', '-')}",
            f"- 视觉调用状态：{task.summary_diagnostics.get('vision_call_status', '-')}",
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


@app.get("/health")
def health() -> dict:
    ffmpeg = ffmpeg_bin()
    ffprobe = ffprobe_bin()
    duration_probe = "ffprobe" if ffprobe else "ffmpeg" if ffmpeg else ""
    return {
        "ok": True,
        "ffmpeg": bool(ffmpeg),
        "ffmpeg_path": ffmpeg or "",
        "ffprobe": bool(ffprobe),
        "ffprobe_path": ffprobe or "",
        "duration_probe": duration_probe,
        "duration_probe_available": bool(duration_probe),
        "ffprobe_optional": bool(ffmpeg and not ffprobe),
        "vision_model_configured": bool(LLM_API_KEY),
        "default_llm_model": LLM_MODEL,
        "default_llm_base_url": LLM_BASE_URL,
    }


@app.post("/api/tasks/from-current-page")
def create_from_current_page(request: CurrentPageTaskRequest, background_tasks: BackgroundTasks) -> dict:
    source_type = "page_text" if request.mode == "page_text" else "current_page"
    task = create_task(source_type=source_type, title=request.title or request.page_url, page_url=request.page_url, options=request.options, mode=request.mode)
    if request.browser_subtitles:
        task = update_task(task.id, browser_subtitles=request.browser_subtitles)
    background_tasks.add_task(process_current_page_task, task.id, request)
    return {"task_id": task.id, "task": task}


@app.post("/api/media/preflight")
def api_media_preflight(request: MediaPreflightRequest) -> dict:
    result = preflight_media_resource(request.resource, request.cookies, request.page_url)
    return {"preflight": result}


@app.post("/api/media/preflight-current-page")
def api_page_media_preflight(request: PagePreflightRequest) -> dict:
    return {"report": page_preflight_report(request)}


@app.post("/api/tasks/from-local")
async def create_from_local(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(""),
    options: str = Form("{}"),
) -> dict:
    safe_name = local_upload_filename(file.filename, file.content_type)
    try:
        parsed_options = TaskOptions.model_validate(json.loads(options or "{}"))
    except Exception:
        parsed_options = TaskOptions()
    pending_path = UPLOAD_DIR / f"pending_{uuid4().hex}_{safe_name}"
    try:
        with pending_path.open("wb") as output:
            while True:
                chunk = await file.read(LOCAL_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
        validate_local_upload_file(pending_path)
    except HTTPException:
        pending_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        pending_path.unlink(missing_ok=True)
        raise local_upload_error("local_upload_failed", f"保存本地视频失败：{exc}", status_code=500) from exc

    task = create_task(source_type="local", title=title or safe_name, options=parsed_options, mode="local")
    upload_path = UPLOAD_DIR / f"{task.id}_{safe_name}"
    pending_path.replace(upload_path)
    background_tasks.add_task(process_local_video_task, task.id, upload_path, title or safe_name, parsed_options)
    return {"task_id": task.id, "task": task}


@app.post("/api/tasks/{task_id}/rerun-from-media")
def create_from_existing_media(
    task_id: str,
    background_tasks: BackgroundTasks,
    options: TaskOptions | None = Body(default=None),
) -> dict:
    try:
        source = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc

    if not source.media_path:
        raise HTTPException(status_code=404, detail={"code": "media_not_found", "message": "Task has no downloaded media"})
    media_path = Path(source.media_path)
    if not media_path.exists():
        raise HTTPException(status_code=404, detail={"code": "media_not_found", "message": "Downloaded media file is missing"})

    parsed_options = options or source.options or TaskOptions()
    task = create_task(
        source_type="local",
        title=source.title or f"Media from {source.id}",
        page_url=source.page_url,
        options=parsed_options,
        mode="rerun_from_media",
    )
    task = update_task(
        task.id,
        selected_resource=source.selected_resource,
        download_attempts=source.download_attempts,
        active_video=source.active_video,
        drm_detected=source.drm_detected,
        drm_signals=source.drm_signals,
        message="Queued from downloaded media",
    )
    background_tasks.add_task(process_local_video_task, task.id, media_path, task.title, parsed_options, source.page_url, source.browser_subtitles)
    return {"task_id": task.id, "task": task, "source_task_id": source.id}


@app.get("/api/tasks")
def api_list_tasks() -> dict:
    return {"tasks": [task_payload(task) for task in list_tasks()]}


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


@app.get("/api/tasks/{task_id}/exports/manifest")
def api_export_manifest(task_id: str) -> Response:
    try:
        task = get_task(task_id)
        transcript = read_transcript(task_id)
        visual_index = read_visual_index(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc

    has_artifact = bool(
        task.media_path
        or task.note_path
        or task.subtitle_path
        or task.transcript_path
        or task.visual_windows
        or task.frame_grids
        or task.download_attempts
        or task.error_code
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
    visual_windows = render_visual_windows_markdown(task)
    manifest = render_bundle_manifest(task, transcript, visual_index)
    has_artifact = bool(
        note.strip()
        or transcript.get("segments")
        or visual_index.get("windows")
        or task.frame_grids
        or task.subtitle_path
        or task.media_path
        or task.download_attempts
        or task.error_code
    )
    if not has_artifact:
        raise HTTPException(status_code=404, detail="Task artifacts not found")

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("diagnostics.md", diagnostics)
        archive.writestr("visual_windows.md", visual_windows)
        if note.strip():
            archive.writestr("note.md", note)
        archive.writestr("task.json", json.dumps(task.model_dump(mode="json"), ensure_ascii=False, indent=2))
        archive.writestr("transcript.json", json.dumps(transcript, ensure_ascii=False, indent=2))
        archive.writestr("visual_index.json", json.dumps(visual_index, ensure_ascii=False, indent=2))
        if task.subtitle_path:
            _write_file_if_exists(archive, task.subtitle_path, f"subtitles/{Path(task.subtitle_path).name}")
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


@app.get("/api/tasks/{task_id}/exports/subtitles")
def api_export_subtitles(task_id: str) -> FileResponse:
    task, path = _task_subtitle_file(task_id)
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


@app.get("/api/tasks/{task_id}/exports/media")
def api_export_media(task_id: str) -> FileResponse:
    task, path = _task_media_file(task_id)
    filename = media_filename(task.id, task.title)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}.mp4"; '
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
    if not task.media_path:
        raise HTTPException(status_code=404, detail="Media not found")
    path = Path(task.media_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    return task, path


@app.get("/api/tasks/{task_id}/media")
def api_preview_media(task_id: str) -> FileResponse:
    task, path = _task_media_file(task_id)
    filename = media_filename(task.id, task.title)
    headers = {
        "Content-Disposition": (
            f'inline; filename="learnnote-{task.id}.mp4"; '
            f"filename*=UTF-8''{quote(filename)}"
        ),
        "Cache-Control": "private, max-age=60",
    }
    return FileResponse(path, media_type="video/mp4", headers=headers)


@app.get("/api/tasks/{task_id}/assets/{filename}")
def api_asset(task_id: str, filename: str) -> FileResponse:
    path = task_dir(task_id) / "grids" / Path(filename).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(path)
