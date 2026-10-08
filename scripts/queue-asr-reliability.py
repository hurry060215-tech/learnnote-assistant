"""Opt-in real local ASR queue proof using predownloaded public fixtures only.

No fixture downloads or provider calls are performed. Summary is a declared
deterministic reference adapter; media decoding, Whisper and storage are real.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--speech-file", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    model = args.model_dir.resolve()
    speech = args.speech_file.resolve()
    if not (model / "model.bin").is_file() or not speech.is_file():
        parser.error("Provide existing public model and speech fixture paths")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update({"LEARNNOTE_DATA_DIR": str(output / "data"), "LEARNNOTE_LLM_API_KEY": "",
                       "LEARNNOTE_DEPLOYMENT_MODE": "desktop", "HF_HUB_OFFLINE": "1",
                       "TRANSFORMERS_OFFLINE": "1", "ORT_DISABLE_TELEMETRY": "1",
                       "HF_HUB_DISABLE_TELEMETRY": "1", "LEARNNOTE_LOW_RESOURCE_MODE": "1"})
    sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
    spec = importlib.util.spec_from_file_location("offline_guard", ROOT / "scripts/test-backend-offline.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    with guard.offline_network():
        return exercise(args, output, model, speech)


def exercise(args, output, model, speech):
    from app.models import TaskOptions
    from app import processor
    from app.storage import create_task, get_task, task_dir
    from app.task_queue import LocalTaskQueue
    from app.resource_monitor import ResourceMonitor

    media = output / "public-speech.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=5",
                    "-i", str(speech), "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1",
                    "-c:a", "aac", str(media)], check=True, timeout=60)
    subtitle = output / "reference.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:12,000\nPublic speech fixture: ask what you can do for your country.\n", encoding="utf-8")
    def reference_summary(title, transcript, *unused, **kwargs):
        return "# " + title + "\n\n## Transcript evidence\n\n" + transcript.full_text, "offline-fixture", "", []
    processor.summarize_with_diagnostics = reference_summary
    queue = LocalTaskQueue(output / "data")
    monitor = ResourceMonitor(output, interval_seconds=.05).start()
    lock = threading.Lock()
    release = threading.Event()
    active = {"heavy": 0, "light": 0}
    peak = dict(active)
    order, completed = [], []
    tasks, futures = [], []
    started = time.monotonic()
    def run(task, lane, use_subtitles):
        with lock:
            active[lane] += 1
            peak[lane] = max(peak[lane], active[lane])
            order.append(task.title)
        try:
            if not release.wait(5):
                raise RuntimeError("Queue setup did not complete")
            processor.process_local_video_task(task.id, media, task.title, task.options,
                subtitle_path=subtitle if use_subtitles else None,
                subtitle_source="prebuilt-reference")
            final = get_task(task.id)
            transcript = json.loads((task_dir(task.id) / "transcript.json").read_text(encoding="utf-8"))
            completed.append({"label": task.title, "status": final.status,
                              "transcript_source": transcript.get("source"),
                              "note_present": bool(final.note_path),
                              "resource_report": (task_dir(task.id) / "resource_usage.json").is_file()})
        finally:
            with lock:
                active[lane] -= 1
    try:
        for index in range(5):
            light = index == 1
            options = TaskOptions(content_mode="text", visual_understanding=False, whisper_model=str(model),
                                  low_resource_mode=True, llm_api_key="")
            task = create_task("local", f"reference-{index}", options=options, mode="local")
            tasks.append(task)
            lane = "light" if light else "heavy"
            futures.append(queue.enqueue(task.id, "local_light" if light else "local",
                lambda task=task, lane=lane, light=light: run(task, lane, light)))
        cancel_start = time.monotonic()
        cancelled = queue.cancel_pending(tasks[-1].id)
        futures[-1].result(2)
        cancel_seconds = time.monotonic() - cancel_start
        release.set()
        for future in futures:
            future.result(180)
    finally:
        release.set()
        queue.stop()
        resources = monitor.stop().as_dict()
    journal = queue.entries()
    real_asr = sum(item["transcript_source"] == "faster-whisper" for item in completed)
    report = {"status": "pass" if cancelled and cancel_seconds < 2 and real_asr == 3
              and peak == {"heavy": 1, "light": 1} and len(completed) == 4
              and all(item["status"] == "success" and item["note_present"] for item in completed) else "fail",
              "submitted": 5, "completed": completed, "real_asr_tasks": real_asr,
              "peak_active_lanes": peak, "cancel_seconds": round(cancel_seconds, 4),
              "execution_order": order, "durable_states": [row["state"] for row in journal],
              "elapsed_seconds": round(time.monotonic() - started, 3), "resources": resources,
              "input": "predownloaded public speech and local tiny model", "summary": "deterministic reference adapter",
              "remote_calls": 0, "subtitle_fixture_tasks": 1}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
