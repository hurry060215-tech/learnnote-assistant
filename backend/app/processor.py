from __future__ import annotations

import json
from pathlib import Path

from .downloader import DownloadError, MediaDownloader, classify_resource, infer_manifest_url_from_fragment
from .media import build_frame_grids, extract_audio, extract_frames, normalize_video
from .models import CurrentPageTaskRequest, DownloadAttempt, FrameGrid, ResourceCandidate, TaskOptions, TranscriptResult, VisualWindow
from .storage import get_task, save_task, task_dir, update_task, write_json
from .summarizer import MAX_VISION_GRIDS, build_visual_windows, summarize_page_text, summarize_with_diagnostics
from .transcriber import transcript_from_subtitle, transcribe_audio


SAFE_RESPONSE_HEADER_NAMES = {"content-type", "content-length", "content-range", "accept-ranges"}


def _fail(task_id: str, code: str, detail: str) -> None:
    update_task(
        task_id,
        status="failed",
        phase="failed",
        progress=100,
        error_code=code,
        error_detail=detail,
        message=detail,
    )


def _redacted_values(values: dict[str, str]) -> dict[str, str]:
    return {name: "<redacted>" for name in values}


def _safe_response_headers(headers: dict[str, str]) -> dict[str, str]:
    return {name: value for name, value in headers.items() if str(name).lower() in SAFE_RESPONSE_HEADER_NAMES}


def redacted_resource(resource: ResourceCandidate) -> ResourceCandidate:
    redacted = resource.model_copy(deep=True)
    redacted.headers = _safe_response_headers(redacted.headers)
    redacted.request_headers = _redacted_values(redacted.request_headers)
    return redacted


def redacted_request_dump(request: CurrentPageTaskRequest) -> dict:
    data = request.model_dump(mode="json")
    if data.get("options") and data["options"].get("llm_api_key"):
        data["options"]["llm_api_key"] = "<redacted>"
    for cookie in data.get("cookies", []):
        if "value" in cookie:
            cookie["value"] = "<redacted>"
    for resource in data.get("resources", []):
        resource["headers"] = _safe_response_headers(resource.get("headers") or {})
        resource["request_headers"] = _redacted_values(resource.get("request_headers") or {})
    return data


def has_downloadable_candidate(resources: list[ResourceCandidate]) -> bool:
    for resource in resources:
        kind = classify_resource(resource.url, resource.mime)
        if kind in {"video", "hls", "dash"}:
            return True
        if kind == "fragment" and infer_manifest_url_from_fragment(resource.url):
            return True
    return False


def drm_failure_message(request: CurrentPageTaskRequest) -> str:
    signals = request.drm_signals or []
    key_systems = sorted({signal.key_system for signal in signals if signal.key_system})
    init_types = sorted({signal.init_data_type for signal in signals if signal.init_data_type})
    details = []
    if key_systems:
        details.append(f"key system: {', '.join(key_systems[:3])}")
    if init_types:
        details.append(f"init data: {', '.join(init_types[:3])}")
    suffix = f"（{'；'.join(details)}）" if details else ""
    return f"页面触发了 EME/DRM 加密媒体信号{suffix}，且没有发现可直接下载的 mp4/m3u8/mpd；不会录制或绕过 DRM。"


def build_summary_diagnostics(
    task_id: str,
    title: str,
    page_url: str,
    options: TaskOptions,
    grids: list[FrameGrid],
    visual_windows: list[VisualWindow],
    summary_source: str,
    summary_warning: str,
) -> dict:
    eligible_grids = grids[:MAX_VISION_GRIDS]
    total_image_count = sum(1 for grid in grids if grid.path and Path(grid.path).is_file())
    eligible_image_count = sum(1 for grid in eligible_grids if grid.path and Path(grid.path).is_file())
    return {
        "task_id": task_id,
        "title": title,
        "page_url": page_url,
        "summary_source": summary_source,
        "summary_warning": summary_warning,
        "visual_understanding": bool(options.visual_understanding),
        "llm_model": options.llm_model or "",
        "llm_base_url": options.llm_base_url or "",
        "note_style": options.note_style,
        "summary_depth": options.summary_depth,
        "frame_grid_count": len(grids),
        "visual_window_count": len(visual_windows),
        "available_grid_image_count": total_image_count,
        "vision_grid_limit": MAX_VISION_GRIDS,
        "vision_grid_count": len(eligible_grids),
        "vision_image_count": eligible_image_count,
        "omitted_frame_grid_count": max(0, len(grids) - len(eligible_grids)),
        "used_vision_llm": summary_source == "vision-llm",
        "used_text_llm": summary_source == "text-llm",
        "used_local_template": summary_source == "local-template",
        "all_sent_grids_had_images": eligible_image_count == len(eligible_grids),
        "all_grids_had_images": total_image_count == len(grids),
        "window_ids": [window.id for window in visual_windows],
    }


def process_page_text_task(task_id: str, request: CurrentPageTaskRequest) -> None:
    try:
        update_task(task_id, status="running", phase="summarizing", progress=60, message="正在总结当前页面文本")
        note = summarize_page_text(request.title, request.page_url, request.page_text, request.options)
        note_path = task_dir(task_id) / "note.md"
        note_path.write_text(note, encoding="utf-8")
        update_task(task_id, status="success", phase="completed", progress=100, message="页面文本总结完成", note_path=str(note_path))
    except Exception as exc:
        _fail(task_id, "processing_failed", str(exc))


