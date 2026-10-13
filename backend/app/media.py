from __future__ import annotations

import base64
import errno
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .config import BACKEND_ORIGIN
from .models import FrameGrid, FrameSample, MediaIntegrity, MediaTrackInfo
from .runtime import ffmpeg_bin, ffprobe_bin, text_subprocess_kwargs
from .text_cleanup import TextDecodingError, read_canonical_text


class MediaProcessingError(RuntimeError):
    pass


FRAME_CACHE_SCHEMA_VERSION = 3
FRAME_EXTRACTOR_VERSION = "adaptive-batch-v3-exact"
DEFAULT_FRAME_EXTRACT_BATCH_SIZE = 12
_cancel_check = ContextVar("media_cancel_check", default=None)


@contextmanager
def media_cancellation(check):
    """Bind cancellation to this task/thread only, including subprocess cleanup."""
    token = _cancel_check.set(check)
    try:
        check()
        yield
    finally:
        _cancel_check.reset(token)


def _run(cmd: list[str], message: str) -> None:
    check = _cancel_check.get()
    if check is None:
        result = subprocess.run(cmd, capture_output=True, **text_subprocess_kwargs())
    else:
        check()
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **text_subprocess_kwargs()) as process:
            try:
                while True:
                    check()
                    try:
                        stdout, stderr = process.communicate(timeout=.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException:
                process.kill()
                process.communicate()
                raise
            result = subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
    if result.returncode != 0:
        raise MediaProcessingError(f"{message}: {result.stderr[:500]}")


def require_ffmpeg() -> None:
    if not ffmpeg_bin():
        raise MediaProcessingError("未找到 ffmpeg。")


def probe_duration(path: Path) -> float:
    probe = ffprobe_bin()
    if probe:
        result = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            **text_subprocess_kwargs(),
        )
        if result.returncode == 0:
            try:
                return float(json.loads(result.stdout)["format"]["duration"])
            except Exception:
                pass

    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        return 0
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(path),
        ],
        capture_output=True,
        **text_subprocess_kwargs(),
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr or "")
    if not match:
        return 0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_float(value: object) -> float:
    try:
        result = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) and result >= 0 else 0.0


def _integrity_status(has_video: bool, has_audio: bool) -> tuple[str, list[str]]:
    if has_video and has_audio:
        return "ready", []
    if has_video:
        return "video_only", ["missing_audio_track"]
    if has_audio:
        return "audio_only", ["missing_video_track"]
    return "no_media", ["missing_video_and_audio_tracks"]


