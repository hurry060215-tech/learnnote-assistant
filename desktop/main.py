from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import requests
import uvicorn

from desktop.credentials import delete_secret, read_secret, write_secret


GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/hurry060215-tech/learnnote-assistant/releases/latest"
DESKTOP_MODEL_PROVIDER = "kimi"
DESKTOP_MODEL_BASE_URL = "https://api.moonshot.cn/v1"
DESKTOP_MODEL_NAME = "kimi-k2.6"


class DesktopApi:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def save_model_key(self, provider: str, api_key: str) -> dict:
        write_secret(provider, api_key)
        return {"ok": True, "provider": provider}

    def load_model_key(self, provider: str) -> dict:
        value = read_secret(provider)
        return {"ok": True, "provider": provider, "api_key": value, "configured": bool(value)}

    def delete_model_key(self, provider: str) -> dict:
        return {"ok": True, "provider": provider, "deleted": delete_secret(provider)}

    def open_data_folder(self) -> dict:
        os.startfile(self.data_dir)  # type: ignore[attr-defined]
        return {"ok": True}

    def check_update(self) -> dict:
        try:
            response = requests.get(
                GITHUB_LATEST_RELEASE_API,
                timeout=4.0,
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            payload = response.json()
            tag = str(payload.get("tag_name") or "").lstrip("v")
            url = str(payload.get("html_url") or "")
            return {"ok": True, "latest_version": tag, "release_url": url}
        except (requests.RequestException, ValueError) as exc:
            return {"ok": False, "message": str(exc)}

    def open_release(self, url: str) -> dict:
        if not str(url).startswith("https://github.com/hurry060215-tech/learnnote-assistant/releases/"):
            raise ValueError("Unsupported release URL")
        webbrowser.open(url)
        return {"ok": True}


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


def configure_model_runtime() -> bool:
    api_key = read_secret(DESKTOP_MODEL_PROVIDER)
    if not api_key:
        return False
    os.environ["LEARNNOTE_LLM_API_KEY"] = api_key
    os.environ["LEARNNOTE_LLM_BASE_URL"] = DESKTOP_MODEL_BASE_URL
    os.environ["LEARNNOTE_LLM_MODEL"] = DESKTOP_MODEL_NAME
    return True


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
    configure_model_runtime()

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
            js_api=DesktopApi(data_dir),
        )
        window.events.loaded += lambda: window.set_title("LearnNote - Video Learning Notes")
        webview.start(debug=args.debug, private_mode=False)
    finally:
        server.should_exit = True
        thread.join(timeout=8)

    print(f"LearnNote Desktop closed. Data kept at {data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
