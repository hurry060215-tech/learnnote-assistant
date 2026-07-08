from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_PORT = 8765
SAMPLES_PORT = 8777


def project_python() -> str:
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def request_json(method: str, url: str, payload: dict | None = None, timeout: float = 20) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def wait_for_json(url: str, timeout_seconds: float = 45) -> dict:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return request_json("GET", url, timeout=3)
        except Exception as exc:  # noqa: BLE001 - surface latest startup error below
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def start_process(command: list[str], *, cwd: Path, log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(command, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, text=True)


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)


def candidate(url: str, *, kind: str, source: str = "e2e", **extra: object) -> dict:
    base = {
        "url": url,
        "kind": kind,
        "source": source,
        "score": 100,
        "label": f"E2E {kind}",
        "request_type": "xmlhttprequest" if kind == "unknown" else "media",
    }
    base.update(extra)
    return base


def preflight(backend: str, page_url: str, resource: dict, label: str) -> dict:
    result = request_json("POST", f"{backend}/api/media/preflight", {
        "page_url": page_url,
        "resource": resource,
        "cookies": [],
    })["preflight"]
    if not result.get("downloadable"):
        raise AssertionError(f"{label} preflight failed: {result}")
    print(f"PASS preflight {label}: {result.get('kind') or resource.get('kind')} / {result.get('strategy')}")
    return result


def start_download_only_task(backend: str, page_url: str, resource: dict) -> dict:
    payload = {
        "mode": "download_only",
        "page_url": page_url,
        "title": "E2E MP4 download-only",
        "page_text": "local e2e smoke",
        "resources": [resource],
        "cookies": [],
        "options": {
            "visual_understanding": False,
            "frame_interval": 20,
            "grid_columns": 3,
            "grid_rows": 3,
            "transcriber": "faster-whisper",
            "whisper_model": "small",
            "note_style": "study",
            "note_template": "standard",
            "summary_depth": "brief",
        },
    }
    created = request_json("POST", f"{backend}/api/tasks/from-current-page", payload)
    task_id = created["task_id"]
    deadline = time.time() + 60
    latest: dict = {}
    while time.time() < deadline:
        latest = request_json("GET", f"{backend}/api/tasks/{task_id}")
        task = latest.get("task", latest)
        if task.get("status") in {"success", "failed"}:
            break
        time.sleep(0.8)
    task = latest.get("task", latest)
    if task.get("status") != "success" or not task.get("media_path"):
        raise AssertionError(f"download-only task did not produce media: {task}")
    print(f"PASS task download_only: {task_id} -> {task.get('media_path')}")
    return task


def launch_browser_if_available(sample_home: str, open_browser: bool) -> None:
    if not open_browser:
        return
    paths = [
        Path(os.environ.get("LEARNNOTE_E2E_BROWSER", "")),
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    ]
    browser = next((path for path in paths if str(path) and path.exists()), None)
    if not browser:
        print("SKIP browser launch: Chrome/Edge executable not found")
        return
    profile_dir = Path(tempfile.mkdtemp(prefix="learnnote-e2e-profile-"))
    command = [
        str(browser),
        f"--user-data-dir={profile_dir}",
        f"--load-extension={ROOT / 'extension'}",
        "--no-first-run",
        "--disable-first-run-ui",
        sample_home,
    ]
    subprocess.Popen(command)
    print(f"OPENED browser with temporary profile: {sample_home}")
    print(f"Extension path: {ROOT / 'extension'}")
    print(f"Temp profile: {profile_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local LearnNote backend/sample smoke checks.")
    parser.add_argument("--backend-port", type=int, default=BACKEND_PORT)
    parser.add_argument("--samples-port", type=int, default=SAMPLES_PORT)
    parser.add_argument("--open-browser", action="store_true", help="Launch Chrome/Edge with a temporary profile and the unpacked extension.")
    args = parser.parse_args()

    python = project_python()
    log_dir = ROOT / "data" / "test-runs" / "e2e-logs"
    backend = f"http://127.0.0.1:{args.backend_port}"
    samples = f"http://127.0.0.1:{args.samples_port}"
    backend_process: subprocess.Popen | None = None
    samples_process: subprocess.Popen | None = None

    try:
        backend_process = start_process(
            [python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.backend_port)],
            cwd=ROOT / "backend",
            log_path=log_dir / "backend.log",
        )
        samples_process = start_process(
            [python, str(ROOT / "scripts" / "serve-samples.py"), "--port", str(args.samples_port)],
            cwd=ROOT,
            log_path=log_dir / "samples.log",
        )
        health = wait_for_json(f"{backend}/health")
        data_root = health.get("data_paths", {}).get("root") or ""
        print(
            "PASS backend health: "
            f"ffmpeg={health.get('ffmpeg')} "
            f"local_asr={health.get('local_asr_available')} "
            f"data_root={data_root}"
        )
        urllib.request.urlopen(f"{samples}/", timeout=10).read()
        print(f"PASS sample site: {samples}")

        mp4_url = f"{samples}/media/sample.mp4"
        hls_url = f"{samples}/hls/master.m3u8"
        post_url = f"{samples}/api/play"
        page_url = f"{samples}/mp4.html"

        mp4 = candidate(mp4_url, kind="video", source="dom", request_headers={"Referer": page_url})
        hls = candidate(hls_url, kind="hls", source="dom", request_headers={"Referer": f"{samples}/hls.html"})
        post = candidate(
            post_url,
            kind="unknown",
            source="webRequest",
            request_type="xmlhttprequest",
            method="POST",
            request_headers={"Referer": f"{samples}/post-api.html", "Origin": samples, "X-Requested-With": "XMLHttpRequest"},
            request_body={"content": "lesson=smoke&objectid=abc&dtoken=def", "type": "form"},
        )

        preflight(backend, page_url, mp4, "mp4")
        preflight(backend, f"{samples}/hls.html", hls, "hls")
        preflight(backend, f"{samples}/post-api.html", post, "post-play-api")
        start_download_only_task(backend, page_url, mp4)

        report = request_json("POST", f"{backend}/api/media/preflight-current-page", {
            "page_url": f"{samples}/blob-iframe.html",
            "resources": [{
                "url": f"{samples}/player/blob-source.html",
                "kind": "unknown",
                "source": "frame-context",
                "request_type": "page-scan-fallback",
                "frame_url": f"{samples}/player/blob-source.html",
                "page_url": f"{samples}/blob-iframe.html",
                "request_headers": {"Referer": f"{samples}/blob-iframe.html"},
            }],
            "cookies": [],
            "probe_limit": 3,
        })["report"]
        if not (report.get("candidate_count", 0) or report.get("page_scan", {}).get("attempted")):
            raise AssertionError(f"page preflight did not scan iframe context: {report}")
        print(f"PASS page fallback preflight: candidates={report.get('candidate_count')} ready={report.get('ready')}")

        launch_browser_if_available(samples, args.open_browser)
    finally:
        stop_process(samples_process)
        stop_process(backend_process)


if __name__ == "__main__":
    main()
