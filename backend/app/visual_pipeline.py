"""Visual evidence extraction and index persistence for video tasks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import BACKEND_ORIGIN
from .media import build_frame_grids, extract_frames_adaptive
from .models import FrameGrid, FrameSample, TaskOptions
from .processor_state import check_cancel
from .storage import write_json
from .storage import update_task


@dataclass
class VisualArtifacts:
    frames: list[Path]
    frame_samples: list[FrameSample]
    grids: list[FrameGrid]
    warning: str
    visual_index_path: str = ""


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
    if options.visual_understanding:
        update_task(task_id, phase="extracting_frames", progress=68, message="正在抽帧并生成画面网格")
        work_dir = normalized_path.parent
        frame_dir = work_dir / "frames"
        grid_dir = work_dir / "grids"
        extract_frames_runner = extract_frames_fn or extract_frames_adaptive
        build_grids_runner = build_grids_fn or build_frame_grids
        frames, frame_samples = extract_frames_runner(
            normalized_path,
            frame_dir,
            max(1, options.frame_interval),
            max_frames=max(60, min(2400, int(options.max_frame_count) // (2 if options.low_resource_mode else 1))),
            anchor_timestamps=frame_anchor_timestamps,
        )
        for sample in frame_samples:
            sample.url = f"{BACKEND_ORIGIN}/api/tasks/{task_id}/frames/{Path(sample.path).name}"
        check_cancel(task_id)
        grids = build_grids_runner(
            task_id,
            frames,
            grid_dir,
            max(1, options.grid_columns),
            max(1, options.grid_rows),
            max(1, options.frame_interval),
            media_duration=media_duration,
        )
        important_paths = {sample.path for sample in frame_samples if sample.important}
        for grid in grids:
            grid.important_frame_paths = [path for path in grid.frame_paths if path in important_paths]
        if not frames:
            frame_extraction_warning = (
                "已启用画面理解，但未能从完整视频提取任何画面帧；本任务没有视觉切片，"
                "请检查视频是否包含可解码的视频轨道。"
            )

    return VisualArtifacts(frames, frame_samples, grids, frame_extraction_warning)


def write_visual_index(
    task_id: str,
    title: str,
    page_url: str,
    frame_samples: list[FrameSample],
    visual_windows: list,
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
            "important_frames": [sample.model_dump(mode="json") for sample in frame_samples if sample.important],
            "frames": [sample.model_dump(mode="json") for sample in frame_samples],
            "windows": [window.model_dump(mode="json") for window in visual_windows],
        },
    )
    return str(visual_index_path)


__all__ = ["VisualArtifacts", "extract_visual_evidence", "write_visual_index"]
