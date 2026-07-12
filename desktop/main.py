from __future__ import annotations

import argparse
import hashlib
import os
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
import uvicorn

from desktop.credentials import delete_secret, read_secret, write_secret


GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/hurry060215-tech/learnnote-assistant/releases/latest"
GITHUB_LATEST_RELEASE_PAGE = "https://github.com/hurry060215-tech/learnnote-assistant/releases/latest"
GITHUB_RELEASE_BASE = "https://github.com/hurry060215-tech/learnnote-assistant/releases"
WINDOWS_INSTALLER_NAME = "LearnNote-Setup-x64.exe"
MAX_UPDATE_BYTES = 500 * 1024 * 1024
DESKTOP_MODEL_PROVIDER = "kimi"
DESKTOP_MODEL_BASE_URL = "https://api.moonshot.cn/v1"
DESKTOP_MODEL_NAME = "kimi-k2.6"


class DesktopApi:
    EXPORT_TYPES = {
        "markdown": ".md",
        "bundle": ".zip",
        "manifest": ".json",
        "diagnostics": ".md",
        "visual-windows": ".json",
        "subtitles": ".srt",
        "media": ".mp4",
        "audit": ".md",
        "qa": ".json",
        "resource-inventory": ".json",
        "page-preflight-report": ".json",
    }

    def __init__(self, data_dir: Path, backend_url: str = ""):
        self.data_dir = data_dir
        self.backend_url = backend_url.rstrip("/") or os.getenv("LEARNNOTE_BACKEND_ORIGIN", "http://127.0.0.1:8765").rstrip("/")
        self._window = None

    def _bind_window(self, window) -> None:
        self._window = window

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

    def export_task(self, task_id: str, export_type: str) -> dict:
        task_id = str(task_id or "").strip()
        export_type = str(export_type or "").strip().lower()
        clip_match = re.fullmatch(r"clips/(W\d{3})", export_type)
        if not re.fullmatch(r"[a-f0-9]{12}", task_id) or (export_type not in self.EXPORT_TYPES and not clip_match):
            raise ValueError("Unsupported task export")
        fallback_suffix = ".mp4" if clip_match else self.EXPORT_TYPES[export_type]

        response = requests.get(
            f"{self.backend_url}/api/tasks/{task_id}/exports/{export_type}",
            stream=True,
            timeout=(5.0, 180.0),
        )
        response.raise_for_status()
        disposition = response.headers.get("Content-Disposition", "")
        filename_match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, flags=re.I)
        if not filename_match:
            filename_match = re.search(r'filename="?([^";]+)', disposition, flags=re.I)
        filename = unquote(filename_match.group(1)) if filename_match else f"{task_id}-{export_type.replace('/', '-')}{fallback_suffix}"
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", Path(filename).name).strip(" .")
        if not filename:
            filename = f"{task_id}-{export_type.replace('/', '-')}{fallback_suffix}"

        export_dir = (self.data_dir / "exports").resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        target = (export_dir / filename).resolve()
        if target.parent != export_dir:
            raise ValueError("Unsafe export filename")
        stem, suffix = target.stem, target.suffix
        index = 2
        while target.exists():
            target = export_dir / f"{stem} ({index}){suffix}"
            index += 1
        with target.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)
        return {"ok": True, "path": str(target), "filename": target.name, "bytes": target.stat().st_size}

    def open_export_folder(self) -> dict:
        export_dir = self.data_dir / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(export_dir)  # type: ignore[attr-defined]
        return {"ok": True, "path": str(export_dir)}

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
            installer = next(
                (asset for asset in payload.get("assets") or [] if asset.get("name") == WINDOWS_INSTALLER_NAME),
                {},
            )
            digest = str(installer.get("digest") or "")
            sha256 = digest.removeprefix("sha256:") if digest.startswith("sha256:") else ""
            installer_url = str(installer.get("browser_download_url") or "")
            installable = bool(
                re.fullmatch(r"\d+\.\d+\.\d+", tag)
                and re.fullmatch(r"[a-fA-F0-9]{64}", sha256)
                and self._valid_installer_url(tag, installer_url)
            )
            result = {
                "ok": True,
                "latest_version": tag,
                "release_url": url,
                "installer_url": installer_url if installable else "",
                "installer_sha256": sha256.lower() if installable else "",
                "installable": installable,
            }
            return result if installable else self._check_update_without_api()
        except (requests.RequestException, ValueError):
            try:
                return self._check_update_without_api()
            except (requests.RequestException, ValueError) as exc:
                return {"ok": False, "message": str(exc)}

    def _check_update_without_api(self) -> dict:
        release = requests.get(
            GITHUB_LATEST_RELEASE_PAGE,
            timeout=8.0,
            allow_redirects=True,
            headers={"User-Agent": "LearnNote-Desktop-Updater"},
        )
        release.raise_for_status()
        match = re.fullmatch(
            r"https://github\.com/hurry060215-tech/learnnote-assistant/releases/tag/v(\d+\.\d+\.\d+)/?",
            str(release.url or ""),
        )
        if not match:
            raise ValueError("GitHub latest release redirect is invalid")
        version = match.group(1)
        asset_base = f"{GITHUB_RELEASE_BASE}/download/v{version}"
        checksums = requests.get(
            f"{asset_base}/SHA256SUMS.txt",
            timeout=8.0,
            headers={"User-Agent": "LearnNote-Desktop-Updater"},
        )
        checksums.raise_for_status()
        checksum_match = re.search(
            rf"(?mi)^([a-f0-9]{{64}})\s+\*?{re.escape(WINDOWS_INSTALLER_NAME)}\s*$",
            checksums.text,
        )
        if not checksum_match:
            raise ValueError("Release checksum file does not contain the Windows installer")
        installer_url = f"{asset_base}/{WINDOWS_INSTALLER_NAME}"
        return {
            "ok": True,
            "latest_version": version,
            "release_url": f"{GITHUB_RELEASE_BASE}/tag/v{version}",
            "installer_url": installer_url,
            "installer_sha256": checksum_match.group(1).lower(),
            "installable": True,
        }

    @staticmethod
    def _valid_installer_url(version: str, url: str) -> bool:
        parsed = urlparse(str(url or ""))
        expected_path = f"/hurry060215-tech/learnnote-assistant/releases/download/v{version}/{WINDOWS_INSTALLER_NAME}"
        return parsed.scheme == "https" and parsed.netloc == "github.com" and parsed.path == expected_path and not parsed.query

    def download_update(self, version: str, url: str, sha256: str) -> dict:
        version = str(version or "").strip()
        sha256 = str(sha256 or "").strip().lower()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not self._valid_installer_url(version, url):
            raise ValueError("Unsupported update installer URL")
        if not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise ValueError("Invalid update checksum")

        update_dir = (self.data_dir / "installers" / f"v{version}").resolve()
        update_dir.mkdir(parents=True, exist_ok=True)
        target = (update_dir / WINDOWS_INSTALLER_NAME).resolve()
        partial = target.with_suffix(".download")
        if target.parent != update_dir or partial.parent != update_dir:
            raise ValueError("Unsafe update path")

        if target.is_file() and target.stat().st_size <= MAX_UPDATE_BYTES:
            cached_digest = hashlib.sha256()
            with target.open("rb") as existing:
                for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                    cached_digest.update(chunk)
            if cached_digest.hexdigest() == sha256:
                return {
                    "ok": True,
                    "path": str(target),
                    "version": version,
                    "bytes": target.stat().st_size,
                    "sha256": sha256,
                    "cached": True,
                }
            target.unlink()

        response = requests.get(
            url,
            stream=True,
            timeout=(5.0, 300.0),
            headers={"Accept": "application/octet-stream", "User-Agent": "LearnNote-Desktop-Updater"},
        )
        response.raise_for_status()
        content_length = int(response.headers.get("Content-Length") or 0)
        if content_length > MAX_UPDATE_BYTES:
            raise ValueError("Update installer is unexpectedly large")

        digest = hashlib.sha256()
        written = 0
        try:
            with partial.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > MAX_UPDATE_BYTES:
                        raise ValueError("Update installer is unexpectedly large")
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != sha256:
                raise ValueError("Update installer checksum mismatch")
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return {"ok": True, "path": str(target), "version": version, "bytes": written, "sha256": sha256}

    def install_update(self, version: str, installer_path: str) -> dict:
        version = str(version or "").strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("Invalid update version")
        update_dir = (self.data_dir / "installers" / f"v{version}").resolve()
        installer = Path(str(installer_path or "")).resolve()
        if installer != update_dir / WINDOWS_INSTALLER_NAME or not installer.is_file():
            raise ValueError("Update installer is not ready")
        root = application_root().resolve()
        app_path = (root / "LearnNote.exe").resolve()
        if root.drive.upper() == "C:" or not app_path.is_file() or self._window is None:
            raise RuntimeError("Automatic update is only available in the installed desktop client")

        def ps_literal(value: Path | str) -> str:
            return "'" + str(value).replace("'", "''") + "'"

        script_path = update_dir / "install-update.ps1"
        log_path = update_dir / "install.log"
        script = "\n".join([
            "$ErrorActionPreference = 'Stop'",
            f"$parentPid = {os.getpid()}",
            "$parent = Get-Process -Id $parentPid -ErrorAction SilentlyContinue",
            "if ($parent) { Wait-Process -Id $parentPid }",
            f"$installer = {ps_literal(installer)}",
            f"$app = {ps_literal(app_path)}",
            f"$installDir = {ps_literal(root)}",
            f"$log = {ps_literal(log_path)}",
            "$arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/DIR=\"' + $installDir + '\"'), ('/LOG=\"' + $log + '\"'))",
            "$result = Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru",
            "if ($result.ExitCode -eq 0) { Start-Process -FilePath $app -WorkingDirectory $installDir }",
        ]) + "\n"
        script_path.write_text(script, encoding="utf-8-sig")
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            cwd=str(update_dir),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Timer(0.4, self._window.destroy).start()
        return {"ok": True, "installing": True, "version": version}

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

    webview.settings["ALLOW_DOWNLOADS"] = True

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
        desktop_api = DesktopApi(data_dir, backend_url)
        window = webview.create_window(
            "LearnNote",
            backend_url,
            width=1440,
            height=900,
            min_size=(1024, 700),
            background_color="#f6f8fa",
            text_select=True,
            confirm_close=False,
            js_api=desktop_api,
        )
        desktop_api._bind_window(window)
        window.events.loaded += lambda: window.set_title("LearnNote - Video Learning Notes")
        webview.start(debug=args.debug, private_mode=False)
    finally:
        server.should_exit = True
        thread.join(timeout=8)

    print(f"LearnNote Desktop closed. Data kept at {data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
