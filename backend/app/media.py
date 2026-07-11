from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .config import BACKEND_ORIGIN
from .models import FrameGrid
from .runtime import ffmpeg_bin, ffprobe_bin


class MediaProcessingError(RuntimeError):
    pass


def _run(cmd: list[str], message: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
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
            text=True,
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
        text=True,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr or "")
    if not match:
        return 0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def normalize_video(input_path: Path, output_path: Path) -> Path:
    require_ffmpeg()
    ffmpeg = ffmpeg_bin()
    if input_path.resolve() == output_path.resolve():
        return input_path
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
            str(output_path),
        ],
        "视频标准化失败",
    )
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
            "-c",
            "copy",
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
        text=True,
    )
    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
        output_path.unlink(missing_ok=True)
        return None
    text = output_path.read_text(encoding="utf-8-sig", errors="replace")
    if "-->" not in text:
        output_path.unlink(missing_ok=True)
        return None
    return output_path


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _average_hash(path: Path, size: int = 8) -> int:
    with Image.open(path) as image:
        pixels = list(
            image.convert("L")
            .resize((size, size), Image.Resampling.LANCZOS)
            .getdata()
        )
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
        pixels = list(image.convert("L").resize((16, 16), Image.Resampling.BILINEAR).getdata())
    if not pixels:
        return 0.0
    return sum(pixels) / len(pixels)


def _hamming_distance(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def _should_keep_sampled_frame(
    *,
    current_hash: str,
    current_average_hash: int,
    timestamp: float,
    last_hash: str,
    last_average_hash: int | None,
    last_kept_timestamp: float | None,
    coverage_gap: int,
    current_mean_luma: float | None = None,
    last_mean_luma: float | None = None,
) -> bool:
    if not last_hash or last_kept_timestamp is None:
        return True
    exact_duplicate = current_hash == last_hash
    near_duplicate = last_average_hash is not None and _hamming_distance(current_average_hash, last_average_hash) <= 1
    if near_duplicate and current_mean_luma is not None and last_mean_luma is not None:
        near_duplicate = abs(current_mean_luma - last_mean_luma) <= 8
    is_duplicate = exact_duplicate or near_duplicate
    if not is_duplicate:
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


def _sample_frame_timestamps(
    duration: float,
    interval: int,
    max_frames: int = 900,
    anchor_timestamps: list[float] | None = None,
) -> list[int]:
    if duration <= 0 or max_frames <= 0:
        return []
    interval = max(1, int(interval or 1))
    duration_int = int(duration)
    timestamps = list(range(0, duration_int, interval))
    if not timestamps:
        timestamps = [0]

    tail = max(0, int(duration) - 1)
    tail_gap = tail - timestamps[-1]
    if tail > timestamps[-1] and tail_gap >= max(5, int(interval * 0.5)):
        timestamps.append(tail)

    anchors = _normalize_frame_anchor_timestamps(duration, anchor_timestamps)
    if not anchors:
        return timestamps[:max_frames]

    selected = anchors[:max_frames]
    if len(selected) < max_frames:
        selected.extend(timestamp for timestamp in timestamps if timestamp not in anchors)
    return sorted(selected[:max_frames])


def extract_frames(
    video_path: Path,
    frame_dir: Path,
    interval: int,
    max_frames: int = 900,
    anchor_timestamps: list[float] | None = None,
) -> list[Path]:
    require_ffmpeg()
    ffmpeg = ffmpeg_bin()
    frame_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(video_path)
    if duration <= 0:
        return []
    interval = max(1, interval)
    coverage_gap = max(5, interval)
    timestamps = _sample_frame_timestamps(duration, interval, max_frames, anchor_timestamps)
    anchor_set = set(_normalize_frame_anchor_timestamps(duration, anchor_timestamps))
    frames: list[Path] = []
    last_hash = ""
    last_average_hash: int | None = None
    last_mean_luma: float | None = None
    last_kept_timestamp: float | None = None
    for index, ts in enumerate(timestamps):
        out = frame_dir / f"frame_{index:04d}_{ts:06d}.jpg"
        seek_start = max(0, ts - 3)
        precise_offset = ts - seek_start
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
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not out.exists():
            continue
        current_hash = _md5(out)
        current_average_hash = _average_hash(out)
        current_mean_luma = _mean_luma(out)
        if ts not in anchor_set and not _should_keep_sampled_frame(
            current_hash=current_hash,
            current_average_hash=current_average_hash,
            current_mean_luma=current_mean_luma,
            timestamp=float(ts),
            last_hash=last_hash,
            last_average_hash=last_average_hash,
            last_mean_luma=last_mean_luma,
            last_kept_timestamp=last_kept_timestamp,
            coverage_gap=coverage_gap,
        ):
            out.unlink(missing_ok=True)
            continue
        last_hash = current_hash
        last_average_hash = current_average_hash
        last_mean_luma = current_mean_luma
        last_kept_timestamp = float(ts)
        frames.append(out)
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
        path = grid_dir / f"grid_{grid_index:03d}.jpg"
        canvas.save(path, quality=82)
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
            )
        )
    return grids


def image_to_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"
