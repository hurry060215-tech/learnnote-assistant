"""Owned local A/V + embedded captions; real visual pipeline with held completions.

Only the chat-completion boundary is deterministic. Admission, queue, FFmpeg,
transcript/grid preparation, batch scheduling/cache, partial publication and SSE
remain production code. Never run against an existing user data directory.
"""
import argparse
from contextlib import ExitStack
import faulthandler
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

OPTIONS = {"content_mode": "visual", "visual_understanding": True, "local_ocr": False,
           "frame_interval": 8, "grid_columns": 1, "grid_rows": 1,
           "vision_batch_size": 1, "vision_concurrency": 2, "resource_budget_mb": 1024,
           "use_saved_connection": False, "llm_base_url": "http://127.0.0.1:9/v1",
           "llm_model": "visual-join-reference", "llm_api_key": ""}
MARKER = {"schema_version": 1, "fixture": "joined-visual-continuation"}
CAPTIONS = ["Synthetic source: the first window shows a generated test pattern.",
            "Synthetic source: the second window retains the original caption text.",
            "Synthetic source: the final window remains available for human review."]


def startup_phase(phase):
    # Owned fixture diagnostics only: no environment, requests or source paths.
    print(json.dumps({"fixture_startup_phase": phase, "worker_pid": os.getpid(),
                      "monotonic_seconds": time.monotonic()}), file=sys.stderr, flush=True)


def thread_locations(root):
    """Failure-only code locations, never frame locals, source lines or arguments."""
    current = sys._current_frames()
    threads = []
    for identity, frame in sorted(current.items())[:32]:
        locations = []
        while frame is not None and len(locations) < 32:
            file = Path(frame.f_code.co_filename)
            try:
                label = str(file.relative_to(root)).replace("\\", "/")
            except ValueError:
                label = file.name
            locations.append({"file": re.sub(r"[^a-zA-Z0-9_./<>-]", "_", label)[-200:],
                              "function": re.sub(r"[^a-zA-Z0-9_.<>-]", "_", frame.f_code.co_name)[:100],
                              "line": frame.f_lineno})
            frame = frame.f_back
        threads.append({"thread_id": identity, "locations": locations, "frames_truncated": frame is not None})
    return {"worker_pid": os.getpid(), "threads": threads, "thread_count": len(current),
            "threads_truncated": len(current) > 32, "thread_limit": 32, "frame_limit": 32}


def run_owned_command(command, shutdown):
    from app.media import media_cancellation, _run
    deadline = time.monotonic() + 60
    def check():
        if shutdown.is_set(): raise RuntimeError("Owned fixture generation was stopped")
        if time.monotonic() >= deadline: raise TimeoutError("Owned fixture generation timed out")
    with media_cancellation(check):
        _run(command, "Owned fixture media generation failed")


def generate_media(directory, shutdown, variant="a"):
    startup_phase(f"media_{variant}_tool_check")
    from app.runtime import ffmpeg_bin, ffprobe_bin
    if not ffmpeg_bin() or not ffprobe_bin():
        raise RuntimeError("Installed FFmpeg and FFprobe are required; no download is performed")
    subtitle = directory / f"reference-{variant}.srt"
    subtitle.write_text("\n\n".join(f"{i+1}\n00:00:{i*12:02d},000 --> 00:00:{(i+1)*12:02d},000\n{text}"
                                    for i, text in enumerate(CAPTIONS if variant == "a" else ["Changed source: " + value for value in CAPTIONS])) + "\n", encoding="utf-8")
    media = directory / f"reference-{variant}.mp4"
    startup_phase(f"media_{variant}_generation")
    run_owned_command([ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=2",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-i", str(subtitle),
        "-t", "36", "-map", "0:v:0", "-map", "1:a:0", "-map", "2:s:0",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "32k", "-c:s", "mov_text", "-movflags", "+faststart", str(media)],
        shutdown)
    startup_phase(f"media_{variant}_ready")
    return media