def process_current_page_task(task_id: str, request: CurrentPageTaskRequest) -> None:
    write_json(task_id, "request.json", redacted_request_dump(request))
    if request.mode == "page_text":
        process_page_text_task(task_id, request)
        return

    work_dir = task_dir(task_id)
    try:
        update_task(
            task_id,
            active_video=request.active_video,
            drm_detected=bool(request.drm_detected),
            drm_signals=request.drm_signals,
        )
        update_task(task_id, status="running", phase="downloading", progress=10, message="正在解析并下载当前页视频")
        if request.drm_detected and not has_downloadable_candidate(request.resources):
            message = drm_failure_message(request)
            update_task(
                task_id,
                download_attempts=[
                    DownloadAttempt(
                        strategy="eme-detected",
                        status="failed",
                        code="drm_or_encrypted",
                        message=message,
                    )
                ],
            )
            _fail(task_id, "drm_or_encrypted", message)
            return
        downloader = MediaDownloader(work_dir)
        media_path, selected = downloader.download(request.page_url, request.resources, request.cookies, request.title)
        if selected:
            update_task(task_id, selected_resource=redacted_resource(selected))
        subtitle_path = downloader.download_subtitle(request.resources, request.cookies, request.page_url, request.title)
        update_task(task_id, download_attempts=downloader.attempts)

        _process_video_file(
            task_id=task_id,
            input_path=media_path,
            title=request.title,
            page_url=request.page_url,
            options=request.options,
            subtitle_path=subtitle_path,
        )
    except DownloadError as exc:
        if "downloader" in locals():
            update_task(task_id, download_attempts=downloader.attempts)
        _fail(task_id, exc.code, exc.message)
    except Exception as exc:
        _fail(task_id, "processing_failed", str(exc))


def process_local_video_task(task_id: str, input_path: Path, title: str, options: TaskOptions) -> None:
    try:
        _process_video_file(task_id=task_id, input_path=input_path, title=title, page_url="", options=options)
    except Exception as exc:
        _fail(task_id, "processing_failed", str(exc))


def _process_video_file(
    task_id: str,
    input_path: Path,
    title: str,
    page_url: str,
    options: TaskOptions,
    subtitle_path: Path | None = None,
) -> None:
    work_dir = task_dir(task_id)
    update_task(task_id, status="running", phase="processing_video", progress=25, message="正在标准化视频")

    normalized = work_dir / "media.mp4"
    normalize_video(input_path, normalized)
    update_task(task_id, media_path=str(normalized))

    update_task(task_id, phase="processing_video", progress=38, message="正在提取音频")
    audio_path = work_dir / "audio.wav"
    extract_audio(normalized, audio_path)
    update_task(task_id, audio_path=str(audio_path))

    update_task(task_id, phase="transcribing", progress=52, message="正在转写音频")
    if subtitle_path:
        update_task(task_id, subtitle_path=str(subtitle_path), message="已检测到页面字幕，正在解析字幕")
        transcript = transcript_from_subtitle(subtitle_path)
        if not transcript.segments:
            transcript = transcribe_audio(audio_path, options.whisper_model)
    else:
        transcript = transcribe_audio(audio_path, options.whisper_model)
    transcript_path = work_dir / "transcript.json"
    transcript_path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
    update_task(task_id, transcript_path=str(transcript_path))

    grids = []
    if options.visual_understanding:
        update_task(task_id, phase="extracting_frames", progress=68, message="正在抽帧并生成画面网格")
        frame_dir = work_dir / "frames"
        grid_dir = work_dir / "grids"
        frames = extract_frames(normalized, frame_dir, max(1, options.frame_interval))
        grids = build_frame_grids(task_id, frames, grid_dir, max(1, options.grid_columns), max(1, options.grid_rows), max(1, options.frame_interval))

    visual_windows = build_visual_windows(transcript, grids)
    visual_index_path = write_json(
        task_id,
        "visual_index.json",
        {
            "task_id": task_id,
            "title": title,
            "page_url": page_url,
            "windows": [window.model_dump(mode="json") for window in visual_windows],
        },
    )

    record = get_task(task_id)
    record.frame_grids = grids
    record.visual_windows = visual_windows
    record.visual_index_path = str(visual_index_path)
    save_task(record)

    update_task(task_id, phase="summarizing", progress=84, message="正在生成 Markdown 笔记")
    note, summary_source, summary_warning = summarize_with_diagnostics(title, transcript, grids, options, page_url)
    summary_diagnostics = build_summary_diagnostics(
        task_id=task_id,
        title=title,
        page_url=page_url,
        options=options,
        grids=grids,
        visual_windows=visual_windows,
        summary_source=summary_source,
        summary_warning=summary_warning,
    )
    summary_diagnostics_path = write_json(task_id, "summary_diagnostics.json", summary_diagnostics)
    note_path = work_dir / "note.md"
    note_path.write_text(note, encoding="utf-8")

    update_task(
        task_id,
        status="success",
        phase="completed",
        progress=100,
        message="任务完成",
        note_path=str(note_path),
        summary_source=summary_source,
        summary_warning=summary_warning,
        summary_diagnostics_path=str(summary_diagnostics_path),
        summary_diagnostics=summary_diagnostics,
    )


def read_transcript(task_id: str) -> dict:
    record = get_task(task_id)
    if not record.transcript_path:
        return TranscriptResult().model_dump(mode="json")
    path = Path(record.transcript_path)
    if not path.is_file():
        return TranscriptResult().model_dump(mode="json")
    return json.loads(path.read_text(encoding="utf-8"))


def read_note(task_id: str) -> str:
    record = get_task(task_id)
    if not record.note_path:
        return ""
    path = Path(record.note_path)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def read_visual_index(task_id: str) -> dict:
    record = get_task(task_id)
    if record.visual_index_path:
        path = Path(record.visual_index_path)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return {
        "task_id": task_id,
        "title": record.title,
        "page_url": record.page_url,
        "windows": [window.model_dump(mode="json") for window in record.visual_windows],
    }
