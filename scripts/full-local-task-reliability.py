from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_long_video_helpers():
    path = ROOT / "scripts" / "long-video-reliability.py"
    spec = importlib.util.spec_from_file_location("learnnote_long_video", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load long-video helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one complete local LearnNote task on synthetic media without an API key.")
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "test-runs" / "full-local-task")
    args = parser.parse_args()
    if args.duration_seconds < 5:
        parser.error("--duration-seconds must be at least 5")

    output_dir = args.output_dir.expanduser().resolve()
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["LEARNNOTE_DATA_DIR"] = str(data_dir)
    os.environ["LEARNNOTE_DEPLOYMENT_MODE"] = "desktop"
    # This gate is explicitly local-only; it never consumes an inherited key.
    os.environ["LEARNNOTE_LLM_API_KEY"] = ""
    backend = ROOT / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    long_video = load_long_video_helpers()
    from app.models import TaskOptions  # noqa: E402
    from app.processor import process_local_video_task  # noqa: E402
    from app.storage import create_task, get_task, task_dir  # noqa: E402

    media_path = output_dir / "media" / f"synthetic-{args.duration_seconds}s.mp4"
    if not media_path.is_file():
        long_video.generate_synthetic_media(media_path, args.duration_seconds)
    subtitle_path = output_dir / "synthetic.srt"
    if not subtitle_path.is_file():
        segment_length = max(5, args.duration_seconds // 4)
        lines: list[str] = []
        for index in range(4):
            start = index * segment_length
            end = args.duration_seconds if index == 3 else min(args.duration_seconds, (index + 1) * segment_length)
            def stamp(seconds: int) -> str:
                return f"00:{seconds // 60:02d}:{seconds % 60:02d},000"
            lines.extend([
                str(index + 1),
                f"{stamp(start)} --> {stamp(end)}",
                f"Synthetic lesson checkpoint {index + 1}: local evidence remains traceable.",
                "",
            ])
        subtitle_path.write_text("\n".join(lines), encoding="utf-8")
    options = TaskOptions(
        visual_understanding=True,
        max_frame_count=60,
        frame_interval=15,
        low_resource_mode=True,
        llm_api_key="",
    )
    task = create_task(source_type="local", title="Full local reliability", options=options, mode="local")
    started = time.monotonic()
    process_local_video_task(task.id, media_path, task.title, options, subtitle_path=subtitle_path, subtitle_source="synthetic-fixture")
    final = get_task(task.id)
    resource_path = task_dir(task.id) / "resource_usage.json"
    report = {
        "status": "pass" if final.status == "success" and bool(final.note_path) and resource_path.is_file() else "fail",
        "task_id": task.id,
        "duration_seconds": args.duration_seconds,
        "final_status": final.status,
        "final_phase": final.phase,
        "note_path": final.note_path,
        "transcript_path": final.transcript_path,
        "subtitle_path": str(subtitle_path),
        "visual_index_path": final.visual_index_path,
        "resource_usage_path": str(resource_path),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "remote_calls": 0,
        "api_key_configured": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