def _integrity_from_ffprobe(path: Path, probe: str) -> MediaIntegrity | None:
    result = subprocess.run(
        [
            probe,
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration,size:stream=index,codec_type,codec_name,duration,width,height,channels:stream_tags=language,title",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        **text_subprocess_kwargs(),
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None
    tracks: list[MediaTrackInfo] = []
    for raw in payload.get("streams") or []:
        raw_type = str(raw.get("codec_type") or "unknown").lower()
        track_type = raw_type if raw_type in {"video", "audio", "subtitle", "data"} else "unknown"
        tags = raw.get("tags") if isinstance(raw.get("tags"), dict) else {}
        tracks.append(MediaTrackInfo(
            index=int(raw.get("index") or 0),
            type=track_type,
            codec=str(raw.get("codec_name") or ""),
            duration=_safe_float(raw.get("duration")),
            language=str(tags.get("language") or ""),
            title=str(tags.get("title") or ""),
            width=int(raw["width"]) if raw.get("width") is not None else None,
            height=int(raw["height"]) if raw.get("height") is not None else None,
            channels=int(raw["channels"]) if raw.get("channels") is not None else None,
        ))
    format_data = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    return _build_media_integrity(
        path,
        tracks,
        duration=_safe_float(format_data.get("duration")),
        container=str(format_data.get("format_name") or ""),
        probe_backend="ffprobe",
    )


def _integrity_from_ffmpeg(path: Path, ffmpeg: str) -> MediaIntegrity:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        **text_subprocess_kwargs(),
    )
    stderr = result.stderr or ""
    tracks: list[MediaTrackInfo] = []
    stream_pattern = re.compile(
        r"Stream\s+#\S+?(?:\((?P<language>[^)]+)\))?:\s+(?P<type>Video|Audio|Subtitle|Data):\s+(?P<codec>[^,\s]+)",
        re.I,
    )
    for index, match in enumerate(stream_pattern.finditer(stderr)):
        track_type = match.group("type").lower()
        tracks.append(MediaTrackInfo(
            index=index,
            type=track_type if track_type in {"video", "audio", "subtitle", "data"} else "unknown",
            codec=match.group("codec"),
            language=match.group("language") or "",
        ))
    container_match = re.search(r"Input #0,\s*([^,\r\n]+(?:,[^,\r\n]+)*)\s*,\s*from", stderr)
    return _build_media_integrity(
        path,
        tracks,
        duration=probe_duration(path),
        container=container_match.group(1).strip() if container_match else "",
        probe_backend="ffmpeg",
        warnings=[] if tracks else ["stream_metadata_unavailable"],
    )


def _build_media_integrity(
    path: Path,
    tracks: list[MediaTrackInfo],
    *,
    duration: float,
    container: str,
    probe_backend: str,
    warnings: list[str] | None = None,
) -> MediaIntegrity:
    video_tracks = [track for track in tracks if track.type == "video"]
    audio_tracks = [track for track in tracks if track.type == "audio"]
    subtitle_tracks = [track for track in tracks if track.type == "subtitle"]
    status, blocking_reasons = _integrity_status(bool(video_tracks), bool(audio_tracks))
    if duration <= 0:
        status = "invalid"
        blocking_reasons.append("invalid_or_missing_duration")
    return MediaIntegrity(
        status=status,
        probe_backend=probe_backend,
        file_size=path.stat().st_size if path.is_file() else 0,
        sha256=file_sha256(path) if path.is_file() else "",
        duration=duration,
        container=container,
        stream_count=len(tracks),
        video_stream_count=len(video_tracks),
        audio_stream_count=len(audio_tracks),
        subtitle_stream_count=len(subtitle_tracks),
        has_video=bool(video_tracks),
        has_audio=bool(audio_tracks),
        has_subtitles=bool(subtitle_tracks),
        video_codec=video_tracks[0].codec if video_tracks else "",
        audio_codec=audio_tracks[0].codec if audio_tracks else "",
        subtitle_codec=subtitle_tracks[0].codec if subtitle_tracks else "",
        tracks=tracks,
        blocking_reasons=list(dict.fromkeys(blocking_reasons)),
        warnings=list(warnings or []),
    )


def probe_media_integrity(path: Path) -> MediaIntegrity:
    if not path.is_file() or path.stat().st_size <= 0:
        return MediaIntegrity(status="invalid", blocking_reasons=["empty_or_missing_file"])
    probe = ffprobe_bin()
    if probe:
        integrity = _integrity_from_ffprobe(path, probe)
        if integrity is not None:
            return integrity
    ffmpeg = ffmpeg_bin()
    if ffmpeg:
        return _integrity_from_ffmpeg(path, ffmpeg)
    return MediaIntegrity(
        status="invalid",
        file_size=path.stat().st_size,
        sha256=file_sha256(path),
        blocking_reasons=["ffmpeg_or_ffprobe_required"],
    )


def normalize_video(input_path: Path, output_path: Path) -> Path:
    require_ffmpeg()
    ffmpeg = ffmpeg_bin()
    if input_path.resolve() == output_path.resolve():
        return input_path
    # Atomically replace the directory entry: retained OCR hardlinks must
    # keep their original inode even when this task normalizes again.
    with tempfile.TemporaryDirectory(prefix=".normalize-", dir=output_path.parent) as temporary_dir:
        temporary = Path(temporary_dir) / output_path.name
        _run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(input_path),
                "-map",
                "0:v:0?",
                "-map",
                "0:a:0?",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            "视频标准化失败",
        )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise MediaProcessingError("视频标准化未生成有效文件")
        temporary.replace(output_path)
    return output_path


