from __future__ import annotations

import base64
import hashlib
import json
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
) -> bool:
    if not last_hash or last_kept_timestamp is None:
        return True
    is_duplicate = current_hash == last_hash or (
        last_average_hash is not None
        and _hamming_distance(current_average_hash, last_average_hash) <= 1
    )
    if not is_duplicate:
        return True
    return timestamp - last_kept_timestamp >= max(1, coverage_gap)


def extract_frames(video_path: Path, frame_dir: Path, interval: int, max_frames: int = 900) -> list[Path]:
    require_ffmpeg()
    ffmpeg = ffmpeg_bin()
    frame_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(video_path)
    if duration <= 0:
        return []
    interval = max(1, interval)
    coverage_gap = max(5, interval)
    timestamps = list(range(0, int(duration), interval))[:max_frames]
    frames: list[Path] = []
    last_hash = ""
    last_average_hash: int | None = None
    last_kept_timestamp: float | None = None
    for index, ts in enumerate(timestamps):
        out = frame_dir / f"frame_{index:04d}_{ts:06d}.jpg"
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                str(ts),
                "-i",
                str(video_path),
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
        if not _should_keep_sampled_frame(
            current_hash=current_hash,
            current_average_hash=current_average_hash,
            timestamp=float(ts),
            last_hash=last_hash,
            last_average_hash=last_average_hash,
            last_kept_timestamp=last_kept_timestamp,
            coverage_gap=coverage_gap,
        ):
            out.unlink(missing_ok=True)
            continue
        last_hash = current_hash
        last_average_hash = current_average_hash
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


def _draw_tile_timestamp(tile: Image.Image, timestamp: float) -> None:
    label = _format_timestamp_label(timestamp)
    draw = ImageDraw.Draw(tile, "RGBA")
    font = ImageFont.load_default()
    left = 8
    bottom = tile.height - 8
    bbox = draw.textbbox((left, bottom), label, font=font, anchor="ls")
    pad_x = 6
    pad_y = 4
    rect = (
        max(0, bbox[0] - pad_x),
        max(0, bbox[1] - pad_y),
        min(tile.width, bbox[2] + pad_x),
        min(tile.height, bbox[3] + pad_y),
    )
    draw.rounded_rectangle(rect, radius=4, fill=(8, 13, 23, 196))
    draw.text((left, bottom), label, font=font, fill=(255, 255, 255, 236), anchor="ls")


def build_frame_grids(
    task_id: str,
    frames: list[Path],
    grid_dir: Path,
    columns: int,
    rows: int,
    interval: int,
) -> list[FrameGrid]:
    grid_dir.mkdir(parents=True, exist_ok=True)
    group_size = max(1, columns * rows)
    grids: list[FrameGrid] = []
    for idx in range(0, len(frames), group_size):
        group = frames[idx: idx + group_size]
        if not group:
            continue
        canvas = Image.new("RGB", (columns * 320, rows * 180), "white")
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
            _draw_tile_timestamp(tile, timestamps[pos])
            canvas.paste(tile, ((pos % columns) * 320, (pos // columns) * 180))
        grid_index = idx // group_size
        path = grid_dir / f"grid_{grid_index:03d}.jpg"
        canvas.save(path, quality=82)
        start = min(timestamps) if timestamps else float(idx * interval)
        end = max(timestamp + max(1, interval) for timestamp in timestamps) if timestamps else float((idx + len(group)) * interval)
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
