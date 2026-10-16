"""Visual evidence extraction and index persistence for video tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from pathlib import Path

from .config import BACKEND_ORIGIN
from .media import FRAME_EXTRACTOR_VERSION, MediaProcessingError, build_frame_grids, extract_frames_adaptive, file_sha256, media_cancellation
from .models import FrameGrid, FrameSample, TaskOptions, VisualWindow
from .processor_state import check_cancel
from .storage import write_json
from .storage import update_task
from .storage import task_dir, get_task
from .local_ocr import recognize_frames
from .task_paths import native_task_artifact, TaskArtifactUnavailable
from .processor_state import TaskCancelled


@dataclass
class VisualArtifacts:
    frames: list[Path]
    frame_samples: list[FrameSample]
    grids: list[FrameGrid]
    warning: str
    visual_index_path: str = ""
    metrics: dict = field(default_factory=dict)


def _preserved_visual_evidence(work_dir: Path, media: Path, task=None) -> VisualArtifacts | None:
    """Do not remap existing W IDs merely because the extraction policy changed."""
    index_path = work_dir / "visual_index.json"
    try:
        index_path = native_task_artifact(work_dir, work_dir.name, str(index_path))
    except TaskArtifactUnavailable as exc:
        if exc.reason == "missing_destination" and not (task is not None and (task.visual_windows or task.frame_grids or task.visual_index_path)):
            return None
        raise MediaProcessingError("已发布画面索引缺失或无法校验，已停止重新抽帧并保留现有引用；请从保存的媒体创建新任务。") from exc
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(index, dict):
            raise ValueError("invalid index")
        metrics = index.get("performance") or {}
        if not isinstance(metrics, dict):
            raise ValueError("invalid metrics")
        extraction = metrics.get("frame_extraction") or {}
        if extraction.get("extractor_version") not in (None, "", "adaptive-batch-v2", FRAME_EXTRACTOR_VERSION):
            raise ValueError("unsupported sampling version")
        if not index.get("windows"):
            if task is not None and (task.visual_windows or task.frame_grids):
                raise ValueError("published windows missing from index")
            return None
        source_hash = extraction.get("source_sha256") if extraction.get("extractor_version") == FRAME_EXTRACTOR_VERSION else None
        if not source_hash:
            cache_path = native_task_artifact(work_dir, work_dir.name,
                str(work_dir / "frames" / "frame_cache.json"), directory="frames")
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            signature = cache["signature"]
            source_hash = signature.get("source_sha256") if signature.get("extractor_version") == "adaptive-batch-v2" else None
        if not source_hash or source_hash != file_sha256(media):
            raise ValueError("unverified source")
        samples = [FrameSample.model_validate(value) for value in index["frames"]]
        if not samples:
            raise ValueError("missing frames")
        for sample in samples:
            path = native_task_artifact(work_dir, work_dir.name, sample.path, directory="frames")
            if not sample.sha256 or file_sha256(path) != sample.sha256:
                raise ValueError("unverified frame")
        if task is not None:
            def window_identity(window):
                return (window.id, window.start, window.end, window.grid_path, window.grid_url, window.frame_timestamps)
            indexed = [VisualWindow.model_validate(value) for value in index.get("windows", [])]
            if [window_identity(window) for window in indexed] != [window_identity(window) for window in task.visual_windows]:
                raise ValueError("published windows differ from index")
        grids = []
        for position, raw_window in enumerate(index.get("windows", []), start=1):
            window = VisualWindow.model_validate(raw_window)
            path = native_task_artifact(work_dir, work_dir.name, window.grid_path, directory="grids")
            if window.id != f"W{position:03d}":
                raise ValueError("unverified window")
            members = [sample for sample in samples if sample.timestamp in window.frame_timestamps]
            if len(members) != window.frame_count:
                raise ValueError("unverified membership")
            grids.append(FrameGrid(path=str(path), url=window.grid_url, start=window.start, end=window.end,
                frame_count=window.frame_count, frame_timestamps=window.frame_timestamps,
                frame_paths=[sample.path for sample in members], important_frame_paths=[sample.path for sample in members if sample.important]))
        if task is not None and task.frame_grids:
            def grid_identity(grid):
                return (grid.path, grid.url, grid.start, grid.end, grid.frame_count, grid.frame_timestamps)
            if [grid_identity(grid) for grid in grids] != [grid_identity(grid) for grid in task.frame_grids]:
                raise ValueError("published grids differ from index")
        if not grids:
            raise ValueError("missing windows")
        metrics = {**metrics, "published_sampling_reused": True, "grid_build_ms": 0,
            "frame_extract_wall_ms": 0, "frame_count": len(samples), "grid_count": len(grids),
            "frame_extraction": {**extraction, "cached_frame_count": len(samples),
                "ffmpeg_batch_process_count": 0, "ffmpeg_fallback_process_count": 0,
                "elapsed_ms": 0}}
        return VisualArtifacts([Path(sample.path) for sample in samples], samples, grids,
            "已复用此任务原有画面采样和窗口，保留旧引用；如需采用新的采样规则，请从保存的媒体创建新任务。", metrics=metrics)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise MediaProcessingError("旧画面证据无法完整校验，已停止重新抽帧并保留原文件和引用；请从保存的媒体创建新任务。") from exc


def extract_visual_evidence(
    task_id: str,
    normalized_path: Path,
    title: str,
    page_url: str,
    options: TaskOptions,
    media_duration: float,
    frame_anchor_timestamps: list[float] | None = None,
    extract_frames_fn=None,
    build_grids_fn=None,
) -> VisualArtifacts:
    frames: list[Path] = []
    frame_samples: list[FrameSample] = []
    grids: list[FrameGrid] = []
    frame_extraction_warning = ""
    metrics: dict = {
        "schema_version": 1,
        "enabled": bool(options.visual_understanding),
        "frame_extraction": {},
        "grid_build_ms": 0,
    }
    if options.visual_understanding or options.local_ocr:
        work_dir = normalized_path.parent
        preserved = _preserved_visual_evidence(work_dir, normalized_path, get_task(task_id))
        if preserved is not None:
            check_cancel(task_id)
            if not options.visual_understanding:
                preserved.grids = []
            return _with_local_ocr(task_id, options, preserved)
        update_task(task_id, phase="extracting_frames", progress=68, message="正在抽帧并生成画面网格")
        frame_dir = work_dir / "frames"
        grid_dir = work_dir / "grids"
        extract_frames_runner = extract_frames_fn or extract_frames_adaptive
        build_grids_runner = build_grids_fn or build_frame_grids
        extract_started_at = time.monotonic()
        with media_cancellation(lambda: check_cancel(task_id)):
            frames, frame_samples = extract_frames_runner(
                normalized_path,
                frame_dir,
                max(1, options.frame_interval),
                max_frames=min(24, options.ocr_frame_limit * 2) if options.local_ocr and not options.visual_understanding else max(60, min(2400, int(options.max_frame_count) // (2 if options.low_resource_mode else 1))),
                anchor_timestamps=frame_anchor_timestamps,
                batch_size=1 if options.low_resource_mode else options.frame_extract_batch_size,
            )
        metrics["frame_extract_wall_ms"] = round(max(0.0, time.monotonic() - extract_started_at) * 1000)
        try:
            extraction_metrics = json.loads((frame_dir / "frame_extraction_metrics.json").read_text(encoding="utf-8"))
            if isinstance(extraction_metrics, dict):
                metrics["frame_extraction"] = extraction_metrics
        except (OSError, ValueError):
            pass
        for sample in frame_samples:
            sample.url = f"{BACKEND_ORIGIN}/api/tasks/{task_id}/frames/{Path(sample.path).name}"
        check_cancel(task_id)
        grid_started_at = time.monotonic()
        with media_cancellation(lambda: check_cancel(task_id)):
            grids = build_grids_runner(
                task_id,
                frames,
                grid_dir,
                max(1, options.grid_columns),
                max(1, options.grid_rows),
                max(1, options.frame_interval),
                media_duration=media_duration,
            )
        metrics["grid_build_ms"] = round(max(0.0, time.monotonic() - grid_started_at) * 1000)
        important_paths = {sample.path for sample in frame_samples if sample.important}
        for grid in grids:
            grid.important_frame_paths = [path for path in grid.frame_paths if path in important_paths]
        if not frames:
            frame_extraction_warning = (
                "已启用画面理解，但未能从完整视频提取任何画面帧；本任务没有视觉切片，"
                "请检查视频是否包含可解码的视频轨道。"
            )
        else:
            sampling = metrics["frame_extraction"].get("sampling_coverage") or {}
            if sampling.get("status") == "incomplete":
                frame_extraction_warning = "部分计划画面未能提取，或预算不足以保留首尾；现有切片不代表完整画面覆盖。"
            elif sampling.get("budget_limited"):
                frame_extraction_warning = "已达到抽帧预算，部分采样点或播放定位未保留；现有切片不代表完整画面覆盖。"

    metrics["frame_count"] = len(frames)
    metrics["grid_count"] = len(grids)
    return _with_local_ocr(task_id, options, VisualArtifacts(frames, frame_samples, grids, frame_extraction_warning, metrics=metrics))


def _with_local_ocr(task_id: str, options: TaskOptions, artifacts: VisualArtifacts) -> VisualArtifacts:
    if options.local_ocr and artifacts.frame_samples:
        update_task(task_id, phase="extracting_frames", message="正在本地识别关键画面文字")
        try:
            ocr = recognize_frames(artifacts.frame_samples, limit=options.ocr_frame_limit, cancel_check=lambda: check_cancel(task_id), cache_dir=task_dir(task_id) / "ocr-cache")
        except TaskCancelled:
            raise
        except Exception as exc:
            ocr = {"schema_version": 1, "status": "failed", "frames": [], "error_type": type(exc).__name__, "warning": "本地OCR未完成；字幕和画面索引仍然可用。"}
        write_json(task_id, "ocr.json", ocr)
        artifacts.metrics["ocr"] = {key: value for key, value in ocr.items() if key != "frames"}
    # OCR-only frames must never enter the vision-model request path.
    if not options.visual_understanding:
        artifacts.grids = []
    return artifacts


def write_visual_index(
    task_id: str,
    title: str,
    page_url: str,
    frame_samples: list[FrameSample],
    visual_windows: list,
    extraction_metrics: dict | None = None,
) -> str:
    visual_index_path = write_json(
        task_id,
        "visual_index.json",
        {
            "task_id": task_id,
            "title": title,
            "page_url": page_url,
            "sampling": {
                "strategy": "scene-change-plus-coverage",
                "scene_threshold": 0.22,
                "sample_count": len(frame_samples),
                "important_frame_count": sum(sample.important for sample in frame_samples),
            },
            "performance": dict(extraction_metrics or {}),
            "important_frames": [sample.model_dump(mode="json") for sample in frame_samples if sample.important],
            "frames": [sample.model_dump(mode="json") for sample in frame_samples],
            "windows": [window.model_dump(mode="json") for window in visual_windows],
        },
    )
    return str(visual_index_path)


__all__ = ["VisualArtifacts", "extract_visual_evidence", "write_visual_index"]