def extract_video_clip(video_path: Path, output_path: Path, start: float, end: float) -> Path:
    require_ffmpeg()
    ffmpeg = ffmpeg_bin()
    start_value = max(0.0, float(start or 0))
    duration = max(0.5, float(end or 0) - start_value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    _run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start_value:.3f}",
            "-i",
            str(video_path),
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-threads",
            "2",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-avoid_negative_ts",
            "make_zero",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        "视频切片导出失败",
    )
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise MediaProcessingError("视频切片导出失败：输出文件为空")
    return output_path


def extract_audio(video_path: Path, output_path: Path) -> Path:
    require_ffmpeg()
    ffmpeg = ffmpeg_bin()
    _run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-acodec",
            "pcm_s16le",
            str(output_path),
        ],
        "音频提取失败",
    )
    return output_path


def extract_embedded_subtitle(video_path: Path, output_path: Path) -> Path | None:
    require_ffmpeg()
    ffmpeg = ffmpeg_bin()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-map",
            "0:s:0?",
            "-c:s",
            "srt",
            str(output_path),
        ],
        capture_output=True,
        **text_subprocess_kwargs(),
    )
    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
        output_path.unlink(missing_ok=True)
        return None
    try:
        text = read_canonical_text(output_path).text
    except TextDecodingError:
        output_path.unlink(missing_ok=True)
        return None
    if "-->" not in text:
        output_path.unlink(missing_ok=True)
        return None
    return output_path


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _image_pixels(image: Image.Image):
    if hasattr(image, "get_flattened_data"):
        return image.get_flattened_data()
    return image.getdata()


def _average_hash(path: Path, size: int = 8) -> int:
    with Image.open(path) as image:
        pixels = list(_image_pixels(image.convert("L").resize((size, size), Image.Resampling.LANCZOS)))
    if not pixels:
        return 0
    average = sum(pixels) / len(pixels)
    value = 0
    for index, pixel in enumerate(pixels):
        if pixel >= average:
            value |= 1 << index
    return value


def _mean_luma(path: Path) -> float:
    with Image.open(path) as image:
        pixels = list(_image_pixels(image.convert("L").resize((16, 16), Image.Resampling.BILINEAR)))
    if not pixels:
        return 0.0
    return sum(pixels) / len(pixels)


