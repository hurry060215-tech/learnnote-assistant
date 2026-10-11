"""Opt-in, local hard-subtitle OCR with verified, atomic window checkpoints.

Only a bounded decoder lookahead, one crop and one window are held at a time. Every
sample, including blank frames, stays in the checkpoint. Cue timing describes
sample observations, not exact subtitle onset or verified speech.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading

from .local_ocr import _normalize_lines
from .models import ScreenSubtitleSettings, TranscriptResult, TranscriptSegment
from .ocr_runtime import create_ocr_engine

SCHEMA = 1
ALGORITHM = "screen-ocr-v3-rgb-displayed-frame"
WINDOW_SECONDS = 60
MAX_WINDOW_BYTES = 16 * 1024 * 1024
WARNING = "画面字幕为本地 OCR 自动识别，未人工核验，不是已验证的讲者原话。时间点为抽样估计；短暂字幕、裁剪外文字及识别错误可能遗漏。置信度不是正确率。"
_preview_lock = threading.Lock()


class ScreenOcrError(ValueError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _durable_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def media_hash(path: Path, cancel_check=lambda: None):
    digest = hashlib.sha256()
    before = path.stat()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            cancel_check()
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ScreenOcrError("media_changed")
    return digest.hexdigest()


def engine_identity():
    """Hash the actual bundled models/config as well as runtime versions."""
    versions = {}
    for package in ("rapidocr-onnxruntime", "onnxruntime", "av", "Pillow"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ScreenOcrError("ocr_unavailable") from exc
    spec = importlib.util.find_spec("rapidocr_onnxruntime")
    root = Path(spec.origin).parent
    files = sorted([*root.rglob("*.onnx"), *root.rglob("*.yaml")])
    if not files:
        raise ScreenOcrError("ocr_models_missing")
    return {"algorithm": ALGORITHM, "packages": versions,
            "models": {str(path.relative_to(root)): media_hash(path) for path in files}}


def media_info(path: Path):
    import av
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ScreenOcrError("video_stream_missing")
        stream = container.streams.video[0]
        duration = float(stream.duration * stream.time_base) if stream.duration is not None else float(container.duration or 0) / av.time_base
        if not math.isfinite(duration) or duration <= 0:
            raise ScreenOcrError("video_duration_unknown")
        width, height = stream.codec_context.width, stream.codec_context.height
        # Avoid a malicious or unsupported gigantic frame allocation.
        if width <= 0 or height <= 0 or width * height > 3840 * 2160:
            raise ScreenOcrError("video_dimensions_unsupported")
        return {"duration": duration, "width": width, "height": height,
                "time_base": str(stream.time_base), "start_time": stream.start_time,
                "codec": stream.codec_context.name}


def crop_box(width, height, settings):
    box = (int(width * settings.crop_left), int(height * settings.crop_top),
           int(width * settings.crop_right), int(height * settings.crop_bottom))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        raise ScreenOcrError("crop_too_small")
    return box


def sample_frames(path, targets, settings, cancel_check=lambda: None):
    """Seek once, then sample the frame displayed at each requested time.

    A single decoded frame may cover several sample points in low-frame-rate
    recordings. Keep one lookahead frame to establish that display interval;
    never stretch the last frame beyond its own duration to fill a broken tail.
    """
    import av
    if not targets:
        return
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "SLICE"
        stream.codec_context.thread_count = 2
        origin = float((stream.start_time or 0) * stream.time_base)
        container.seek(max(0, int((targets[0] + origin) / stream.time_base)), stream=stream, backward=True)
        index, previous, previous_position = 0, None, None
        rate = float(stream.average_rate or 0)

        def observations(frame, position, boundary):
            nonlocal index
            crop = box = None
            while index < len(targets) and targets[index] < boundary - 1e-7:
                cancel_check()
                if targets[index] + 1e-7 < position:
                    raise ScreenOcrError("video_timestamp_gap")
                if crop is None:
                    if frame.width * frame.height > 3840 * 2160:
                        raise ScreenOcrError("video_dimensions_unsupported")
                    image = frame.to_image()
                    box = crop_box(image.width, image.height, settings)
                    crop = image.crop(box)
                yield targets[index], position, crop, box
                index += 1

        for frame in container.decode(stream):
            cancel_check()
            if frame.pts is None:
                continue
            position = float(frame.pts * stream.time_base) - origin
            if previous is not None:
                if position <= previous_position:
                    raise ScreenOcrError("video_timestamp_order")
                yield from observations(previous, previous_position, position)
                if index == len(targets):
                    return
            previous, previous_position = frame, position
        if previous is not None:
            duration = float((getattr(previous, "duration", 0) or 0) * stream.time_base)
            if duration <= 0 and rate > 0:
                duration = 1 / rate
            yield from observations(previous, previous_position, previous_position + duration)
        if index != len(targets):
            raise ScreenOcrError("video_truncated")


def recognize(image, box, settings, engine):
    import numpy as np
    raw, _ = engine(np.asarray(image)[:, :, ::-1].copy())
    if raw is not None and (not isinstance(raw, (tuple, list)) or len(raw) > 200):
        raise ScreenOcrError("ocr_output_truncated")
    if any(len(str(item[1])) > 2000 for item in (raw or [])):
        raise ScreenOcrError("ocr_output_truncated")
    lines = _normalize_lines(raw or [])
    for line in lines:
        line["bbox"] = [[x + box[0], y + box[1]] for x, y in line["bbox"]]
        line["selected"] = settings.language == "auto" or bool(re.search(r"[\u3400-\u9fff]" if settings.language == "zh" else r"[A-Za-z]", line["text"]))
    # Retain excluded lines in raw observations for review/re-filtering.
    return sorted(lines, key=lambda line: (min(p[1] for p in line["bbox"]), min(p[0] for p in line["bbox"])))


def preview(path, settings, timestamp=0):
    if not _preview_lock.acquire(blocking=False):
        raise ScreenOcrError("preview_busy")
    try:
        return _preview(path, settings, timestamp)
    finally:
        _preview_lock.release()


def _preview(path, settings, timestamp):
    info = media_info(path)
    if not math.isfinite(timestamp) or not 0 <= timestamp < info["duration"]:
        raise ScreenOcrError("preview_outside_video")
    engine = create_ocr_engine()
    for target, position, image, box in sample_frames(path, [timestamp], settings):
        lines = recognize(image, box, settings, engine)
        output = io.BytesIO()
        image.thumbnail((1280, 720))
        image.save(output, format="JPEG", quality=85)
        return {"timestamp": target, "frame_timestamp": position, "crop_pixels": box,
                "image_url": "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii"),
                "lines": lines, "warning": WARNING, "media": info}


def _targets(start, end, interval):
    # Integer indices avoid cumulative floating-point drift between windows.
    first = math.ceil((start - 1e-9) / interval)
    last = math.ceil((end - 1e-9) / interval)
    return [round(index * interval, 9) for index in range(first, last)]


def _read_window(path, fingerprint, start, end, targets):
    if path.stat().st_size > MAX_WINDOW_BYTES:
        raise ValueError("oversized_checkpoint")
    payload = json.loads(path.read_text(encoding="utf-8"))
    checksum = payload.pop("sha256")
    if _digest(payload) != checksum or payload["fingerprint"] != fingerprint or payload["range"] != [start, end] or payload["complete"] is not True:
        raise ValueError("incompatible_checkpoint")
    samples = payload["samples"]
    if [sample["timestamp"] for sample in samples] != targets:
        raise ValueError("incomplete_checkpoint")
    for sample in samples:
        if sample["status"] not in {"text_detected", "no_text", "filtered"}:
            raise ValueError("incomplete_checkpoint")
        if not math.isfinite(sample["frame_timestamp"]):
            raise ValueError("invalid_checkpoint")
        for line in sample["lines"]:
            _normalize_lines([(line["bbox"], line["text"], line["confidence"])])
            if not isinstance(line["selected"], bool):
                raise ValueError("invalid_checkpoint")
    return samples


def _merge(cues, samples, interval, duration):
    for sample in samples:
        selected = [line for line in sample["lines"] if line["selected"]]
        text = "\n".join(line["text"] for line in selected)
        if not text:
            continue
        start, end = sample["timestamp"], min(duration, sample["timestamp"] + interval)
        confidence = min(line["confidence"] for line in selected)
        # Exact consecutive duplicates only: blank observations create a gap,
        # and changes (including punctuation) always create a new cue.
        if cues and cues[-1]["text"] == text and abs(cues[-1]["end"] - start) < 1e-6:
            cues[-1]["end"] = end
            cues[-1]["confidence"] = min(cues[-1]["confidence"], confidence)
            cues[-1]["sample_count"] += 1
        else:
            cues.append({"start": start, "end": end, "text": text, "confidence": confidence,
                         "sample_count": 1, "verification": "unreviewed", "lines": selected})


def extract(path: Path, settings: ScreenSubtitleSettings, cache_dir: Path, *, cancel_check=lambda: None,
            progress=lambda report: None, engine=None, identity=None, window_seconds=WINDOW_SECONDS, expected_media_sha256=None):
    info = media_info(path)
    crop_box(info["width"], info["height"], settings)
    identity = identity if identity is not None else engine_identity()
    digest = media_hash(path, cancel_check)
    if expected_media_sha256 and digest != expected_media_sha256:
        raise ScreenOcrError("media_changed")
    original_stat = (path.stat().st_size, path.stat().st_mtime_ns)
    manifest = {"schema_version": SCHEMA, "media_sha256": digest, "media": info,
                "settings": settings.model_dump(mode="json"), "engine": identity,
                "range": [0.0, info["duration"]], "window_seconds": window_seconds}
    fingerprint = _digest(manifest)
    root = cache_dir / fingerprint
    invalid_manifest = False
    if (root / "manifest.json").exists():
        try:
            saved_manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            invalid_manifest = saved_manifest != manifest
        except (OSError, ValueError):
            invalid_manifest = True
    _durable_write(root / "manifest.json", _json(manifest))
    report = {**manifest, "fingerprint": fingerprint, "status": "running", "source": "screen-ocr",
              "completed_windows": 0, "total_windows": math.ceil(info["duration"] / window_seconds),
              "cache_hits": 0, "invalid_cache_windows": [], "failed_windows": [], "cues": [],
              "invalid_cache_manifest": invalid_manifest,
              "sample_count": 0, "text_sample_count": 0, "remote_calls": 0, "warning": WARNING,
              "coverage": {"complete": False, "sampled_seconds": 0.0, "requested_seconds": info["duration"], "sampled_ranges": []}}
    progress(report)
    for index in range(report["total_windows"]):
        cancel_check()
        start, end = float(index * window_seconds), min(info["duration"], float((index + 1) * window_seconds))
        targets = _targets(start, end, settings.interval_seconds)
        checkpoint = root / f"window-{index:06d}.json"
        try:
            if invalid_manifest:
                raise ValueError("incompatible_checkpoint_manifest")
            samples = _read_window(checkpoint, fingerprint, start, end, targets)
            report["cache_hits"] += 1
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
            if checkpoint.exists():
                report["invalid_cache_windows"].append(index)
            samples = []
            sample_bytes = 0
            try:
                if engine is None:
                    engine = create_ocr_engine()
                for target, position, image, box in sample_frames(path, targets, settings, cancel_check):
                    cancel_check()
                    lines = recognize(image, box, settings, engine)
                    cancel_check()
                    samples.append({"timestamp": target, "frame_timestamp": position, "lines": lines,
                                    "status": "text_detected" if any(line["selected"] for line in lines) else "filtered" if lines else "no_text"})
                    sample_bytes += len(_json(samples[-1]).encode("utf-8"))
                    if sample_bytes > MAX_WINDOW_BYTES - 1024:
                        raise ScreenOcrError("ocr_output_truncated")
                if len(samples) != len(targets):
                    raise ScreenOcrError("video_truncated")
                if (path.stat().st_size, path.stat().st_mtime_ns) != original_stat:
                    raise ScreenOcrError("media_changed")
                payload = {"fingerprint": fingerprint, "range": [start, end], "complete": True, "samples": samples}
                serialized = _json({**payload, "sha256": _digest(payload)})
                if len(serialized.encode("utf-8")) > MAX_WINDOW_BYTES:
                    raise ScreenOcrError("ocr_output_truncated")
                _durable_write(checkpoint, serialized)
            except Exception as exc:
                cancel_check()  # Cancellation is never treated as a blank/failed OCR frame.
                from .processor_state import TaskCancelled
                if isinstance(exc, TaskCancelled):
                    raise
                report["failed_windows"].append({"index": index, "range": [start, end], "error": str(exc) if isinstance(exc, ScreenOcrError) else type(exc).__name__})
                report["status"] = "partial" if report["completed_windows"] else "failed"
                progress(report)
                return report
        _merge(report["cues"], samples, settings.interval_seconds, info["duration"])
        report["completed_windows"] += 1
        report["sample_count"] += len(samples)
        report["text_sample_count"] += sum(sample["status"] == "text_detected" for sample in samples)
        report["coverage"]["sampled_seconds"] += end - start
        report["coverage"]["sampled_ranges"].append([start, end])
        progress(report)
    cancel_check()
    if (path.stat().st_size, path.stat().st_mtime_ns) != original_stat:
        raise ScreenOcrError("media_changed")
    report["coverage"]["complete"] = True
    report["status"] = "ready" if report["cues"] else "empty"
    progress(report)
    return report


def as_transcript(report):
    return TranscriptResult(source="screen-ocr", language=report["settings"]["language"], warning=report["warning"],
        segments=[TranscriptSegment(start=cue["start"], end=cue["end"], text=cue["text"]) for cue in report["cues"]],
        full_text="\n".join(cue["text"] for cue in report["cues"]),
        provenance={"kind": "screen-ocr", "verification": "unreviewed", "fingerprint": report["fingerprint"],
                    "media_sha256": report["media_sha256"], "settings": report["settings"], "engine": report["engine"],
                    "coverage": report["coverage"], "status": report["status"],
                    "observations": "screen-subtitles-cache/<fingerprint>/window-*.json"})


def read_observations(cache_dir, fingerprint, index):
    if not re.fullmatch(r"[a-f0-9]{64}", fingerprint) or index < 0:
        raise ValueError("invalid_checkpoint")
    root = cache_dir / fingerprint
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if _digest(manifest) != fingerprint:
        raise ValueError("incompatible_checkpoint")
    duration, size = manifest["media"]["duration"], manifest["window_seconds"]
    start, end = float(index * size), min(duration, float((index + 1) * size))
    if start >= end:
        raise ValueError("invalid_checkpoint")
    targets = _targets(start, end, manifest["settings"]["interval_seconds"])
    return {"source": "screen-ocr", "verification": "unreviewed", "range": [start, end],
            "fingerprint": fingerprint, "samples": _read_window(root / f"window-{index:06d}.json", fingerprint, start, end, targets)}
