from __future__ import annotations

from dataclasses import dataclass
import json
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urldefrag

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from .downloader import DownloadError, MediaDownloader, classify_resource, effective_resource_kind, infer_manifest_url_from_fragment
from .media import build_frame_grids, extract_audio, extract_embedded_subtitle, extract_frames, normalize_video, probe_duration
from .models import ActiveVideoInfo, BrowserSubtitleCue, CurrentPageTaskRequest, DownloadAttempt, FrameGrid, ResourceCandidate, TaskOptions, TranscriptResult, TranscriptSegment, VisualWindow
from .storage import get_task, mark_task_cancelled, save_task, task_dir, update_task, write_json
from .source_input import clean_task_title
from .summarizer import MAX_GRIDS_PER_VISION_CALL, MAX_VISION_GRIDS, build_visual_windows, llm_base_host, llm_model_supports_vision, llm_provider_name, select_vision_grid_entries, summarize_page_text_with_diagnostics, summarize_with_diagnostics_audit as summarize_with_diagnostics
from .text_cleanup import correct_transcript_terms
from .transcriber import transcript_from_subtitle, transcribe_audio, transcribe_audio_openai_compatible


SAFE_RESPONSE_HEADER_NAMES = {"content-type", "content-disposition", "content-length", "content-range", "accept-ranges"}
REMOTE_ASR_TRANSCRIBERS = {"openai", "openai-compatible", "openai-compatible-asr", "groq", "groq-asr"}
ASR_FAILURE_SOURCES = {"missing-faster-whisper", "faster-whisper-error"}


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


class TaskCancelled(Exception):
    pass


def _check_cancel(task_id: str) -> None:
    if get_task(task_id).cancel_requested:
        mark_task_cancelled(task_id)
        raise TaskCancelled(task_id)


def _fail(task_id: str, code: str, detail: str) -> None:
    record = get_task(task_id)
    if record.cancel_requested or record.status == "cancelled":
        mark_task_cancelled(task_id)
        return
    update_task(
        task_id,
        status="failed",
        phase="failed",
        progress=100,
        error_code=code,
        error_detail=detail,
        failed_phase=record.phase,
        message=detail,
    )


def remember_reusable_media(task_id: str, path: Path) -> bool:
    try:
        candidate = Path(path)
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            return False
        update_task(task_id, media_path=str(candidate))
        return True
    except OSError:
        return False


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


def human_bytes(value: int | None) -> str:
    if value is None or value < 0:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{int(value)} B"


def download_progress_updater(task_id: str):
    last_progress = 10
    last_update = 0.0

    def update(downloaded: int, total: int | None, candidate: ResourceCandidate) -> None:
        nonlocal last_progress, last_update
        if downloaded <= 0:
            return
        if total and total > 0:
            progress = 10 + int(min(1.0, downloaded / total) * 50)
            size_text = f"{human_bytes(downloaded)} / {human_bytes(total)}"
        else:
            progress = min(55, 10 + int(downloaded / (10 * 1024 * 1024)) * 5)
            size_text = human_bytes(downloaded)
        now = time.monotonic()
        if progress < last_progress + 5 and now - last_update < 2:
            return
        last_progress = max(last_progress, min(60, progress))
        last_update = now
        update_task(
            task_id,
            phase="downloading",
            progress=last_progress,
            message=f"正在下载当前页视频（{size_text}）",
            selected_resource=redacted_resource(candidate),
        )

    return update


def download_status_updater(task_id: str):
    def update(message: str, progress: int, candidate: ResourceCandidate | None = None) -> None:
        current = get_task(task_id)
        payload = {
            "phase": "downloading",
            "progress": max(current.progress, max(10, min(60, int(progress)))),
            "message": message,
        }
        if candidate:
            payload["selected_resource"] = redacted_resource(candidate)
        update_task(task_id, **payload)

    return update


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


