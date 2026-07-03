from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from urllib.parse import urldefrag

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from .downloader import DownloadError, MediaDownloader, effective_resource_kind, infer_manifest_url_from_fragment
from .media import build_frame_grids, extract_audio, extract_embedded_subtitle, extract_frames, normalize_video
from .models import ActiveVideoInfo, BrowserSubtitleCue, CurrentPageTaskRequest, DownloadAttempt, FrameGrid, ResourceCandidate, TaskOptions, TranscriptResult, TranscriptSegment, VisualWindow
from .storage import get_task, save_task, task_dir, update_task, write_json
from .summarizer import MAX_GRIDS_PER_VISION_CALL, MAX_VISION_GRIDS, build_visual_windows, llm_base_host, llm_provider_name, summarize_page_text_with_diagnostics, summarize_with_diagnostics
from .transcriber import transcript_from_subtitle, transcribe_audio, transcribe_audio_openai_compatible


SAFE_RESPONSE_HEADER_NAMES = {"content-type", "content-disposition", "content-length", "content-range", "accept-ranges"}
REMOTE_ASR_TRANSCRIBERS = {"openai", "openai-compatible", "openai-compatible-asr", "groq", "groq-asr"}


@dataclass
class PageTextArtifacts:
    note_path: str = ""
    subtitle_path: str = ""
    transcript_path: str = ""
    created: bool = False
    summary_source: str = ""
    summary_warning: str = ""
    summary_diagnostics_path: str = ""
    summary_diagnostics: dict | None = None


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
    redacted.request_body = _redacted_values(redacted.request_body)
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
        resource["request_body"] = _redacted_values(resource.get("request_body") or {})
    return data


def has_downloadable_candidate(resources: list[ResourceCandidate]) -> bool:
    for resource in resources:
        kind = effective_resource_kind(resource)
        if kind in {"video", "hls", "dash"}:
            return True
        if kind == "fragment" and infer_manifest_url_from_fragment(resource.url):
            return True
    return False


