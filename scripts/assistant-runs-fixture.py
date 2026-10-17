"""Serve a new synthetic acceptance workspace with loopback-only networking."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys



def controls_startup_diagnostics(task_id, queue, manifest, entered, started, callback_errors):
    """Bounded synthetic state only; diagnostic reads never wait on worker locks."""
    import sqlite3
    import threading
    import traceback
    result = {"task_id": task_id, "callback_entered": entered.is_set(),
              "running_state_written": started.is_set(), "callback_errors": callback_errors[-1:]}
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
        result["task"] = {key: value.get(key) for key in
                          ("id", "status", "phase", "cancel_requested", "error_code", "control_generation")}
    except Exception as exc:
        result["task_read_error"] = type(exc).__name__
    try:
        from contextlib import closing
        with closing(sqlite3.connect(queue.path, timeout=.2)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT task_id,state,generation,callback_finished FROM jobs WHERE task_id=?", (task_id,)).fetchone()
            result["intent"] = dict(row) if row else None
    except Exception as exc:
        result["intent_read_error"] = type(exc).__name__
    job = queue.jobs.get(task_id)
    if job:
        future = job[1]
        result["future"] = {"done": future.done(), "running": future.running(), "cancelled": future.cancelled()}
        if future.done() and not future.cancelled():
            error = future.exception(timeout=0)
            result["future"]["exception"] = None if error is None else str(error)[:1000]
    else:
        result["future"] = {"retained": False, "unavailable_reason": "queue_entry_removed_or_not_admitted"}
    frames = sys._current_frames()
    result["workers"] = [{"name": thread.name, "alive": thread.is_alive(),
                          "stack": [line[:300] for line in traceback.format_stack(frames[thread.ident], limit=12)]}
                         for thread in threading.enumerate()
                         if thread.name.startswith("learnnote-task-queue-") and thread.ident in frames][:12]
    return result


def write_controls_startup_report(destination, payload):
    """A failed diagnostic write must not replace the actual startup failure."""
    try:
        if destination:
            Path(destination).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps({"controls_startup": payload}), flush=True)
    except Exception as exc:
        print("Controls startup diagnostic write failed: " + type(exc).__name__, file=sys.stderr, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--model-base", required=True)
    parser.add_argument("--controls", action="store_true")
    parser.add_argument("--startup-report")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    data = Path(args.data_dir).resolve()
    # The caller owns this freshly created directory and its eventual cleanup.
    if not data.is_dir() or any(data.iterdir()):
        raise ValueError("Acceptance data directory must exist and be empty")
    from urllib.parse import urlsplit
    endpoint = urlsplit(args.model_base)
    if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or not endpoint.port:
        raise ValueError("The mocked model must use an explicit loopback port")
    for name in list(os.environ):
        if name.startswith(("LEARNNOTE_", "OPENAI_", "AZURE_", "ANTHROPIC_")) or name.upper().endswith("_PROXY"):
            del os.environ[name]
    os.environ.update(LEARNNOTE_DATA_DIR=str(data), LEARNNOTE_DEPLOYMENT_MODE="local",
                      LEARNNOTE_LLM_BASE_URL=args.model_base, LEARNNOTE_LLM_MODEL="mocked-acceptance-model",
                      LEARNNOTE_LLM_API_KEY="", PYTHONUTF8="1")
    sys.path.insert(0, str(root / "backend"))
    spec = importlib.util.spec_from_file_location("offline_acceptance", root / "scripts/test-backend-offline.py")
    offline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(offline)
    # Apply the existing test guard before importing uvicorn or the application.
    with offline.offline_network():
        import uvicorn
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            os.environ["LEARNNOTE_BACKEND_ORIGIN"] = f"http://127.0.0.1:{port}"
            controls = {}
            if args.controls:
                import threading
                import time
                from fastapi import BackgroundTasks
                from app.storage import create_task, update_task, get_task, task_dir, mark_task_cancelled
                from app.courses import save_course
                from app.task_queue import schedule_processing, queue_for
                from app.task_control import task_generation
                task = create_task("local", "Synthetic running task")
                original = task_dir(task.id) / "original.txt"
                original.write_bytes(b"Synthetic original retained by cancellation.\n")
                generation = task_generation(task)
                started = threading.Event()
                entered = threading.Event()
                callback_errors = []
                def callback(task_id):
                    update_task(task_id, status="running", phase="summarizing", message="Synthetic callback")
                    started.set()
                    deadline = time.monotonic() + 120
                    while time.monotonic() < deadline:
                        if get_task(task_id).cancel_requested:
                            mark_task_cancelled(task_id, expected_generation=generation)
                            return
                        time.sleep(.025)
                    raise RuntimeError("Synthetic callback was not cancelled in time")
                def work(task_id):
                    entered.set()
                    try:
                        callback(task_id)
                    except BaseException:
                        import traceback
                        callback_errors.append(traceback.format_exc()[-4000:])
                        raise
                schedule_processing(BackgroundTasks(), work, task.id, _queue_kind="summary")
                ready = started.wait(5)
                try:
                    diagnostics = controls_startup_diagnostics(task.id, queue_for(data),
                        task_dir(task.id) / "task.json", entered, started, callback_errors)
                    diagnostics["ready"] = ready
                    diagnostics["wait_seconds"] = 5
                    write_controls_startup_report(args.startup_report, diagnostics)
                except Exception as exc:
                    print("Controls startup diagnostic collection failed: " + type(exc).__name__, file=sys.stderr, flush=True)
                if not ready:
                    raise RuntimeError("Synthetic callback did not start")
                course = save_course("Synthetic control course", [{"kind": "task", "id": task.id}])
                controls = {"control_task_id": task.id, "control_course_id": course["id"]}
            print(json.dumps({"fixture_origin": os.environ["LEARNNOTE_BACKEND_ORIGIN"],
                              "offline_network": True, **controls}), flush=True)
            server = uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=port, log_level="warning"))
            server.run(sockets=[listener])


if __name__ == "__main__":
    main()
