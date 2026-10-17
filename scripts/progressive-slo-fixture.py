"""Isolated real API/queue/SSE fixture; complete reference captions, held summary.

Only the final summary adapter and model-readiness checks are substituted. The
normal persisted task admission, workers, drafts, cancellation and recovery run.
Never import this fixture into a production server or reuse a real data directory.
"""
import argparse
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import traceback
from urllib.parse import urlsplit
from unittest.mock import patch

MARKER = {"schema_version": 1, "fixture": "progressive-slo-complete-captions"}


def configure_fixture(root, data, stack, *, resume=False):
    if data.is_symlink() or not data.is_dir():
        raise ValueError("Fixture data must be an existing non-symlink directory")
    marker = data / "progressive-slo-fixture.json"
    if resume:
        if marker.is_symlink() or not marker.is_file() or json.loads(marker.read_text()) != MARKER:
            raise ValueError("Resume requires this fixture's owned data marker")
    elif any(data.iterdir()):
        raise ValueError("New fixture data directory must be empty")
    else:
        marker.write_text(json.dumps(MARKER), encoding="utf-8")
    for name in list(os.environ):
        if name.startswith(("LEARNNOTE_", "OPENAI_", "AZURE_", "ANTHROPIC_")) or name.upper().endswith("_PROXY"):
            del os.environ[name]
    os.environ.update(LEARNNOTE_DATA_DIR=str(data), LEARNNOTE_DEPLOYMENT_MODE="local", PYTHONUTF8="1",
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", ORT_DISABLE_TELEMETRY="1")
    sys.path[:0] = [str(root), str(root / "backend")]
    spec = importlib.util.spec_from_file_location("offline_slo", root / "scripts/test-backend-offline.py")
    offline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(offline)
    stack.enter_context(offline.offline_network())
    from fastapi import HTTPException
    from app import main, processor, storage, update_service
    import openai
    from app.observability import read_task_events
    from app.queue_journal import read_queue_job
    from app.task_artifacts import task_artifact_path
    from app.task_control_state import task_generation

    if not resume:
        update_service.save_preferences({"auto_check": False, "auto_download": False})

    records, titles, startup = {}, {}, {}
    forbidden_path = data / "forbidden-operations.json"
    forbidden = json.loads(forbidden_path.read_text()) if forbidden_path.exists() else []
    diagnostic_path = data / "forbidden-diagnostics.json"
    network_diagnostics = json.loads(diagnostic_path.read_text()) if diagnostic_path.exists() else []
    lock = threading.RLock()

    def register(task_id, *, admission=False):
        task = storage.get_task(task_id)
        if not task.title.startswith("SLO reference "):
            raise HTTPException(409, "Not a reference fixture task")
        with lock:
            record = records.setdefault(task_id, {"gate": threading.Event(), "continuation_calls": 0,
                "waiting": False, "transcript_recorded": None, "admissions": 0})
            titles[task.title] = task_id
            if admission:
                record["gate"].clear()
                record["admissions"] += 1
            return record

    for task in storage.list_tasks_snapshot():
        register(task.id)
    original_schedule = main.schedule_processing
    original_timing = processor.record_stage_duration
    original_recovery = main.recover_processing

    def schedule(background_tasks, function, task_id, *args, **kwargs):
        register(task_id, admission=True)
        return original_schedule(background_tasks, function, task_id, *args, **kwargs)

    def timing(task_id, stage, *args, **kwargs):
        result = original_timing(task_id, stage, *args, **kwargs)
        if stage == "transcript":
            register(task_id)["transcript_recorded"] = time.monotonic()
        return result

    def recover(*args, **kwargs):
        result = original_recovery(*args, **kwargs)
        startup.update(result)
        return result

    def reference_summary(title, transcript, *args, **kwargs):
        task_id = titles[title]
        record = register(task_id)
        record["continuation_calls"] += 1
        record["waiting"] = True
        deadline = time.monotonic() + 90
        try:
            while not record["gate"].wait(.02):
                processor._check_cancel(task_id)
                if time.monotonic() >= deadline:
                    raise TimeoutError("Reference continuation was not released within 90 seconds")
            processor._check_cancel(task_id)
            return "# " + title + "\n\n## Source evidence\n\n" + transcript.segments[0].text, "offline-fixture", "", []
        finally:
            record["waiting"] = False

    def record_forbidden(kind, diagnostic=None):
        with lock:
            forbidden.append(kind)
            forbidden_path.write_text(json.dumps(forbidden), encoding="utf-8")
            if diagnostic and len(network_diagnostics) < 32:
                network_diagnostics.append(diagnostic)
                diagnostic_path.write_text(json.dumps(network_diagnostics), encoding="utf-8")

    def deny(kind):
        def forbidden_call(*args, **kwargs):
            record_forbidden(kind)
            raise AssertionError("Forbidden fixture operation: " + kind)
        return forbidden_call

    def observed_guard(function, transport):
        def guarded(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except OSError as error:
                if "Offline tests forbid external" in str(error):
                    if transport == "send":
                        parsed = urlsplit(args[1].url)
                        host, endpoint_path = parsed.hostname or "", parsed.path
                    else:
                        target = args[0] if transport == "getaddrinfo" else args[1]
                        host, endpoint_path = (target[0] if isinstance(target, tuple) else target), ""
                    record_forbidden("external_network_blocked", {"transport": transport,
                        "host": str(host)[:253], "path": str(endpoint_path)[:200],
                        "locations": [{"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                                      for frame in traceback.extract_stack(limit=10)[:-1]]})
                raise
        return guarded

    import requests
    for module, name in ((socket.socket, "connect"), (socket.socket, "connect_ex"),
                         (socket, "getaddrinfo"), (requests.adapters.HTTPAdapter, "send")):
        stack.enter_context(patch.object(module, name, observed_guard(getattr(module, name), name)))

    for module, name, replacement in (
        (main, "schedule_processing", schedule), (main, "recover_processing", recover),
        (main, "require_ready_note_model", lambda options: None),
        (main, "resolve_model_options", lambda options: options),
        (processor, "record_stage_duration", timing),
        (processor, "summarize_with_diagnostics", reference_summary),
        (processor, "MediaDownloader", deny("download")),
        (processor, "prepare_transcript", deny("media_or_asr")),
        (openai, "OpenAI", deny("provider_constructor")),
    ):
        stack.enter_context(patch.object(module, name, replacement))

    def snapshot(task_id):
        record, task = register(task_id), storage.get_task(task_id)
        hashes, source_coverage = {}, {}
        for field in ("transcript_path", "subtitle_path"):
            target = task_artifact_path(task, field)
            if target is not None:
                content = target.read_bytes()
                hashes[field] = hashlib.sha256(content).hexdigest()
                if field == "transcript_path":
                    cues = json.loads(content)["segments"]
                    duration = task.active_video.duration if task.active_video else 0
                    source_coverage = {"duration": duration, "cue_count": len(cues),
                        "first_start": cues[0]["start"] if cues else None, "last_end": cues[-1]["end"] if cues else None,
                        "reference_cues_complete": len(cues) == duration / 30 and all(
                            cue["start"] == index * 30 and cue["end"] == (index + 1) * 30
                            and cue["text"] == f"Reference lesson source statement at {index * 30} seconds."
                            for index, cue in enumerate(cues))}
        draft = storage.task_dir(task_id) / "draft.md"
        if draft.is_file():
            hashes["draft.md"] = hashlib.sha256(draft.read_bytes()).hexdigest()
        sections_path = storage.task_dir(task_id) / "draft_sections.json"
        if sections_path.is_file():
            sections = json.loads(sections_path.read_bytes())["sections"]
            source_coverage.update(section_count=len(sections), final_section_end=sections[-1]["end"] if sections else None)
        events = [event for event in read_task_events(task_id) if event.get("event") in
                  {"stage_timing", "draft_ready", "pipeline_attempt_started"}]
        return {"task_id": task_id, "status": task.status, "phase": task.phase,
            "generation": task_generation(task), "hashes": hashes, "source_coverage": source_coverage,
            "continuation_calls": record["continuation_calls"], "waiting": record["waiting"],
            "admissions": record["admissions"], "queue": read_queue_job(data, task_id), "stages": events}

    @main.app.get("/_fixture/state")
    def state():
        return {"startup_recovery": startup, "forbidden_attempts": forbidden, "network_diagnostics": network_diagnostics,
                "update_preferences": update_service.get_preferences(), "worker_pid": os.getpid()}

    @main.app.get("/_fixture/tasks/{task_id}")
    def task_state(task_id: str):
        return snapshot(task_id)

    @main.app.post("/_fixture/tasks/{task_id}/visible")
    def visible(task_id: str):
        record = register(task_id)
        if not record["waiting"] or record["transcript_recorded"] is None:
            raise HTTPException(409, "Visible acknowledgement requires the held transcript draft")
        return {**snapshot(task_id), "after_transcript_visible_ack_seconds":
                time.monotonic() - record["transcript_recorded"]}

    @main.app.post("/_fixture/tasks/{task_id}/release")
    def release(task_id: str):
        record = register(task_id)
        if not record["waiting"]:
            raise HTTPException(409, "Reference continuation is not waiting")
        record["gate"].set()
        return {"released": True}

    return main.app, {"offline_network": True, "resume": resume, "worker_pid": os.getpid()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    with ExitStack() as stack:
        app, fixture = configure_fixture(Path(__file__).resolve().parents[1], args.data_dir.absolute(), stack, resume=args.resume)
        import uvicorn
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
            os.environ["LEARNNOTE_BACKEND_ORIGIN"] = origin
            print(json.dumps({"fixture_origin": origin, **fixture}), flush=True)
            uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[listener])


if __name__ == "__main__":
    main()
