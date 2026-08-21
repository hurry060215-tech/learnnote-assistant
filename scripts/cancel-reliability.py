from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise real local-task cancellation without network or model calls.")
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "test-runs" / "cancel-reliability")
    args = parser.parse_args()
    if args.duration_seconds < 5:
        parser.error("--duration-seconds must be at least 5")

    output_dir = args.output_dir.expanduser().resolve()
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["LEARNNOTE_DATA_DIR"] = str(data_dir)
    os.environ["LEARNNOTE_DEPLOYMENT_MODE"] = "desktop"
    backend = ROOT / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    from app.config import DATA_DIR  # noqa: E402
    from app.models import TaskOptions  # noqa: E402
    from app.processor import process_local_video_task  # noqa: E402
    from app.runtime import ffmpeg_bin, hidden_subprocess_kwargs  # noqa: E402
    from app.storage import create_task, get_task, request_task_cancel, task_dir  # noqa: E402

    media_dir = output_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    media_path = media_dir / f"synthetic-{args.duration_seconds}s.mp4"
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for cancellation reliability.")
    if not media_path.is_file():
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=16000",
                "-t",
                str(args.duration_seconds),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "35",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "32k",
                "-shortest",
                str(media_path),
            ],
            check=True,
            **hidden_subprocess_kwargs(),
        )

    options = TaskOptions(
        visual_understanding=True,
        max_frame_count=60,
        frame_interval=15,
        low_resource_mode=True,
    )
    task = create_task(source_type="local", title="Cancellation reliability", options=options, mode="local")
    task = task.model_copy(update={"source_media_path": str(media_path)})
    # Persist the source path through the normal storage path before the worker starts.
    from app.storage import save_task  # noqa: E402

    save_task(task)
    started = time.monotonic()
    worker = threading.Thread(
        target=process_local_video_task,
        args=(task.id, media_path, task.title, options),
        name="learnnote-cancel-reliability",
        daemon=True,
    )
    worker.start()
    deadline = time.monotonic() + 30
    cancel_deadline = time.monotonic() + 10
    observed_phases: list[str] = []
    while worker.is_alive() and time.monotonic() < cancel_deadline:
        record = get_task(task.id)
        if record.phase and record.phase not in observed_phases:
            observed_phases.append(record.phase)
        if record.status == "running" or record.phase not in {"queued", "cancelling"}:
            break
        time.sleep(0.05)
    if worker.is_alive():
        request_task_cancel(task.id)
    while worker.is_alive() and time.monotonic() < deadline:
        record = get_task(task.id)
        if record.phase and record.phase not in observed_phases:
            observed_phases.append(record.phase)
        time.sleep(0.05)
    worker.join(timeout=30)
    final = get_task(task.id)
    resource_path = task_dir(task.id) / "resource_usage.json"
    report = {
        "status": "pass" if final.status == "cancelled" and resource_path.is_file() else "fail",
        "task_id": task.id,
        "duration_seconds": args.duration_seconds,
        "final_status": final.status,
        "final_phase": final.phase,
        "observed_phases": observed_phases,
        "cancel_latency_seconds": round(max(0.0, time.monotonic() - started), 3),
        "resource_usage_path": str(resource_path),
        "data_dir": str(DATA_DIR),
        "remote_calls": 0,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
