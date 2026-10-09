"""Reference-only 5/30/60/180-minute caption-to-outline latency gate."""
from __future__ import annotations
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def percentile95(values):
    return sorted(values)[max(0, math.ceil(len(values) * .95) - 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repetitions", type=int, default=20)
    args = parser.parse_args()
    if not 2 <= args.repetitions <= 100:
        parser.error("repetitions must be 2–100; published p95 gate uses at least20")
    output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=True)
    os.environ.update({"LEARNNOTE_DATA_DIR": str(output / "data"), "LEARNNOTE_LLM_API_KEY": "",
                       "LEARNNOTE_DEPLOYMENT_MODE": "desktop", "ORT_DISABLE_TELEMETRY": "1",
                       "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
    spec = importlib.util.spec_from_file_location("offline_guard", ROOT / "scripts/test-backend-offline.py")
    guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
    with guard.offline_network():
        return run(output, args.repetitions)


def run(output, repetitions):
    from app import processor
    from app.models import ActiveVideoInfo, BrowserSubtitleCue, CurrentPageTaskRequest, TaskOptions
    from app.storage import create_task, get_task, read_json
    from app.task_artifacts import read_task_note
    from app.task_queue import queue_for
    from app.observability import read_task_events
    queue = queue_for(output / "data")
    current = {}
    def reference_summary(title, transcript, *args, **kwargs):
        task_id = current["task_id"]
        current["visible_seconds"] = time.monotonic() - current["started"]
        document = read_json(task_id, "draft_sections.json", {})
        assert document["status"] == "draft" and not document["summary_generated"]
        assert "按时间段的阅读提纲" in read_task_note(task_id)
        assert document["sections"][-1]["end"] == current["duration"]
        events = read_task_events(task_id)
        transcript_event = next(e for e in events if e.get("event") == "stage_timing" and e.get("phase") == "transcript")
        draft_event = next(e for e in events if e.get("event") == "draft_ready")
        from datetime import datetime
        current["after_transcript_seconds"] = max(0, (datetime.fromisoformat(draft_event["timestamp"]) - datetime.fromisoformat(transcript_event["timestamp"])).total_seconds())
        return "# Reference\n\n## Source evidence\n\n" + transcript.segments[0].text, "offline-fixture", "", []
    processor.summarize_with_diagnostics = reference_summary
    rows = []
    try:
        for minutes in (5, 30, 60, 180):
            duration = minutes * 60
            cues = [BrowserSubtitleCue(start=i, end=min(i + 30, duration), text=f"Reference lesson source statement at {i} seconds.") for i in range(0, duration, 30)]
            samples, after_transcript = [], []
            for repetition in range(repetitions):
                started = time.monotonic()
                options = TaskOptions(content_mode="text", visual_understanding=False, llm_api_key="")
                task = create_task("current_page", "Reference", "https://example.test/reference", options=options)
                current.clear(); current.update(task_id=task.id, started=started, duration=duration)
                request = CurrentPageTaskRequest(mode="subtitle_only", page_url=task.page_url, title=task.title,
                    options=options, browser_subtitles=cues, active_video=ActiveVideoInfo(duration=duration))
                queue.enqueue(task.id, "page_light", lambda: processor.process_current_page_task(task.id, request)).result(30)
                assert get_task(task.id).status == "success"
                samples.append(current["visible_seconds"]); after_transcript.append(current["after_transcript_seconds"])
            row = {"minutes": minutes, "samples": repetitions, "outline_visible_p95_seconds": round(percentile95(samples), 4),
                   "after_transcript_p95_seconds": round(percentile95(after_transcript), 4),
                   "max_seconds": round(max(samples), 4), "section_count": minutes // 5}
            rows.append(row); print(json.dumps(row), flush=True)
    finally:
        queue.stop()
    report = {"status": "pass" if all(row["outline_visible_p95_seconds"] <= 10 and row["after_transcript_p95_seconds"] <= 5 for row in rows) else "fail",
              "reference": "synthetic complete platform captions, real local queue/storage/draft path, deterministic final-summary adapter",
              "outline": "time-based source excerpts, not AI-inferred topic chapters", "network_calls": 0,
              "asr_attempted": False, "queue_contention": False, "model_quality_claim": False,
              "minimum_release_samples_per_duration": 20, "release_gate_eligible": repetitions >= 20, "results": rows}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
