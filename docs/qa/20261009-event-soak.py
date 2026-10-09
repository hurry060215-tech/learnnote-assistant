"""Bounded real-time loopback SSE soak against LearnNote's production event route."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import threading
import time


def bootstrap():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=7200)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--restart", type=float, default=900)
    parser.add_argument("--disconnect-events", type=int, default=15)
    parser.add_argument("--server-port", type=int)
    args = parser.parse_args()
    args.repo, args.output = args.repo.resolve(), args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    os.chdir(args.repo)
    os.environ.update({"LEARNNOTE_DATA_DIR": str(args.output / "data"),
                       "LEARNNOTE_DEPLOYMENT_MODE": "desktop", "LEARNNOTE_LLM_API_KEY": "",
                       "ORT_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
                       "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    sys.path[:0] = [str(args.repo / "backend"), str(args.repo)]
    guard = runpy.run_path(str(args.repo / "scripts/test-backend-offline.py"))
    with guard["offline_network"]():
        if args.server_port:
            from fastapi import FastAPI
            import uvicorn
            from app.routers.events import events_router
            app = FastAPI()
            app.include_router(events_router)
            @app.get("/health")
            def health():
                return {"synthetic_event_soak": True}
            uvicorn.run(app, host="127.0.0.1", port=args.server_port, log_level="warning")
            return 0
        return run(args)


def run(args):
    import requests
    from app.models import TaskOptions
    from app.observability import record_task_event, read_task_events_after
    from app.storage import create_task, get_task, update_task
    assert args.seconds >= 5 and args.interval > 0 and args.restart >= 2
    assert args.disconnect_events >= 1
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()
    main_tree = subprocess.check_output(["git", "rev-parse", "0bb7a1b0514ffc787d7e1289f97d0089e6c165d9^{tree}"], text=True).strip()
    assert tree == main_tree, "The soak must use the verified main product tree"
    report = {"status": "running", "equivalent_main_sha": "0bb7a1b0514ffc787d7e1289f97d0089e6c165d9",
              "tree": tree, "requested_seconds": args.seconds, "transport": "real loopback HTTP/SSE",
              "scope": "production event router and task/event storage; isolated synthetic task; no full app lifecycle",
              "external_network": "blocked by repository guard", "model_calls": 0,
              "native_extension_tested": False, "provider_network_tested": False,
              "connections": 0, "planned_disconnects": 0, "server_restarts": 0, "heartbeats": 0}
    report_path = args.output / "report.json"
    def save():
        temporary = report_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(report_path)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    process = None
    log = (args.output / "server.log").open("a", encoding="utf-8")
    stopped = threading.Event()
    errors = []
    writer = None
    session = requests.Session()
    session.trust_env = False
    def start_server():
        nonlocal process
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--repo", str(args.repo),
                                    "--output", str(args.output), "--server-port", str(port)], stdout=log, stderr=log)
        until = time.monotonic() + 30
        while time.monotonic() < until:
            if process.poll() is not None:
                raise RuntimeError("Synthetic event server exited before readiness")
            try:
                if session.get(base + "/health", timeout=1).json() == {"synthetic_event_soak": True}:
                    return
            except requests.RequestException:
                pass
            time.sleep(.1)
        raise RuntimeError("Synthetic event server did not become ready")
    def stop_server():
        nonlocal process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        process = None
    try:
        task = create_task("local", "Synthetic two-hour event channel", options=TaskOptions(llm_api_key=""))
        update_task(task.id, status="running", phase="summarizing")
        start_server()
        started = time.monotonic()
        deadline = started + args.seconds
        next_restart = started + args.restart
        started_utc = datetime.now(timezone.utc)
        report.update(started_at=started_utc.isoformat(), expected_end_at=(started_utc + timedelta(seconds=args.seconds)).isoformat(),
                      driver_pid=os.getpid(), server_restart_interval_seconds=args.restart,
                      producer_interval_seconds=args.interval, reconnect_every_events=args.disconnect_events)
        save()
        def produce():
            sequence = 0
            try:
                while not stopped.is_set() and time.monotonic() < deadline:
                    sequence += 1
                    record_task_event(task.id, "partial_section_ready", phase="summarizing", status="draft",
                                      message="Synthetic literal text: 学习原文 <not-markup>", details={"sequence": sequence})
                    # An occasional real idle interval exercises SSE heartbeats.
                    pause = 22 if sequence % 1200 == 0 and deadline - time.monotonic() > 25 else args.interval
                    stopped.wait(pause)
                if not stopped.is_set():
                    update_task(task.id, status="success", phase="completed", progress=100)
            except BaseException as exc:
                errors.append(type(exc).__name__ + ": " + str(exc))
                stopped.set()
        writer = threading.Thread(target=produce, daemon=True)
        writer.start()
        received, cursor, terminal = [], 0, False
        next_status = started + 60
        while not terminal:
            if errors:
                raise RuntimeError(errors[0])
            if time.monotonic() > deadline + 60:
                raise TimeoutError("Terminal event did not arrive after the bounded run")
            if time.monotonic() >= next_restart and time.monotonic() < deadline:
                stop_server()
                start_server()
                report["server_restarts"] += 1
                next_restart = time.monotonic() + args.restart
            report["connections"] += 1
            url = base + f"/api/tasks/{task.id}/events/stream?after={max(0, cursor - 5)}"
            with session.get(url, headers={"Last-Event-ID": str(cursor)}, stream=True, timeout=(3, 25)) as response:
                response.raise_for_status()
                response.encoding = "utf-8"
                fields, count = {}, 0
                for line in response.iter_lines(chunk_size=1, decode_unicode=True):
                    if line.startswith(":"):
                        report["heartbeats"] += 1
                        continue
                    if line:
                        key, _, value = line.partition(":")
                        fields[key] = value.lstrip()
                        continue
                    if not fields:
                        continue
                    payload = json.loads(fields["data"])
                    event_id = int(fields["id"])
                    if fields.get("event") == "task_terminal":
                        assert payload["status"] == "success" and event_id == cursor
                        terminal = True
                        break
                    assert event_id == cursor + 1, ("non-monotonic or missing event", cursor, event_id)
                    assert payload["event_id"] == event_id
                    cursor = event_id
                    received.append(event_id)
                    fields = {}
                    count += 1
                    now = time.monotonic()
                    if now >= next_status:
                        report.update(elapsed_seconds=round(now-started, 3), received_events=len(received), cursor=cursor)
                        save()
                        print(json.dumps({key: report[key] for key in ("elapsed_seconds", "received_events", "connections", "server_restarts", "heartbeats")}), flush=True)
                        next_status = now + 60
                    if count >= args.disconnect_events:
                        report["planned_disconnects"] += 1
                        break
        writer.join(timeout=3)
        expected, offset = [], 0
        while True:
            page = read_task_events_after(task.id, after=offset, limit=2000)
            if not page:
                break
            expected.extend(event_id for event_id, _ in page)
            offset = page[-1][0]
        assert received == expected, "The observed stream must exactly match every stored event once"
        assert get_task(task.id).status == "success"
        elapsed = time.monotonic() - started
        assert elapsed >= args.seconds
        report.update(status="pass", elapsed_seconds=round(elapsed, 3), received_events=len(received),
                      stored_events=len(expected), cursor=cursor, missing_events=0, duplicate_events=0,
                      terminal_observed=True, exact_disk_replay=True)
        save()
        print(json.dumps(report), flush=True)
        return 0
    except BaseException as exc:
        report.update(status="failed_or_interrupted", failure_type=type(exc).__name__, failure=str(exc))
        save()
        raise
    finally:
        stopped.set()
        if writer:
            writer.join(timeout=3)
        stop_server()
        session.close()
        log.close()


if __name__ == "__main__":
    raise SystemExit(bootstrap())