def configure_fixture(root, data, stack, shutdown, start_control):
    startup_phase("owned_data_setup")
    if data.is_symlink() or not data.is_dir() or any(data.iterdir()):
        raise ValueError("Visual fixture requires a fresh empty non-symlink directory")
    (data / "visual-fixture.json").write_text(json.dumps(MARKER), encoding="utf-8")
    for name in list(os.environ):
        if name.startswith(("LEARNNOTE_", "OPENAI_", "AZURE_", "ANTHROPIC_")) or name.upper().endswith("_PROXY"):
            del os.environ[name]
    os.environ.update(LEARNNOTE_DATA_DIR=str(data), LEARNNOTE_DEPLOYMENT_MODE="local", PYTHONUTF8="1",
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", ORT_DISABLE_TELEMETRY="1")
    sys.path[:0] = [str(root), str(root / "backend")]
    spec = importlib.util.spec_from_file_location("visual_offline", root / "scripts/test-backend-offline.py")
    offline = importlib.util.module_from_spec(spec); spec.loader.exec_module(offline)
    startup_phase("offline_guard_imports")
    stack.enter_context(offline.offline_network())
    startup_phase("application_imports")
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from app import main, processor, storage, update_service
    from app.observability import read_task_events
    from app.queue_journal import read_queue_job
    from app.task_control_state import task_generation
    from app.summarizer import SummarizationCancelled
    from app.partial_note_projection import partial_revision
    from openai.resources.chat.completions import Completions
    import httpx2 as httpx
    startup_phase("application_ready")
    # Windows native imports can block while another thread reads piped stdin.
    # Finish them first; control must still be live before cancellable generation.
    start_control()
    update_service.save_preferences({"auto_check": False, "auto_download": False})
    inputs = data / "fixture-inputs"; inputs.mkdir()
    media = {variant: generate_media(inputs, shutdown, variant) for variant in ("a", "b")}
    lock, records, forbidden = threading.RLock(), {}, []
    forbidden_count = 0

    def record_forbidden(kind):
        nonlocal forbidden_count
        with lock:
            forbidden_count += 1
            if len(forbidden) < 64: forbidden.append(kind)

    def cancel_on_shutdown():
        shutdown.wait()
        for task in storage.list_tasks_snapshot():
            if task.title.startswith("Visual join ") and task.status in {"queued", "running", "cancelling"}:
                try: main.api_cancel_task(task.id)
                except HTTPException: pass
    threading.Thread(target=cancel_on_shutdown, daemon=True).start()

    def task_record(task_id):
        task = storage.get_task(task_id)
        if not task.title.startswith("Visual join "):
            raise HTTPException(409, "Not an owned visual fixture task")
        with lock:
            record = records.setdefault(task_id, {"calls": [], "gates": {}, "active": 0})
        return task, record

    def deny(kind):
        def forbidden_call(*args, **kwargs):
            record_forbidden(kind)
            raise AssertionError("Forbidden visual fixture operation: " + kind)
        return forbidden_call

    def completion(_client, **kwargs):
        content = kwargs["messages"][0]["content"]
        if not isinstance(content, list):
            return deny("merge_or_nonvisual_completion")()
        prompt = content[0]["text"]
        title = re.search(r"标题：(.*?)\n来源：", prompt)
        batch = re.search(r"批次：(\d+)", prompt)
        candidates = [task for task in storage.list_tasks_snapshot() if title and task.title == title.group(1)]
        if len(candidates) != 1 or not batch or kwargs.get("model") != OPTIONS["llm_model"]:
            return deny("unbound_completion")()
        task, record = task_record(candidates[0].id)
        number = int(batch.group(1))
        images = [item for item in content if item.get("type") == "image_url"]
        if not images or any(not item["image_url"]["url"].startswith("data:image/") for item in images):
            return deny("missing_owned_image")()
        with lock:
            call = {"batch": number, "state": "waiting", "image_count": len(images),
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "generation": task_generation(task)}
            record["calls"].append(call); record["active"] += 1
            gate = record["gates"].setdefault(number, threading.Event())
        try:
            deadline = time.monotonic() + 120
            while not gate.wait(.02):
                current = storage.get_task(task.id)
                if current.cancel_requested or current.status in {"cancelling", "cancelled"} or task_generation(current) != call["generation"]:
                    call["state"] = "cancelled"
                    raise SummarizationCancelled("Owned fixture completion acknowledged cancellation")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Owned visual completion was not released")
            current = storage.get_task(task.id)
            if current.cancel_requested or task_generation(current) != call["generation"]:
                call["state"] = "cancelled"
                raise SummarizationCancelled("Owned fixture completion changed before release")
            text = f"## Synthetic visual batch {number}\n\n" + "\n\n".join(
                f"Reference paragraph {index}: This deterministic response describes the supplied synthetic image and caption window. "
                "It is an unverified draft, retained only for this bounded continuation test."
                for index in range(1, 5))
            call["state"] = "returned"
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=None)
        finally:
            with lock:
                record["active"] -= 1
                if call["state"] == "waiting": call["state"] = "failed"

    def observed_guard(function):
        def guarded(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except OSError as error:
                if "Offline tests forbid external" in str(error):
                    record_forbidden("external_network_blocked")
                raise
        return guarded
    import requests
    for module, name in ((socket.socket, "connect"), (socket.socket, "connect_ex"),
                         (socket, "getaddrinfo"), (requests.adapters.HTTPAdapter, "send")):
        stack.enter_context(patch.object(module, name, observed_guard(getattr(module, name))))

    original_send = httpx.Client.send
    def send(client, request, *args, **kwargs):
        if request.url.host not in {"127.0.0.1", "localhost", "::1"} or request.url.port == 9:
            return deny("provider_or_external_network")()
        return original_send(client, request, *args, **kwargs)
    for module, name, replacement in (
        (Completions, "create", completion), (httpx.Client, "send", send),
        (processor, "MediaDownloader", deny("download")),
        (processor, "transcribe_with_task_progress", deny("asr")),
    ):
        stack.enter_context(patch.object(module, name, replacement))

    def snapshot(task_id):
        task, record = task_record(task_id)
        work = storage.task_dir(task_id)
        hashes = {}
        for name in ("transcript.json", "embedded_subtitle.srt", "draft.md", "draft.partial.md", "partial_note.json", "visual_index.json"):
            file = work / name
            if file.is_file(): hashes[name] = hashlib.sha256(file.read_bytes()).hexdigest()
        for field in ("source_media_path", "media_path"):
            file = Path(getattr(task, field) or "")
            if file.is_file(): hashes[field] = hashlib.sha256(file.read_bytes()).hexdigest()
        assets = {str(file.relative_to(work)): hashlib.sha256(file.read_bytes()).hexdigest()
                  for folder in ("frames", "grids", "vision_cache") for file in (work / folder).glob("*") if file.is_file()}
        partial = storage.read_json(task_id, "partial_note.json", {})
        outline = storage.read_json(task_id, "draft_sections.json", {})
        partial_identity = {key: partial.get(key) for key in ("attempt_id", "source_revision", "generation_revision", "revision", "verified")}
        partial_identity.update(section_ids=[section["id"] for section in partial.get("sections", [])],
            outline_revision=outline.get("revision"),
            projection_revision=partial_revision([outline["revision"], partial["revision"]]) if outline.get("sections") and partial.get("revision") else partial.get("revision"))
        with lock:
            calls = [dict(call) for call in record["calls"]]
            active = record["active"]
        return {"task_id": task_id, "status": task.status, "phase": task.phase, "error_code": task.error_code,
                "error_detail": task.error_detail[:500], "generation": task_generation(task), "hashes": hashes,
                "partial": partial_identity, "assets": assets, "calls": calls, "active_completions": active,
                "queue": read_queue_job(data, task_id), "frame_count": len(storage.read_json(task_id, "visual_index.json", {}).get("frames", [])), "grid_count": len(task.frame_grids),
                "events": read_task_events(task_id, limit=256), "event_snapshot_limit": 256, "transcript": storage.read_json(task_id, "transcript.json", None)}

    @main.app.get("/_fixture/media/{variant}")
    def fixture_media(variant: str):
        if variant not in media: raise HTTPException(404, "Unknown owned input")
        return FileResponse(media[variant], media_type="video/mp4", filename=f"synthetic-visual-{variant}.mp4")

    @main.app.get("/_fixture/state")
    def state():
        return {"forbidden_attempts": list(forbidden), "forbidden_attempt_count": forbidden_count, "worker_pid": os.getpid(), "options": OPTIONS,
                "media_sha256": hashlib.sha256(media["a"].read_bytes()).hexdigest(), "update_preferences": update_service.get_preferences()}

    @main.app.get("/_fixture/tasks/{task_id}")
    def task_state(task_id: str):
        return snapshot(task_id)

    @main.app.get("/_fixture/diagnostics")
    def diagnostics():
        return thread_locations(root)

    @main.app.post("/_fixture/tasks/{task_id}/release/{number}")
    def release(task_id: str, number: int):
        task, record = task_record(task_id)
        with lock:
            if task.status != "running" or not any(call["batch"] == number and call["state"] == "waiting" for call in record["calls"]):
                raise HTTPException(409, "Only an actually waiting current completion can be released")
            record["gates"][number].set()
        return {"released": number}

    return main.app, {"offline_network": True, "worker_pid": os.getpid(), "options": OPTIONS,
                      "media_sha256": hashlib.sha256(media["a"].read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    shutdown = threading.Event()
    def control():
        for line in sys.stdin:
            if line.strip() == "shutdown":
                shutdown.set(); return
    def start_control():
        startup_phase("control_start")
        threading.Thread(target=control, name="visual-fixture-control", daemon=True).start()
    # One bounded stack dump precedes both callers' existing startup deadlines.
    faulthandler.dump_traceback_later(20, repeat=False)
    with ExitStack() as stack:
        stack.callback(faulthandler.cancel_dump_traceback_later)
        app, fixture = configure_fixture(Path(__file__).resolve().parents[1], args.data_dir.absolute(), stack, shutdown, start_control)
        startup_phase("server_setup")
        import uvicorn
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(128)
            origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
            os.environ["LEARNNOTE_BACKEND_ORIGIN"] = origin
            server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
            def stop_server():
                shutdown.wait(); server.should_exit = True
            threading.Thread(target=stop_server, daemon=True).start()
            startup_phase("server_ready")
            faulthandler.cancel_dump_traceback_later()
            print(json.dumps({"fixture_origin": origin, **fixture}), flush=True)
            server.run(sockets=[listener])


if __name__ == "__main__": main()
