from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
from pathlib import Path

import requests
import uvicorn


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundled_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", application_root())).resolve()


def available_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No available LearnNote desktop port was found.")


def wait_for_backend(url: str, timeout: float = 25.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{url}/health", timeout=1.0)
            if response.ok:
                return
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(0.15)
    raise RuntimeError(f"LearnNote backend did not start: {last_error or 'health check timed out'}")


def configure_runtime(root: Path, port: int) -> Path:
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["LEARNNOTE_DATA_DIR"] = str(data_dir)
    os.environ["LEARNNOTE_BACKEND_ORIGIN"] = f"http://127.0.0.1:{port}"
    os.environ["LEARNNOTE_DEPLOYMENT_MODE"] = "desktop"

    backend_dir = bundled_root() / "backend"
    if not backend_dir.exists():
        backend_dir = root / "backend"
    sys.path.insert(0, str(backend_dir))
    return data_dir


def run() -> int:
    parser = argparse.ArgumentParser(description="Launch the LearnNote Windows desktop client.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    root = application_root()
    if root.drive.upper() == "C:":
        raise RuntimeError("LearnNote Desktop must be installed on D: or another non-system drive.")
    port = available_port(args.port)
    data_dir = configure_runtime(root, port)

    from app.main import app
    import webview

    backend_url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info" if args.debug else "warning",
        proxy_headers=False,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, name="learnnote-backend", daemon=True)
    thread.start()

    try:
        wait_for_backend(backend_url)
        window = webview.create_window(
            "LearnNote",
            backend_url,
            width=1440,
            height=900,
            min_size=(1024, 700),
            text_select=True,
            confirm_close=False,
        )
        window.events.loaded += lambda: window.set_title("LearnNote - 视频学习笔记")
        webview.start(debug=args.debug, private_mode=False)
    finally:
        server.should_exit = True
        thread.join(timeout=8)

    print(f"LearnNote Desktop closed. Data kept at {data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
