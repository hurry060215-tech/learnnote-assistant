from __future__ import annotations

from io import BytesIO
import json
import re
from zipfile import ZIP_DEFLATED, ZipFile
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import DATA_DIR, STATIC_DIR, UPLOAD_DIR, WEB_DIR, ensure_dirs
from .downloader import preflight_media_resource
from .models import CurrentPageTaskRequest, MediaPreflightRequest, TaskOptions, TaskRecord
from .processor import process_current_page_task, process_local_video_task, read_note, read_transcript, read_visual_index
from .runtime import ffmpeg_bin, ffprobe_bin
from .storage import create_task, get_task, list_tasks, task_dir, update_task

ensure_dirs()

app = FastAPI(title="LearnNote Assistant", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome-extension://[a-z]+|moz-extension://[a-z0-9-]+|https?://(localhost|127\.0\.0\.1)(:\d+)?)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
                f"- 帧数：{window.frame_count}",
                f"- 帧时间：{', '.join(_format_timestamp(value) for value in window.frame_timestamps) or '-'}",
            ])
            if window.transcript_excerpt.strip():
                lines.extend(["", window.transcript_excerpt.strip()])
            else:
                lines.append("- 字幕摘录：-")
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


def diagnostic_recovery_steps(task: TaskRecord) -> list[str]:
    codes = {task.error_code} if task.error_code else set()
    codes.update(attempt.code for attempt in task.download_attempts if attempt.code)
    steps: list[str] = []

    def add(text: str) -> None:
        if text and text not in steps:
            steps.append(text)

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
    if len(task.download_attempts) > 1:
        add(f"后端已尝试 {len(task.download_attempts)} 条路线；查看上方下载尝试，优先处理第一个失败的直接媒体候选。")
    if task.status == "failed" and task.note_path:
        add("视频直取失败但已有兜底笔记时，可先导出 Markdown/资料包复习，再根据诊断重新尝试直取。")
    if not steps:
        add("如果任务未完成，先查看下载尝试的错误码；当前页直取失败时可以改用本地视频入口走同一套切片总结。")
    return steps


def render_diagnostics_markdown(task: TaskRecord) -> str:
    selected = task.selected_resource
    lines = [
        "# LearnNote 任务诊断报告",
        "",
        f"- 任务：{task.title}",
        f"- ID：{task.id}",
        f"- 状态：{task.status} / {task.phase} / {task.progress}%",
        f"- 来源：{task.source_type}",
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
            f"- 播放匹配：{selected.playback_match or '-'}",
            f"- Blob：{selected.blob_url or '-'}",
            f"- Frame：{selected.frame_url or selected.frame_id or '-'}",
            f"- HTTP：{selected.status_code or '-'}",
            f"- MIME：{selected.mime or '-'}",
            f"- 大小：{_format_bytes(selected.content_length)}",
            f"- 可复用请求头名：{_safe_header_names(selected.request_headers)}",
        ])
    else:
        lines.append("- 未选择直接媒体资源，可能使用页面解析或 yt-dlp fallback。")

    lines.extend(["", "## 下载尝试"])
    if task.download_attempts:
        for index, attempt in enumerate(task.download_attempts, start=1):
            lines.extend([
                f"### {index}. {attempt.strategy} · {attempt.status}",
                f"- URL：{attempt.url or '-'}",
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

    lines.extend(["", "## 下一步建议"])
    lines.extend(f"- {step}" for step in diagnostic_recovery_steps(task))

    lines.extend([
        "",
        "## 处理产物",
        f"- 媒体：{task.media_path or '-'}",
        f"- 音频：{task.audio_path or '-'}",
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
            f"- 省略网格：{task.summary_diagnostics.get('omitted_frame_grid_count', '-')}",
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
    return {
        "ok": True,
        "ffmpeg": bool(ffmpeg),
        "ffmpeg_path": ffmpeg or "",
        "ffprobe": bool(ffprobe),
        "ffprobe_path": ffprobe or "",
    }


@app.post("/api/tasks/from-current-page")
def create_from_current_page(request: CurrentPageTaskRequest, background_tasks: BackgroundTasks) -> dict:
    source_type = "page_text" if request.mode == "page_text" else "current_page"
    task = create_task(source_type=source_type, title=request.title or request.page_url, page_url=request.page_url, options=request.options)
    background_tasks.add_task(process_current_page_task, task.id, request)
    return {"task_id": task.id, "task": task}


@app.post("/api/media/preflight")
def api_media_preflight(request: MediaPreflightRequest) -> dict:
    result = preflight_media_resource(request.resource, request.cookies, request.page_url)
    return {"preflight": result}


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
    task = create_task(source_type="local", title=title or safe_name, options=parsed_options)
    upload_path = UPLOAD_DIR / f"{task.id}_{safe_name}"
    with upload_path.open("wb") as output:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
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
    background_tasks.add_task(process_local_video_task, task.id, media_path, task.title, parsed_options, source.page_url)
    return {"task_id": task.id, "task": task, "source_task_id": source.id}


@app.get("/api/tasks")
def api_list_tasks() -> dict:
    return {"tasks": list_tasks()}


@app.get("/api/tasks/{task_id}")
def api_get_task(task_id: str) -> dict:
    try:
        return {"task": get_task(task_id)}
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
    has_artifact = bool(
        note.strip()
        or transcript.get("segments")
        or visual_index.get("windows")
        or task.frame_grids
        or task.media_path
        or task.download_attempts
        or task.error_code
    )
    if not has_artifact:
        raise HTTPException(status_code=404, detail="Task artifacts not found")

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.md", diagnostics)
        archive.writestr("visual_windows.md", visual_windows)
        if note.strip():
            archive.writestr("note.md", note)
        archive.writestr("task.json", json.dumps(task.model_dump(mode="json"), ensure_ascii=False, indent=2))
        archive.writestr("transcript.json", json.dumps(transcript, ensure_ascii=False, indent=2))
        archive.writestr("visual_index.json", json.dumps(visual_index, ensure_ascii=False, indent=2))
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


@app.get("/api/tasks/{task_id}/exports/media")
def api_export_media(task_id: str) -> FileResponse:
    try:
        task = get_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    if not task.media_path:
        raise HTTPException(status_code=404, detail="Media not found")
    path = Path(task.media_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    filename = media_filename(task.id, task.title)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="learnnote-{task.id}.mp4"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return FileResponse(path, media_type="video/mp4", headers=headers)


@app.get("/api/tasks/{task_id}/assets/{filename}")
def api_asset(task_id: str, filename: str) -> FileResponse:
    path = task_dir(task_id) / "grids" / Path(filename).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(path)