def _hamming_distance(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def _should_keep_sampled_frame(
    *,
    current_hash: str,
    timestamp: float,
    last_hash: str,
    last_kept_timestamp: float | None,
    coverage_gap: int,
) -> bool:
    if not last_hash or last_kept_timestamp is None:
        return True
    exact_duplicate = current_hash == last_hash
    # A perceptual hash cannot prove equality: even a changed subtitle/operator
    # or small colored diagram can have the same reduced grayscale pixels.
    # Callers supply the full encoded-image SHA256; unequal bytes stay retained.
    if not exact_duplicate:
        return True
    return timestamp - last_kept_timestamp >= max(1, coverage_gap)


def _normalize_frame_anchor_timestamps(duration: float, anchor_timestamps: list[float] | None) -> list[int]:
    if duration <= 0:
        return []
    last_seekable_second = max(0, int(math.ceil(duration)) - 1)
    normalized = set()
    for raw_timestamp in anchor_timestamps or []:
        try:
            timestamp = float(raw_timestamp)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(timestamp):
            continue
        normalized.add(min(last_seekable_second, max(0, int(round(timestamp)))))
    return sorted(normalized)


def _evenly_spaced(values, limit: int) -> list[int]:
    if limit <= 0 or not values:
        return []
    if len(values) <= limit:
        return list(values)
    if limit == 1:
        return [values[len(values) // 2]]
    return [values[round(index * (len(values) - 1) / (limit - 1))] for index in range(limit)]


def _sample_frame_timestamps(
    duration: float,
    interval: int,
    max_frames: int = 900,
    anchor_timestamps: list[float] | None = None,
) -> list[int]:
    if not math.isfinite(duration) or duration <= 0 or max_frames <= 0:
        return []
    interval = max(1, int(interval or 1))
    tail = max(0, int(math.ceil(duration)) - 1)
    baseline = range(0, tail + 1, interval)
    anchors = _normalize_frame_anchor_timestamps(duration, anchor_timestamps)
    selected = [0]
    if max_frames > 1 and tail:
        selected.append(tail)
    for timestamp in _evenly_spaced([value for value in anchors if value not in selected], max_frames - len(selected)):
        selected.append(timestamp)
    # Sample the entire range before applying the budget, never its prefix only.
    candidates = _evenly_spaced(baseline, max_frames)
    selected.extend(_evenly_spaced([value for value in candidates if value not in selected], max_frames - len(selected)))
    return sorted(selected)


def detect_scene_change_timestamps(
    video_path: Path,
    *,
    threshold: float = 0.22,
    max_scenes: int = 600,
) -> list[int]:
    ffmpeg = ffmpeg_bin()
    if not ffmpeg or max_scenes <= 0:
        return []
    threshold = min(0.95, max(0.05, float(threshold)))
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(video_path),
            "-an",
            "-vf",
            f"select=gt(scene\\,{threshold:.3f}),showinfo",
            "-frames:v",
            str(max_scenes),
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        **text_subprocess_kwargs(),
    )
    values: set[int] = set()
    for raw in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr or ""):
        values.add(max(0, int(round(float(raw)))))
    return sorted(values)[:max_scenes]


def _adaptive_frame_plan(
    duration: float,
    interval: int,
    max_frames: int,
    scene_timestamps: list[int],
    anchor_timestamps: list[float] | None,
) -> list[tuple[int, list[str]]]:
    if not math.isfinite(duration) or duration <= 0 or max_frames <= 0:
        return []
    baseline = _sample_frame_timestamps(duration, interval, max_frames=max_frames)
    anchors = _normalize_frame_anchor_timestamps(duration, anchor_timestamps)
    last_seekable = max(0, int(math.ceil(duration)) - 1)
    scenes = sorted({min(last_seekable, max(0, int(value))) for value in scene_timestamps})
    reasons: dict[int, set[str]] = {}
    for value in baseline:
        reasons.setdefault(value, set()).add("coverage")
    context_values: list[int] = []
    for value in scenes:
        reasons.setdefault(value, set()).update({"scene_change", "content_change"})
        for context_value in (max(0, value - 1), min(last_seekable, value + 1)):
            reasons.setdefault(context_value, set()).add("interaction_context")
            context_values.append(context_value)
    for value in anchors:
        reasons.setdefault(value, set()).add("playback_anchor")
    reasons.setdefault(0, set()).add("start")
    reasons.setdefault(last_seekable, set()).add("tail")

    if max_frames == 1:
        selected = {0}
        return [(value, sorted(reasons[value])) for value in sorted(selected)]

    def evenly_spaced(values: list[int], limit: int) -> list[int]:
        return _evenly_spaced(sorted(set(values)), limit)

    # Coverage owns the majority of the budget and is selected across the full
    # timeline before scene changes are considered.
    coverage_budget = min(len(baseline), max(2, int(math.ceil(max_frames * 0.60))))
    coverage_values = evenly_spaced(baseline, coverage_budget)
    # Endpoints have first claim on the bounded budget, even with many anchors.
    selected_order = sorted({0, last_seekable})
    anchor_values = evenly_spaced([value for value in anchors if value not in selected_order], max_frames - len(selected_order))
    for value in [*anchor_values, *coverage_values]:
        if value not in selected_order and len(selected_order) < max_frames:
            selected_order.append(value)

    scene_budget = max_frames - len(selected_order)
    available_scene_context = [
        value for value in [*scenes, *context_values]
        if value not in selected_order
    ]
    scene_context = evenly_spaced(available_scene_context, scene_budget)
    for value in scene_context:
        if value not in selected_order and len(selected_order) < max_frames:
            selected_order.append(value)

    if len(selected_order) < max_frames:
        for value in evenly_spaced(baseline, max_frames):
            if value not in selected_order:
                selected_order.append(value)
            if len(selected_order) >= max_frames:
                break
    selected = set(selected_order)
    return [(value, sorted(reasons[value])) for value in sorted(selected)]


def _frame_cache_payload(
    video_path: Path,
    plan: list[tuple[int, list[str]]],
    *,
    interval: int,
    scene_threshold: float,
) -> dict:
    stat = video_path.stat()
    return {
        "schema_version": FRAME_CACHE_SCHEMA_VERSION,
        "extractor_version": FRAME_EXTRACTOR_VERSION,
        "source_sha256": file_sha256(video_path),
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "interval": int(interval),
        "scene_threshold": round(float(scene_threshold), 6),
        "plan": [[int(timestamp), list(reasons)] for timestamp, reasons in plan],
    }


def _read_frame_cache(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_frame_cache(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _extract_frame_batch(
    ffmpeg: str,
    video_path: Path,
    requests: list[tuple[int, Path]],
) -> bool:
    """Extract arbitrary timestamps with one bounded ffmpeg process.

    Each timestamp is an independently seekable input, so accuracy and output
    naming remain compatible with the old per-frame implementation while the
    expensive process startup is amortised across the batch.
    """

    if not requests:
        return True
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for timestamp, _output in requests:
        command.extend(["-ss", f"{max(0, timestamp):.3f}", "-i", str(video_path)])
    for input_index, (_timestamp, output) in enumerate(requests):
        command.extend([
            "-map",
            f"{input_index}:v:0",
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(output),
        ])
    result = subprocess.run(command, capture_output=True, **text_subprocess_kwargs())
    return result.returncode == 0


def _extract_single_frame(ffmpeg: str, video_path: Path, timestamp: int, output: Path) -> bool:
    seek_start = max(0, timestamp - 3)
    precise_offset = timestamp - seek_start
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(seek_start),
            "-i",
            str(video_path),
            "-ss",
            str(precise_offset),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(output),
        ],
        capture_output=True,
        **text_subprocess_kwargs(),
    )
    return result.returncode == 0 and _valid_frame_file(output)


def _valid_frame_file(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError):
        return False


def _publish_evidence(source: Path, target: Path) -> None:
    """Publish without replacing any already referenced evidence bytes."""
    try:
        # Staging and target share the same directory/filesystem. Linking the
        # completed bytes is atomic and cannot replace an existing target.
        os.link(source, target)
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != source.read_bytes():
            raise MediaProcessingError("已有画面证据校验不一致，已停止写入并保留原文件；请在新任务中重新提取。")
    except OSError as exc:
        if exc.errno not in {errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS} and getattr(exc, "winerror", None) not in {1, 50}:
            raise MediaProcessingError("无法保存画面证据，已停止写入；请检查资料目录和剩余空间。") from exc
        # Some user-selected volumes do not support hardlinks. Exclusively
        # create a new target, never replace one. No URL/cache is published until
        # copying finishes. A caught failure removes only our new partial file;
        # after process death a mismatch fails closed on the next attempt.
        try:
            destination = target.open("xb")
        except FileExistsError:
            if target.is_symlink() or target.read_bytes() != source.read_bytes():
                raise MediaProcessingError("已有画面证据校验不一致，已停止写入并保留原文件。")
            return
        try:
            with destination, source.open("rb") as stream:
                shutil.copyfileobj(stream, destination)
        except BaseException:
            target.unlink(missing_ok=True)
            raise


def _sampling_coverage(duration, interval, max_frames, plan, samples, scenes, anchors) -> dict:
    tail = max(0, math.ceil(duration) - 1)
    endpoints = sorted({0, tail})
    selected = {timestamp for timestamp, _ in plan}
    retained = {int(sample.timestamp) for sample in samples}
    baseline_count = len(range(0, tail + 1, interval)) + int(tail % interval != 0)
    baseline_selected = sum(timestamp % interval == 0 or timestamp == tail for timestamp in selected)
    omitted_anchors = sorted(set(_normalize_frame_anchor_timestamps(duration, anchors)) - selected)
    requested_scenes = {min(tail, max(0, int(timestamp))) for timestamp in scenes}
    scene_context = {point for timestamp in requested_scenes for point in (max(0, timestamp - 1), min(tail, timestamp + 1))}
    omitted_scenes = len((requested_scenes | scene_context) - selected)
    missing_endpoints = sorted(set(endpoints) - retained)
    limited = baseline_selected < baseline_count or bool(omitted_anchors) or omitted_scenes > 0
    return {
        "status": "incomplete" if missing_endpoints else "budget_limited" if limited else "sampled",
        "frame_budget": max_frames,
        "budget_limited": limited,
        "endpoint_timestamps": endpoints,
        "missing_endpoint_timestamps": missing_endpoints,
        "omitted_anchor_timestamps": omitted_anchors,
        "omitted_coverage_count": max(0, baseline_count - baseline_selected),
        "omitted_scene_context_count": omitted_scenes,
        "unsampled_changes_possible": True,
    }


def extract_frames_adaptive(
    video_path: Path,
    frame_dir: Path,
    interval: int,
    max_frames: int = 900,
    anchor_timestamps: list[float] | None = None,
    scene_threshold: float = 0.22,
    batch_size: int = DEFAULT_FRAME_EXTRACT_BATCH_SIZE,
) -> tuple[list[Path], list[FrameSample]]:
    require_ffmpeg()
    ffmpeg = ffmpeg_bin()
    frame_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(video_path)
    if not math.isfinite(duration) or duration <= 0:
        return [], []
    interval = max(1, interval)
    coverage_gap = max(5, interval)
    check = _cancel_check.get() or (lambda: None)
    check()
    scene_timestamps = detect_scene_change_timestamps(
        video_path, threshold=scene_threshold, max_scenes=max_frames,
    )
    plan = _adaptive_frame_plan(duration, interval, max_frames, scene_timestamps, anchor_timestamps)
    batch_size = max(1, min(32, int(batch_size or DEFAULT_FRAME_EXTRACT_BATCH_SIZE)))
    signature = _frame_cache_payload(video_path, plan, interval=interval, scene_threshold=scene_threshold)
    generation = hashlib.sha256(json.dumps(signature, sort_keys=True).encode("utf-8")).hexdigest()
    # The old cache and all its referenced images remain untouched on upgrade.
    cache_path = frame_dir / f"frame_cache_v3_{generation}.json"
    cached = _read_frame_cache(cache_path)
    entries = cached.get("entries")
    cache_valid = cached.get("signature") == signature and isinstance(entries, list) and len(entries) == len(plan)
    if cache_valid:
        previous_digest, previous_timestamp = "", None
        for index, ((timestamp, reasons), entry) in enumerate(zip(plan, entries)):
            if not isinstance(entry, dict) or entry.get("timestamp") != timestamp:
                cache_valid = False
                break
            digest = entry.get("sha256", "")
            if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                cache_valid = False
                break
            important = bool({"scene_change", "content_change", "interaction_context", "playback_anchor", "start", "tail"}.intersection(reasons))
            expected_keep = important or _should_keep_sampled_frame(current_hash=digest, timestamp=timestamp,
                last_hash=previous_digest, last_kept_timestamp=previous_timestamp, coverage_gap=coverage_gap)
            if entry.get("kept") is not expected_keep:
                cache_valid = False
                break
            if expected_keep:
                previous_digest, previous_timestamp = digest, timestamp
            expected = f"frame_{index:04d}_{timestamp:06d}_{digest}.jpg"
            if entry.get("kept") is True:
                path = frame_dir / expected
                if entry.get("name") != expected or path.is_symlink() or not _valid_frame_file(path) or file_sha256(path) != digest:
                    cache_valid = False
                    break
            elif entry.get("kept") is not False or entry.get("name") != "":
                cache_valid = False
                break
    started_at = time.monotonic()
    batch_process_count = fallback_process_count = 0
    frames: list[Path] = []
    samples: list[FrameSample] = []
    failed_timestamps: list[int] = []
    new_entries = []
    last_hash = ""
    last_kept_timestamp = None
    with tempfile.TemporaryDirectory(prefix=".extract-", dir=frame_dir) as temporary:
        staged = [(timestamp, Path(temporary) / f"{index}.jpg") for index, (timestamp, _) in enumerate(plan)]
        if not cache_valid:
            for start in range(0, len(staged), batch_size):
                check()
                requests = staged[start:start + batch_size]
                batch_process_count += 1
                _extract_frame_batch(ffmpeg, video_path, requests)
                check()
                for timestamp, output in requests:
                    if not _valid_frame_file(output):
                        output.unlink(missing_ok=True)
                        fallback_process_count += 1
                        _extract_single_frame(ffmpeg, video_path, timestamp, output)
                        check()
        for index, (timestamp, reasons) in enumerate(plan):
            check()
            if cache_valid:
                entry = entries[index]
                if not entry["kept"]:
                    new_entries.append(entry)
                    continue
                out = frame_dir / entry["name"]
                digest = entry["sha256"]
            else:
                source = staged[index][1]
                if not _valid_frame_file(source):
                    failed_timestamps.append(timestamp)
                    continue
                digest = file_sha256(source)
                out = frame_dir / f"frame_{index:04d}_{timestamp:06d}_{digest}.jpg"
            important = bool({"scene_change", "content_change", "interaction_context", "playback_anchor", "start", "tail"}.intersection(reasons))
            keep = important or _should_keep_sampled_frame(
                current_hash=digest, timestamp=float(timestamp),
                last_hash=last_hash,
                last_kept_timestamp=last_kept_timestamp, coverage_gap=coverage_gap,
            )
            new_entries.append({"timestamp": timestamp, "name": out.name if keep else "", "sha256": digest, "kept": keep})
            if not keep:
                continue
            if not cache_valid:
                _publish_evidence(source, out)
            last_hash, last_kept_timestamp = digest, float(timestamp)
            frames.append(out)
            samples.append(FrameSample(path=str(out), timestamp=float(timestamp), reasons=reasons, important=important, sha256=digest))
        check()
        # An incomplete extraction is never a complete duplicate cache: retry it.
        if not failed_timestamps:
            _write_frame_cache(cache_path, {"signature": signature, "entries": new_entries})
    coverage = _sampling_coverage(duration, interval, max_frames, plan, samples, scene_timestamps, anchor_timestamps)
    if failed_timestamps:
        coverage["status"] = "incomplete"
    metrics = {
        "schema_version": 2,
        "extractor_version": FRAME_EXTRACTOR_VERSION,
        "duplicate_policy": "encoded-sha256-equal-only",
        "source_sha256": signature["source_sha256"],
        "planned_frame_count": len(plan),
        "cached_frame_count": len(frames) if cache_valid else 0,
        "cached_duplicate_skip_count": len(plan) - len(frames) if cache_valid else 0,
        "kept_frame_count": len(frames),
        "failed_timestamps": failed_timestamps,
        "sampling_coverage": coverage,
        "batch_size": batch_size,
        "ffmpeg_batch_process_count": batch_process_count,
        "ffmpeg_fallback_process_count": fallback_process_count,
        "elapsed_ms": round(max(0.0, time.monotonic() - started_at) * 1000),
    }
    _write_frame_cache(frame_dir / "frame_extraction_metrics.json", metrics)
    return frames, samples


def extract_frames(
    video_path: Path,
    frame_dir: Path,
    interval: int,
    max_frames: int = 900,
    anchor_timestamps: list[float] | None = None,
) -> list[Path]:
    frames, _samples = extract_frames_adaptive(
        video_path,
        frame_dir,
        interval,
        max_frames=max_frames,
        anchor_timestamps=anchor_timestamps,
    )
    return frames


def _format_timestamp_label(seconds: float | int) -> str:
    value = max(0, int(seconds or 0))
    return f"{value // 3600:02d}:{(value % 3600) // 60:02d}:{value % 60:02d}"


def _timestamp_from_frame_path(path: Path, fallback: float) -> float:
    match = re.search(r"_(\d{6})(?:\D|$)", path.stem)
    if not match:
        return fallback
    try:
        return float(int(match.group(1)))
    except ValueError:
        return fallback


def _draw_label_box(
    tile: Image.Image,
    label: str,
    *,
    anchor: str,
    xy: tuple[int, int],
    fill: tuple[int, int, int, int],
) -> None:
    draw = ImageDraw.Draw(tile, "RGBA")
    font = ImageFont.load_default()
    pad_x = 6
    pad_y = 4
    bbox = draw.textbbox(xy, label, font=font, anchor=anchor)
    rect = (
        max(0, bbox[0] - pad_x),
        max(0, bbox[1] - pad_y),
        min(tile.width, bbox[2] + pad_x),
        min(tile.height, bbox[3] + pad_y),
    )
    draw.rounded_rectangle(rect, radius=4, fill=fill)
    draw.text(xy, label, font=font, fill=(255, 255, 255, 238), anchor=anchor)


def _draw_tile_labels(tile: Image.Image, timestamp: float, window_index: int, tile_index: int, tile_count: int) -> None:
    _draw_label_box(
        tile,
        f"W{window_index:03d}-{tile_index:02d}/{tile_count:02d}",
        anchor="la",
        xy=(8, 8),
        fill=(23, 105, 232, 210),
    )
    _draw_label_box(
        tile,
        _format_timestamp_label(timestamp),
        anchor="ls",
        xy=(8, tile.height - 8),
        fill=(8, 13, 23, 196),
    )


def build_frame_grids(
    task_id: str,
    frames: list[Path],
    grid_dir: Path,
    columns: int,
    rows: int,
    interval: int,
    media_duration: float | None = None,
) -> list[FrameGrid]:
    grid_dir.mkdir(parents=True, exist_ok=True)
    group_size = max(1, columns * rows)
    grids: list[FrameGrid] = []
    for idx in range(0, len(frames), group_size):
        if _cancel_check.get() is not None:
            _cancel_check.get()()
        group = frames[idx: idx + group_size]
        if not group:
            continue
        canvas = Image.new("RGB", (columns * 320, rows * 180), "white")
        grid_index = idx // group_size
        window_index = grid_index + 1
        tile_count = len(group)
        timestamps = [
            _timestamp_from_frame_path(frame, float((idx + pos) * interval))
            for pos, frame in enumerate(group)
        ]
        for pos, frame in enumerate(group):
            image = Image.open(frame).convert("RGB")
            image = ImageOps.contain(image, (320, 180), Image.Resampling.LANCZOS)
            tile = Image.new("RGB", (320, 180), (8, 13, 23))
            x = (320 - image.width) // 2
            y = (180 - image.height) // 2
            tile.paste(image, (x, y))
            _draw_tile_labels(tile, timestamps[pos], window_index, pos + 1, tile_count)
            canvas.paste(tile, ((pos % columns) * 320, (pos // columns) * 180))
        # Grid composition changes with retained frames. Never overwrite an old
        # grid URL when a new extraction policy changes window membership.
        with tempfile.TemporaryDirectory(prefix=".grid-", dir=grid_dir) as temporary:
            staged_grid = Path(temporary) / "grid.jpg"
            canvas.save(staged_grid, quality=82)
            path = grid_dir / f"grid_{grid_index:03d}_{file_sha256(staged_grid)}.jpg"
            _publish_evidence(staged_grid, path)
        start = min(timestamps) if timestamps else float(idx * interval)
        end = max(timestamp + max(1, interval) for timestamp in timestamps) if timestamps else float((idx + len(group)) * interval)
        if media_duration is not None and media_duration > 0:
            end = min(end, float(media_duration))
        end = max(start, end)
        rel_url = f"/api/tasks/{task_id}/assets/{path.name}"
        grids.append(
            FrameGrid(
                path=str(path),
                url=f"{BACKEND_ORIGIN}{rel_url}",
                start=start,
                end=end,
                frame_count=len(group),
                frame_timestamps=timestamps,
                frame_paths=[str(frame) for frame in group],
            )
        )
    return grids


def image_to_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"
