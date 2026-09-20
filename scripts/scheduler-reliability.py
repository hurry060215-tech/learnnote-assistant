"""Run a deterministic mixed local queue gate without task content or network."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.task_queue import LocalTaskQueue  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise durable mixed queue ordering and idempotent enqueue.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "test-runs" / "scheduler-reliability")
    args = parser.parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    root = output_dir / "data"
    root.mkdir(parents=True, exist_ok=True)
    queue = LocalTaskQueue(root)
    active = 0
    peak = 0
    lock = threading.Lock()
    order: list[str] = []
    heavy_started, light_started = threading.Event(), threading.Event()
    lane_active = {"heavy": 0, "light": 0}
    lane_peak = {"heavy": 0, "light": 0}

    def work(label: str, delay: float = 0.02) -> None:
        nonlocal active, peak
        lane = "heavy" if label.startswith("heavy") else "light"
        with lock:
            active += 1
            peak = max(peak, active)
            lane_active[lane] += 1
            lane_peak[lane] = max(lane_peak[lane], lane_active[lane])
            order.append("start:" + label)
        if label == "heavy-1":
            heavy_started.set()
            if not light_started.wait(5):
                raise RuntimeError("Light work was blocked by heavy work")
        if label == "light-1":
            light_started.set()
        time.sleep(delay)
        with lock:
            order.append("end:" + label)
            active -= 1
            lane_active[lane] -= 1

    first = queue.enqueue("heavy-1", "local", lambda: work("heavy-1"))
    if not heavy_started.wait(5):
        raise RuntimeError("Heavy worker did not start")
    duplicate = queue.enqueue("heavy-1", "local", lambda: work("duplicate"))
    futures = [first,
        queue.enqueue("light-1", "light", lambda: work("light-1")),
        queue.enqueue("summary-1", "summary", lambda: work("summary-1")),
        queue.enqueue("heavy-2", "local", lambda: work("heavy-2")),
        queue.enqueue("light-2", "light", lambda: work("light-2")),
    ]
    for future in futures:
        future.result(timeout=10)
    queue.stop()

    restored = LocalTaskQueue(root)
    entries = restored.entries()
    restored.stop()
    states = {str(row["task_id"]): str(row["state"]) for row in entries}
    report = {
        "status": "pass" if peak == 2 and all(value == 1 for value in lane_peak.values()) and duplicate is futures[0] and all(states.get(key) == "done" for key in ("heavy-1", "light-1", "summary-1", "heavy-2", "light-2")) else "fail",
        "queue_kind": "mixed-local",
        "job_count": len(futures),
        "peak_active_callbacks": peak,
        "lane_peak_active_callbacks": lane_peak,
        "light_completed_without_heavy_release": light_started.is_set(),
        "duplicate_enqueue_reused_future": duplicate is futures[0],
        "durable_journal_reopened": all(states.get(key) == "done" for key in states),
        "states": states,
        "execution_order": order,
        "remote_calls": 0,
        "privacy": "queue IDs, states and local timing only; no task content, URL, cookie or model payload",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