def _canonical_media_url(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith("blob:"):
        return value
    return urldefrag(value)[0]


def _active_video_resource_match(active_video: ActiveVideoInfo, resource: ResourceCandidate) -> str:
    active_src = _canonical_media_url(active_video.src)
    if not active_src:
        return ""
    blob_url = _canonical_media_url(resource.blob_url)
    resource_urls = [
        _canonical_media_url(resource.url),
        _canonical_media_url(resource.resolved_url),
        blob_url,
    ]
    if active_src not in resource_urls:
        return ""
    return "blob-source" if active_src.startswith("blob:") or active_src == blob_url else "exact-src"


def enrich_resources_with_active_video(request: CurrentPageTaskRequest) -> list[ResourceCandidate]:
    active_video = request.active_video
    if not active_video:
        return request.resources
    enriched: list[ResourceCandidate] = []
    for resource in request.resources:
        item = resource.model_copy(deep=True)
        match = _active_video_resource_match(active_video, item)
        if match:
            item.is_main_video = True
            if not item.playback_match:
                item.playback_match = match
            if item.frame_id is None:
                item.frame_id = active_video.frame_id
            if item.current_time is None:
                item.current_time = active_video.current_time
            if item.duration is None and active_video.duration:
                item.duration = active_video.duration
            if item.width is None and active_video.width:
                item.width = active_video.width
            if item.height is None and active_video.height:
                item.height = active_video.height
        enriched.append(item)
    return enriched


def attempted_resource_candidate(resources: list[ResourceCandidate], attempts: list[DownloadAttempt]) -> ResourceCandidate | None:
    attempted_urls = [attempt.url for attempt in attempts if attempt.url]
    for url in attempted_urls:
        for resource in resources:
            if resource.url == url or resource.resolved_url == url:
                return resource
    for resource in resources:
        if effective_resource_kind(resource) in {"video", "hls", "dash"}:
            return resource
    return None


def transcript_from_browser_subtitles(segments: list[BrowserSubtitleCue]) -> TranscriptResult:
    cleaned: list[TranscriptSegment] = []
    seen: set[tuple[int, int, str]] = set()
    for cue in sorted(segments, key=lambda item: (item.start, item.end, item.text)):
        text = " ".join(str(cue.text or "").split())
        if not text:
            continue
        start = max(0.0, float(cue.start or 0))
        end = max(start, float(cue.end or start))
        key = (round(start * 1000), round(end * 1000), text)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(TranscriptSegment(start=start, end=end, text=text))
    return TranscriptResult(
        language="unknown",
        segments=cleaned,
        full_text="\n".join(segment.text for segment in cleaned),
        source="browser-subtitle",
    )


def has_downloadable_subtitle_candidate(resources: list[ResourceCandidate]) -> bool:
    for resource in resources or []:
        url = (resource.url or "").strip()
        if not url or url.startswith(("blob:", "data:", "chrome-extension:")):
            continue
        if effective_resource_kind(resource) == "subtitle":
            return True
    return False


def browser_subtitles_look_partial(segments: list[BrowserSubtitleCue], min_count: int = 8, min_span_seconds: float = 45.0) -> bool:
    cleaned: list[tuple[float, float, str]] = []
    for cue in segments or []:
        text = " ".join(str(cue.text or "").split())
        if not text:
            continue
        start = max(0.0, float(cue.start or 0))
        end = max(start, float(cue.end or start))
        cleaned.append((start, end, text))
    if not cleaned:
        return True
    if len(cleaned) >= min_count:
        return False
    span = max(end for _, end, _ in cleaned) - min(start for start, _, _ in cleaned)
    return span < min_span_seconds


def should_download_page_subtitle(request: CurrentPageTaskRequest) -> bool:
    if not request.browser_subtitles:
        return True
    return has_downloadable_subtitle_candidate(request.resources) and browser_subtitles_look_partial(request.browser_subtitles)


def _srt_timestamp(seconds: float) -> str:
    millis = round(max(0.0, seconds) * 1000)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def write_browser_subtitles_srt(task_id: str, transcript: TranscriptResult) -> str:
    if not transcript.segments:
        return ""
    path = task_dir(task_id) / "browser_subtitles.srt"
    blocks = []
    for index, segment in enumerate(transcript.segments, start=1):
        end = segment.end if segment.end > segment.start else segment.start + 0.001
        blocks.append(
            "\n".join([
                str(index),
                f"{_srt_timestamp(segment.start)} --> {_srt_timestamp(end)}",
                segment.text.strip(),
            ])
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return str(path)


def page_text_with_browser_subtitles(page_text: str, transcript: TranscriptResult) -> str:
    text = (page_text or "").strip()
    subtitle_text = (transcript.full_text or "").strip()
    if text and subtitle_text:
        return f"{text}\n\n--- 浏览器字幕 ---\n\n{subtitle_text}"
    return text or subtitle_text


def cookie_sync_summary(cookies: list) -> dict:
    domains: dict[str, int] = {}
    secure_count = 0
    http_only_count = 0
    partitioned_count = 0
    partition_keys: set[str] = set()
    for cookie in cookies or []:
        domain = (getattr(cookie, "domain", "") or "").strip() or "(no domain)"
        domains[domain] = domains.get(domain, 0) + 1
        if getattr(cookie, "secure", False):
            secure_count += 1
        if getattr(cookie, "httpOnly", False):
            http_only_count += 1
        partition_key = getattr(cookie, "partitionKey", None)
        if partition_key:
            partitioned_count += 1
            try:
                partition_keys.add(json.dumps(partition_key, sort_keys=True, ensure_ascii=False))
            except TypeError:
                partition_keys.add(str(partition_key))
    return {
        "total": sum(domains.values()),
        "domains": dict(sorted(domains.items())),
        "domain_count": len(domains),
        "secure_count": secure_count,
        "http_only_count": http_only_count,
        "partitioned_count": partitioned_count,
        "partition_key_count": len(partition_keys),
    }


def write_page_text_artifacts(task_id: str, request: CurrentPageTaskRequest, allow_empty: bool = True) -> PageTextArtifacts:
    transcript = transcript_from_browser_subtitles(request.browser_subtitles)
    page_text = page_text_with_browser_subtitles(request.page_text, transcript)
    if not allow_empty and not page_text.strip():
        return PageTextArtifacts()
    transcript_path = ""
    subtitle_path = ""
    if transcript.segments:
        subtitle_path = write_browser_subtitles_srt(task_id, transcript)
        transcript_path = str(write_json(task_id, "transcript.json", transcript.model_dump(mode="json")))
    note, summary_source, summary_warning = summarize_page_text_with_diagnostics(request.title, request.page_url, page_text, request.options)
    note_path = task_dir(task_id) / "note.md"
    note_path.write_text(note, encoding="utf-8")
    summary_diagnostics = build_summary_diagnostics(
        task_id=task_id,
        title=request.title,
        page_url=request.page_url,
        options=request.options,
        grids=[],
        visual_windows=[],
        summary_source=summary_source,
        summary_warning=summary_warning,
    )
    summary_diagnostics.update({
        "page_text_char_count": len((request.page_text or "").strip()),
        "browser_subtitle_count": len(transcript.segments),
        "combined_text_char_count": len(page_text),
        "used_page_text_fallback": True,
    })
    summary_diagnostics_path = write_json(task_id, "summary_diagnostics.json", summary_diagnostics)
    return PageTextArtifacts(
        note_path=str(note_path),
        subtitle_path=subtitle_path,
        transcript_path=transcript_path,
        created=True,
        summary_source=summary_source,
        summary_warning=summary_warning,
        summary_diagnostics_path=str(summary_diagnostics_path),
        summary_diagnostics=summary_diagnostics,
    )


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
    return f"页面触发了 EME/DRM 加密媒体信号{suffix}，且没有发现可直接下载的 mp4/FLV/m3u8/mpd；不会录制或绕过 DRM。"


def src_object_failure_message(request: CurrentPageTaskRequest) -> str:
    active = request.active_video
    stream_type = active.src_object_type if active and active.src_object_type else "MediaStream/srcObject"
    tracks = []
    if active and active.src_object_video_tracks:
        tracks.append(f"{active.src_object_video_tracks} video")
    if active and active.src_object_audio_tracks:
        tracks.append(f"{active.src_object_audio_tracks} audio")
    track_detail = f"（{', '.join(tracks)}）" if tracks else ""
    return f"当前 HTML5 播放器使用 {stream_type}{track_detail}，页面没有暴露可交给后端下载的 mp4/FLV/m3u8/mpd URL；不会录制标签页，请使用本地视频入口或页面文本兜底。"


def use_remote_asr(options: TaskOptions) -> bool:
    return str(options.transcriber or "").strip().lower() in REMOTE_ASR_TRANSCRIBERS


def transcribe_extracted_audio(audio_path: Path, options: TaskOptions) -> TranscriptResult:
    if use_remote_asr(options):
        return transcribe_audio_openai_compatible(audio_path, options)
    return transcribe_audio(audio_path, options.whisper_model)


def _warning_field(summary_warning: str, key: str) -> str:
    marker = f"{key}="
    if marker not in (summary_warning or ""):
        return ""
    value = (summary_warning or "").split(marker, 1)[1]
    return value.split("，", 1)[0].split(";", 1)[0].split("；", 1)[0].strip()


def _llm_failure_code(summary_source: str, summary_warning: str, configured: bool) -> str:
    if summary_source != "local-template" and not summary_warning:
        return ""
    if not configured:
        return "missing_api_key"
    code = _warning_field(summary_warning, "code")
    if code:
        return code
    if "missing_openai_sdk" in (summary_warning or ""):
        return "missing_openai_sdk"
    if summary_source == "local-template":
        return "llm_unavailable"
    return "partial_vision_failure"


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
    effective_llm_base_url = options.llm_base_url or LLM_BASE_URL
    effective_llm_model = options.llm_model or LLM_MODEL
    llm_configured = bool(options.llm_api_key or LLM_API_KEY)

    def window_id(index: int) -> str:
        if index < len(visual_windows) and visual_windows[index].id:
            return visual_windows[index].id
        return f"W{index + 1:03d}"

    eligible_window_ids = [window_id(index) for index in range(len(eligible_grids))]
    vision_image_window_ids = [
        window_id(index)
        for index, grid in enumerate(eligible_grids)
        if grid.path and Path(grid.path).is_file()
    ]
    missing_vision_image_window_ids = [
        window_id(index)
        for index, grid in enumerate(eligible_grids)
        if not (grid.path and Path(grid.path).is_file())
    ]
    omitted_vision_window_ids = [
        window_id(index)
        for index in range(len(eligible_grids), len(grids))
    ]
    total_image_count = sum(1 for grid in grids if grid.path and Path(grid.path).is_file())
    eligible_image_count = sum(1 for grid in eligible_grids if grid.path and Path(grid.path).is_file())
    vision_batch_size = MAX_GRIDS_PER_VISION_CALL
    vision_call_plan = []
    for batch_index, start in enumerate(range(0, len(eligible_grids), vision_batch_size), start=1):
        batch_grids = eligible_grids[start: start + vision_batch_size]
        batch_window_ids = [window_id(index) for index in range(start, start + len(batch_grids))]
        batch_image_window_ids = [
            window_id(index)
            for index, grid in enumerate(batch_grids, start=start)
            if grid.path and Path(grid.path).is_file()
        ]
        vision_call_plan.append({
            "batch": batch_index,
            "window_ids": batch_window_ids,
            "image_window_ids": batch_image_window_ids,
            "grid_count": len(batch_grids),
            "image_count": len(batch_image_window_ids),
        })
    if summary_source == "vision-llm":
        vision_call_status = "vision_llm_used"
    elif summary_source == "text-llm":
        vision_call_status = "text_llm_fallback"
    elif not bool(options.visual_understanding):
        vision_call_status = "not_enabled"
    elif not eligible_grids:
        vision_call_status = "no_frame_grids"
    elif not eligible_image_count:
        vision_call_status = "no_grid_images"
    elif not llm_configured:
        vision_call_status = "missing_api_key"
    else:
        vision_call_status = "local_template_fallback"
    llm_failure_code = _llm_failure_code(summary_source, summary_warning, llm_configured)
    return {
        "task_id": task_id,
        "title": title,
        "page_url": page_url,
        "summary_source": summary_source,
        "summary_warning": summary_warning,
        "visual_understanding": bool(options.visual_understanding),
        "vision_model_configured": llm_configured,
        "llm_model": effective_llm_model,
        "llm_base_url": effective_llm_base_url,
        "llm_base_host": llm_base_host(effective_llm_base_url),
        "llm_provider": llm_provider_name(effective_llm_base_url),
        "llm_failure_code": llm_failure_code,
        "llm_failure_stage": _warning_field(summary_warning, "stage") if llm_failure_code else "",
        "llm_failure_reason": _warning_field(summary_warning, "reason") if llm_failure_code else "",
        "note_style": options.note_style,
        "note_template": options.note_template,
        "summary_depth": options.summary_depth,
        "frame_grid_count": len(grids),
        "visual_window_count": len(visual_windows),
        "available_grid_image_count": total_image_count,
        "vision_grid_limit": MAX_VISION_GRIDS,
        "vision_batch_size": vision_batch_size,
        "vision_expected_batch_count": len(vision_call_plan),
        "vision_call_status": vision_call_status,
        "vision_call_plan": vision_call_plan,
        "vision_grid_count": len(eligible_grids),
        "vision_image_count": eligible_image_count,
        "vision_window_ids": eligible_window_ids,
        "vision_image_window_ids": vision_image_window_ids,
        "missing_vision_image_window_ids": missing_vision_image_window_ids,
        "omitted_vision_window_ids": omitted_vision_window_ids,
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
        artifacts = write_page_text_artifacts(task_id, request)
        update_task(
            task_id,
            status="success",
            phase="completed",
            progress=100,
            message="页面文本总结完成",
            note_path=artifacts.note_path,
            subtitle_path=artifacts.subtitle_path,
            transcript_path=artifacts.transcript_path,
            summary_source=artifacts.summary_source,
            summary_warning=artifacts.summary_warning,
            summary_diagnostics_path=artifacts.summary_diagnostics_path,
            summary_diagnostics=artifacts.summary_diagnostics or {},
        )
    except Exception as exc:
        _fail(task_id, "processing_failed", str(exc))


def write_download_failure_fallback(task_id: str, request: CurrentPageTaskRequest) -> bool:
    try:
        artifacts = write_page_text_artifacts(task_id, request, allow_empty=False)
        if artifacts.created:
            update_task(
                task_id,
                note_path=artifacts.note_path,
                subtitle_path=artifacts.subtitle_path,
                transcript_path=artifacts.transcript_path,
                summary_source=artifacts.summary_source,
                summary_warning=artifacts.summary_warning,
                summary_diagnostics_path=artifacts.summary_diagnostics_path,
                summary_diagnostics=artifacts.summary_diagnostics or {},
                message="视频直取失败，已保留页面文本/浏览器字幕兜底笔记",
            )
        return artifacts.created
    except Exception:
        return False


def complete_with_download_failure_fallback(task_id: str, request: CurrentPageTaskRequest, code: str, detail: str) -> bool:
    if not write_download_failure_fallback(task_id, request):
        return False
    record = get_task(task_id)
    warnings = [f"视频直取失败（{code}）：{detail}"]
    if record.summary_warning:
        warnings.append(record.summary_warning)
    update_task(
        task_id,
        status="success",
        phase="completed",
        progress=100,
        error_code=code,
        error_detail=detail,
        message="视频直取失败，已生成页面文本/浏览器字幕兜底笔记",
        summary_warning="；".join(warnings),
    )
    return True


def process_current_page_task(task_id: str, request: CurrentPageTaskRequest) -> None:
    request.resources = enrich_resources_with_active_video(request)
    write_json(task_id, "request.json", redacted_request_dump(request))
    if request.mode == "page_text":
        process_page_text_task(task_id, request)
        return

    work_dir = task_dir(task_id)
    try:
        update_task(
            task_id,
            active_video=request.active_video,
            cookie_summary=cookie_sync_summary(request.cookies),
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
            if complete_with_download_failure_fallback(task_id, request, "drm_or_encrypted", message):
                return
            _fail(task_id, "drm_or_encrypted", message)
            return
        downloader = MediaDownloader(work_dir)
        media_path, selected = downloader.download(request.page_url, request.resources, request.cookies, request.title)
        if selected:
            update_task(task_id, selected_resource=redacted_resource(selected))
        if request.mode == "download_only":
            update_task(task_id, download_attempts=downloader.attempts)
            update_task(task_id, phase="processing_video", progress=80, message="正在保存可导出的本地视频")
            normalized = work_dir / "media.mp4"
            normalize_video(media_path, normalized)
            update_task(
                task_id,
                status="success",
                phase="completed",
                progress=100,
                message="视频已下载到本地，可直接导出。",
                media_path=str(normalized),
                download_attempts=downloader.attempts,
            )
            return
        subtitle_path = None
        if should_download_page_subtitle(request):
            subtitle_path = downloader.download_subtitle(request.resources, request.cookies, request.page_url, request.title)
        update_task(task_id, download_attempts=downloader.attempts)

        _process_video_file(
            task_id=task_id,
            input_path=media_path,
            title=request.title,
            page_url=request.page_url,
            options=request.options,
            subtitle_path=subtitle_path,
            browser_subtitles=request.browser_subtitles,
        )
    except DownloadError as exc:
        if "downloader" in locals():
            update_task(task_id, download_attempts=downloader.attempts)
            failed_candidate = attempted_resource_candidate(request.resources, downloader.attempts)
            if failed_candidate:
                update_task(task_id, selected_resource=redacted_resource(failed_candidate))
        detail = exc.message
        if exc.code == "no_media_found" and request.active_video and request.active_video.src_object:
            detail = src_object_failure_message(request)
        if complete_with_download_failure_fallback(task_id, request, exc.code, detail):
            return
        _fail(task_id, exc.code, detail)
    except Exception as exc:
        _fail(task_id, "processing_failed", str(exc))


def process_local_video_task(
    task_id: str,
    input_path: Path,
    title: str,
    options: TaskOptions,
    page_url: str = "",
    browser_subtitles: list[BrowserSubtitleCue] | None = None,
) -> None:
    try:
        _process_video_file(
            task_id=task_id,
            input_path=input_path,
            title=title,
            page_url=page_url,
            options=options,
            browser_subtitles=browser_subtitles,
        )
    except Exception as exc:
        _fail(task_id, "processing_failed", str(exc))


def _process_video_file(
    task_id: str,
    input_path: Path,
    title: str,
    page_url: str,
    options: TaskOptions,
    subtitle_path: Path | None = None,
    browser_subtitles: list[BrowserSubtitleCue] | None = None,
) -> None:
    work_dir = task_dir(task_id)
    update_task(task_id, status="running", phase="processing_video", progress=25, message="正在标准化视频")

    normalized = work_dir / "media.mp4"
    normalize_video(input_path, normalized)
    update_task(task_id, media_path=str(normalized))
    audio_warning = ""
    transcript: TranscriptResult | None = None

    if subtitle_path:
        update_task(task_id, subtitle_path=str(subtitle_path), message="已检测到页面字幕，正在解析字幕")
        transcript = transcript_from_subtitle(subtitle_path)
        if not transcript.segments:
            transcript = None

    if transcript is None and browser_subtitles:
        update_task(task_id, message="已读取浏览器播放器字幕，正在生成带时间戳转写")
        transcript = transcript_from_browser_subtitles(browser_subtitles)
        if not transcript.segments:
            transcript = None
        else:
            update_task(task_id, subtitle_path=write_browser_subtitles_srt(task_id, transcript))

    if transcript is None:
        embedded_subtitle = extract_embedded_subtitle(input_path, work_dir / "embedded_subtitle.srt")
        if embedded_subtitle:
            update_task(task_id, subtitle_path=str(embedded_subtitle), message="已检测到视频内嵌字幕，正在解析字幕")
            transcript = transcript_from_subtitle(embedded_subtitle, source="embedded-subtitle")
            if not transcript.segments:
                transcript = None

    audio_path: Path | None = None
    if transcript is None:
        update_task(task_id, phase="processing_video", progress=38, message="正在提取音频")
        audio_path = work_dir / "audio.wav"
        try:
            extract_audio(normalized, audio_path)
            update_task(task_id, audio_path=str(audio_path))
        except Exception as exc:
            audio_path = None
            audio_warning = f"未能提取可转写音轨：{exc}；已继续使用画面切片生成笔记。"

        update_task(
            task_id,
            phase="transcribing",
            progress=52,
            message="正在使用远程 ASR 转写音频" if use_remote_asr(options) else "正在转写音频",
        )
        if audio_path:
            transcript = transcribe_extracted_audio(audio_path, options)
        else:
            transcript = TranscriptResult(source="no-audio", warning=audio_warning)

    if transcript is None:
        transcript = TranscriptResult(source="no-audio", warning=audio_warning)
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