def resource_inventory_payload(request: CurrentPageTaskRequest) -> dict:
    resources = [redacted_resource(resource).model_dump(mode="json") for resource in request.resources]
    kind_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    downloadable_count = 0
    replayable_count = 0
    for resource in request.resources:
        kind = effective_resource_kind(resource) or resource.kind or "unknown"
        source = resource.source or "unknown"
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        source_counts[source] = source_counts.get(source, 0) + 1
        if kind in {"video", "hls", "dash"} or (kind == "fragment" and infer_manifest_url_from_fragment(resource.url)):
            downloadable_count += 1
        if resource.request_body or resource.request_headers:
            replayable_count += 1
    active = request.active_video
    return {
        "schema_version": 1,
        "page_url": request.page_url,
        "title": request.title,
        "candidate_count": len(resources),
        "downloadable_candidate_count": downloadable_count,
        "replayable_candidate_count": replayable_count,
        "kind_counts": dict(sorted(kind_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "drm_detected": bool(request.drm_detected),
        "drm_signal_count": len(request.drm_signals or []),
        "browser_subtitle_count": len(request.browser_subtitles or []),
        "active_video": {
            "present": bool(active),
            "source_type": "srcObject" if active and active.src_object else "url" if active and active.src else "",
            "frame_id": active.frame_id if active else None,
            "current_time": active.current_time if active else None,
            "duration": active.duration if active else None,
            "width": active.width if active else 0,
            "height": active.height if active else 0,
            "drm_detected": active.drm_detected if active else False,
        },
        "candidates": resources,
    }


def write_resource_inventory(task_id: str, request: CurrentPageTaskRequest) -> str:
    path = write_json(task_id, "resource_inventory.json", resource_inventory_payload(request))
    update_task(task_id, resource_inventory_path=str(path))
    return str(path)


def _redacted_report_value(value, parent_key: str = ""):
    if isinstance(value, dict):
        lowered_parent = parent_key.lower()
        if lowered_parent == "headers":
            return _safe_response_headers({str(name): str(item) for name, item in value.items()})
        if lowered_parent in {"request_headers", "request_body"}:
            return {str(name): "<redacted>" for name in value}
        redacted = {}
        for name, item in value.items():
            key = str(name)
            lowered = key.lower()
            if lowered in {"authorization", "cookie", "set-cookie", "proxy-authorization"}:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redacted_report_value(item, key)
        return redacted
    if isinstance(value, list):
        return [_redacted_report_value(item, parent_key) for item in value]
    return value


def write_page_preflight_report(task_id: str, request: CurrentPageTaskRequest) -> str:
    report = request.page_preflight_report or {}
    if not isinstance(report, dict) or not report:
        return ""
    path = write_json(task_id, "page_preflight_report.json", _redacted_report_value(report))
    update_task(task_id, page_preflight_report_path=str(path))
    return str(path)


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


def enrich_resource_candidates_with_active_video(
    active_video: ActiveVideoInfo | None,
    resources: list[ResourceCandidate],
) -> list[ResourceCandidate]:
    if not active_video:
        return resources
    enriched: list[ResourceCandidate] = []
    matched_active_src = False
    for resource in resources:
        item = resource.model_copy(deep=True)
        match = _active_video_resource_match(active_video, item)
        if match:
            matched_active_src = True
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
    synthetic = active_video_resource_candidate(active_video) if not matched_active_src else None
    if synthetic and not any(_canonical_media_url(item.url) == _canonical_media_url(synthetic.url) for item in enriched):
        enriched.insert(0, synthetic)
    return enriched


def active_video_resource_candidate(active_video: ActiveVideoInfo) -> ResourceCandidate | None:
    src = str(active_video.src or "").strip()
    if not src.lower().startswith(("http://", "https://")):
        return None
    kind = classify_resource(src)
    if kind in {"audio", "subtitle", "fragment"}:
        return None
    if kind == "unknown":
        kind = "video"
    return ResourceCandidate(
        url=src,
        source="activeVideo",
        kind=kind,
        mime="application/vnd.apple.mpegurl" if kind == "hls" else "application/dash+xml" if kind == "dash" else "video/mp4" if kind == "video" else "",
        score=100,
        label=active_video.label or "current video src",
        is_main_video=True,
        playback_match="exact-src",
        frame_id=active_video.frame_id,
        current_time=active_video.current_time,
        duration=active_video.duration or None,
        width=active_video.width or None,
        height=active_video.height or None,
        request_type="active-video",
        frame_url=active_video.frame_url,
        request_headers={"Referer": active_video.frame_url} if active_video.frame_url else {},
    )


def enrich_resources_with_active_video(request: CurrentPageTaskRequest) -> list[ResourceCandidate]:
    return enrich_resource_candidates_with_active_video(request.active_video, request.resources)


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


def maybe_download_page_subtitle(downloader: object, request: CurrentPageTaskRequest) -> Path | None:
    if not should_download_page_subtitle(request):
        return None
    download_subtitle = getattr(downloader, "download_subtitle", None)
    if not callable(download_subtitle):
        return None
    try:
        return download_subtitle(request.resources, request.cookies, request.page_url, request.title)
    except DownloadError:
        return None


def parse_subtitle_or_none(path: Path, source: str = "page-subtitle") -> TranscriptResult | None:
    try:
        transcript = transcript_from_subtitle(path, source=source)
    except Exception:
        return None
    return transcript if transcript.segments else None


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


def asr_failure_detail(transcript: TranscriptResult) -> str:
    source = str(transcript.source or "").strip().lower()
    failed = source in ASR_FAILURE_SOURCES or bool(re.search(r"-(?:missing-key|missing-sdk|error)$", source))
    if not failed:
        return ""
    return transcript.warning or f"ASR failed with source: {transcript.source or 'unknown'}"


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


def _safe_llm_events(events: list[dict] | None, limit: int = 20) -> list[dict]:
    safe_events: list[dict] = []
    for event in (events or [])[:limit]:
        if not isinstance(event, dict):
            continue
        safe_events.append({
            key: value
            for key, value in event.items()
            if key in {"stage", "code", "error_type", "message", "batch", "model"}
            and value not in (None, "", [])
        })
    return safe_events


def _llm_event_failure(events: list[dict]) -> dict:
    for event in reversed(events or []):
        code = str(event.get("code") or "").strip()
        if code and code not in {"ok", "success"}:
            return event
    return {}


def _vision_model_rejected_image(events: list[dict]) -> bool:
    pattern = "image|vision|modal|multimodal|content|unsupported|invalid"
    for event in events or []:
        if event.get("stage") != "vision_batch":
            continue
        text = " ".join(str(event.get(key) or "") for key in ("code", "error_type", "message")).lower()
        if re.search(pattern, text):
            return True
    return False


def build_summary_diagnostics(
    task_id: str,
    title: str,
    page_url: str,
    options: TaskOptions,
    grids: list[FrameGrid],
    visual_windows: list[VisualWindow],
    summary_source: str,
    summary_warning: str,
    llm_events: list[dict] | None = None,
    page_context: str = "",
) -> dict:
    eligible_entries = select_vision_grid_entries(grids)
    eligible_grids = [grid for _index, grid in eligible_entries]
    eligible_indices = [index for index, _grid in eligible_entries]
    eligible_index_set = set(eligible_indices)
    effective_llm_base_url = options.llm_base_url or LLM_BASE_URL
    effective_llm_model = options.llm_model or LLM_MODEL
    llm_configured = bool(options.llm_api_key or LLM_API_KEY)
    vision_model_configured = llm_configured and llm_model_supports_vision(effective_llm_base_url, effective_llm_model)

    def window_id(index: int) -> str:
        if index < len(visual_windows) and visual_windows[index].id:
            return visual_windows[index].id
        return f"W{index + 1:03d}"

    eligible_window_ids = [window_id(index) for index in eligible_indices]
    vision_image_window_ids = [
        window_id(index)
        for index, grid in eligible_entries
        if grid.path and Path(grid.path).is_file()
    ]
    missing_vision_image_window_ids = [
        window_id(index)
        for index, grid in eligible_entries
        if not (grid.path and Path(grid.path).is_file())
    ]
    omitted_vision_window_ids = [
        window_id(index)
        for index in range(len(grids))
        if index not in eligible_index_set
    ]
    total_image_count = sum(1 for grid in grids if grid.path and Path(grid.path).is_file())
    eligible_image_count = sum(1 for grid in eligible_grids if grid.path and Path(grid.path).is_file())
    vision_batch_size = MAX_GRIDS_PER_VISION_CALL
    vision_call_plan = []
    for batch_index, start in enumerate(range(0, len(eligible_entries), vision_batch_size), start=1):
        batch_entries = eligible_entries[start: start + vision_batch_size]
        batch_window_ids = [window_id(index) for index, _grid in batch_entries]
        batch_image_window_ids = [
            window_id(index)
            for index, grid in batch_entries
            if grid.path and Path(grid.path).is_file()
        ]
        vision_call_plan.append({
            "batch": batch_index,
            "window_ids": batch_window_ids,
            "image_window_ids": batch_image_window_ids,
            "grid_count": len(batch_entries),
            "image_count": len(batch_image_window_ids),
        })
    if llm_configured and not vision_model_configured:
        vision_call_status = "text_only_model"
    elif summary_source == "vision-llm":
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
    safe_llm_events = _safe_llm_events(llm_events)
    last_llm_failure = _llm_event_failure(safe_llm_events)
    failed_vision_batch_count = sum(
        1
        for event in safe_llm_events
        if event.get("stage") == "vision_batch" and str(event.get("code") or "").lower() not in {"", "ok", "success"}
    )
    llm_failure_code = _llm_failure_code(summary_source, summary_warning, llm_configured)
    if not llm_failure_code and last_llm_failure and summary_source == "local-template":
        llm_failure_code = str(last_llm_failure.get("code") or "llm_unavailable")
    page_context_text = (page_context or "").strip()
    return {
        "task_id": task_id,
        "title": title,
        "page_url": page_url,
        "summary_source": summary_source,
        "summary_warning": summary_warning,
        "visual_understanding": bool(options.visual_understanding),
        "llm_model_configured": llm_configured,
        "vision_model_configured": vision_model_configured,
        "llm_model": effective_llm_model,
        "llm_base_url": effective_llm_base_url,
        "llm_base_host": llm_base_host(effective_llm_base_url),
        "llm_provider": llm_provider_name(effective_llm_base_url),
        "llm_failure_code": llm_failure_code,
        "llm_failure_stage": (_warning_field(summary_warning, "stage") or last_llm_failure.get("stage") or "") if llm_failure_code else "",
        "llm_failure_reason": (_warning_field(summary_warning, "reason") or last_llm_failure.get("message") or last_llm_failure.get("error_type") or "") if llm_failure_code else "",
        "llm_event_count": len(safe_llm_events),
        "llm_events": safe_llm_events,
        "llm_last_event": safe_llm_events[-1] if safe_llm_events else {},
        "llm_last_failure": last_llm_failure,
        "note_style": options.note_style,
        "note_template": options.note_template,
        "summary_depth": options.summary_depth,
        "page_text_char_count": len(page_context_text),
        "page_context_used": bool(page_context_text),
        "frame_grid_count": len(grids),
        "visual_window_count": len(visual_windows),
        "available_grid_image_count": total_image_count,
        "vision_grid_limit": MAX_VISION_GRIDS,
        "vision_batch_size": vision_batch_size,
        "vision_expected_batch_count": len(vision_call_plan),
        "vision_call_status": vision_call_status,
        "vision_call_plan": vision_call_plan,
        "vision_failed_batch_count": failed_vision_batch_count,
        "vision_model_rejected_image": _vision_model_rejected_image(safe_llm_events),
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
        _check_cancel(task_id)
        update_task(task_id, status="running", phase="summarizing", progress=60, message="正在总结当前页面文本")
        artifacts = write_page_text_artifacts(task_id, request)
        _check_cancel(task_id)
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
    except TaskCancelled:
        return
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
        status="failed",
        phase="failed",
        progress=100,
        error_code=code,
        error_detail=detail,
        message="视频直取失败，已生成页面文本/浏览器字幕兜底笔记",
        summary_warning="；".join(warnings),
    )
    return True


def process_current_page_task(task_id: str, request: CurrentPageTaskRequest) -> None:
    try:
        _check_cancel(task_id)
    except TaskCancelled:
        return
    request.resources = enrich_resources_with_active_video(request)
    write_json(task_id, "request.json", redacted_request_dump(request))
    write_resource_inventory(task_id, request)
    write_page_preflight_report(task_id, request)
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
        downloader = MediaDownloader(
            work_dir,
            progress_callback=download_progress_updater(task_id),
            status_callback=download_status_updater(task_id),
        )
        media_path, selected = downloader.download(request.page_url, request.resources, request.cookies, request.title)
        _check_cancel(task_id)
        resolved_title = clean_task_title(getattr(downloader, "resolved_title", ""), request.page_url, request.title)
        if resolved_title != request.title:
            request.title = resolved_title
            update_task(task_id, title=resolved_title)
        remember_reusable_media(task_id, media_path)
        if selected:
            update_task(task_id, selected_resource=redacted_resource(selected))
        if request.mode == "download_only":
            update_task(task_id, download_attempts=downloader.attempts)
            update_task(task_id, phase="processing_video", progress=80, message="正在保存可导出的本地视频")
            normalized = work_dir / "media.mp4"
            normalize_video(media_path, normalized)
            _check_cancel(task_id)
            transcript_path = ""
            subtitle_path = ""
            page_subtitle_path = maybe_download_page_subtitle(downloader, request)
            if page_subtitle_path:
                subtitle_path = str(page_subtitle_path)
                transcript = parse_subtitle_or_none(page_subtitle_path)
                if transcript:
                    transcript_path = str(write_json(task_id, "transcript.json", transcript.model_dump(mode="json")))
            if not transcript_path:
                transcript = transcript_from_browser_subtitles(request.browser_subtitles)
                if transcript.segments:
                    subtitle_path = write_browser_subtitles_srt(task_id, transcript)
                    transcript_path = str(write_json(task_id, "transcript.json", transcript.model_dump(mode="json")))
            update_task(
                task_id,
                status="success",
                phase="completed",
                progress=100,
                message="视频已下载到本地，可直接导出。",
                media_path=str(normalized),
                subtitle_path=subtitle_path,
                transcript_path=transcript_path,
                download_attempts=downloader.attempts,
            )
            return
        subtitle_path = maybe_download_page_subtitle(downloader, request)
        update_task(task_id, download_attempts=downloader.attempts)

        _process_video_file(
            task_id=task_id,
            input_path=media_path,
            title=request.title,
            page_url=request.page_url,
            options=request.options,
            subtitle_path=subtitle_path,
            browser_subtitles=request.browser_subtitles,
            page_context=request.page_text,
        )
    except TaskCancelled:
        return
    except DownloadError as exc:
        if get_task(task_id).cancel_requested:
            mark_task_cancelled(task_id)
            return
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
    subtitle_path: Path | None = None,
    subtitle_source: str = "page-subtitle",
) -> None:
    try:
        _check_cancel(task_id)
        _process_video_file(
            task_id=task_id,
            input_path=input_path,
            title=title,
            page_url=page_url,
            options=options,
            subtitle_path=subtitle_path,
            browser_subtitles=browser_subtitles,
            subtitle_source=subtitle_source,
            page_context="",
        )
    except TaskCancelled:
        return
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
    subtitle_source: str = "page-subtitle",
    page_context: str = "",
) -> None:
    work_dir = task_dir(task_id)
    _check_cancel(task_id)
    update_task(task_id, status="running", phase="processing_video", progress=25, message="正在标准化视频")

    normalized = work_dir / "media.mp4"
    remember_reusable_media(task_id, input_path)
    normalize_video(input_path, normalized)
    _check_cancel(task_id)
    update_task(task_id, media_path=str(normalized))
    audio_warning = ""
    transcript: TranscriptResult | None = None

    if subtitle_path:
        owned_subtitle_path = subtitle_path
        try:
            if subtitle_path.resolve().parent != work_dir.resolve():
                owned_subtitle_path = work_dir / subtitle_path.name
                if owned_subtitle_path.resolve() != subtitle_path.resolve():
                    shutil.copy2(subtitle_path, owned_subtitle_path)
        except OSError:
            owned_subtitle_path = subtitle_path
        update_task(task_id, subtitle_path=str(owned_subtitle_path), message="已检测到页面字幕，正在解析字幕")
        transcript = parse_subtitle_or_none(owned_subtitle_path, source=subtitle_source or "page-subtitle")

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
            transcript = parse_subtitle_or_none(embedded_subtitle, source="embedded-subtitle")

    audio_path: Path | None = None
    if transcript is None:
        update_task(task_id, phase="processing_video", progress=38, message="正在提取音频")
        audio_path = work_dir / "audio.wav"
        try:
            extract_audio(normalized, audio_path)
            _check_cancel(task_id)
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
            _check_cancel(task_id)
        else:
            transcript = TranscriptResult(source="no-audio", warning=audio_warning)

    if transcript is None:
        transcript = TranscriptResult(source="no-audio", warning=audio_warning)
    transcript = correct_transcript_terms(transcript)
    asr_error = asr_failure_detail(transcript)
    if asr_error:
        transcript = transcript.model_copy(update={"segments": [], "full_text": ""})
    transcript_path = work_dir / "transcript.json"
    transcript_path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
    update_task(task_id, transcript_path=str(transcript_path))

    grids = []
    if options.visual_understanding:
        update_task(task_id, phase="extracting_frames", progress=68, message="正在抽帧并生成画面网格")
        frame_dir = work_dir / "frames"
        grid_dir = work_dir / "grids"
        media_duration = probe_duration(normalized)
        frames = extract_frames(normalized, frame_dir, max(1, options.frame_interval))
        _check_cancel(task_id)
        grids = build_frame_grids(
            task_id,
            frames,
            grid_dir,
            max(1, options.grid_columns),
            max(1, options.grid_rows),
            max(1, options.frame_interval),
            media_duration=media_duration,
        )

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
    _check_cancel(task_id)
    summary_result = summarize_with_diagnostics(title, transcript, grids, options, page_url, page_context)
    _check_cancel(task_id)
    if len(summary_result) == 4:
        note, summary_source, summary_warning, llm_events = summary_result
    else:
        note, summary_source, summary_warning = summary_result
        llm_events = []
    summary_diagnostics = build_summary_diagnostics(
        task_id=task_id,
        title=title,
        page_url=page_url,
        options=options,
        grids=grids,
        visual_windows=visual_windows,
        summary_source=summary_source,
        summary_warning=summary_warning,
        llm_events=llm_events,
        page_context=page_context,
    )
    summary_diagnostics_path = write_json(task_id, "summary_diagnostics.json", summary_diagnostics)
    note_path = work_dir / "note.md"
    note_path.write_text(note, encoding="utf-8")

    final_fields = {
        "note_path": str(note_path),
        "summary_source": summary_source,
        "summary_warning": summary_warning,
        "summary_diagnostics_path": str(summary_diagnostics_path),
        "summary_diagnostics": summary_diagnostics,
    }
    if asr_error:
        update_task(
            task_id,
            status="failed",
            phase="failed",
            progress=100,
            message=asr_error,
            error_code="asr_failed",
            error_detail=asr_error,
            **final_fields,
        )
    else:
        update_task(
            task_id,
            status="success",
            phase="completed",
            progress=100,
            message="任务完成",
            **final_fields,
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
